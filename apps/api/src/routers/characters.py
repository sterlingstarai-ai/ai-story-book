from fastapi import APIRouter, Depends, File, UploadFile, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
import random
import uuid
import structlog

from src.core.character_presets import (
    CHARACTER_PRESETS,
    get_preset_localized,
)
from src.core.consent import require_photo_consent
from src.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from src.core.database import get_db
from sqlalchemy.exc import IntegrityError

from src.core.dependencies import get_user_key
from src.routers.books import get_idempotency_key
from src.models.dto import (
    CreateCharacterRequest,
    CharacterResponse,
    CharacterListResponse,
    CharacterAppearance,
    CharacterClothing,
    ImagePrompt,
)
from src.models.db import Character
from src.services.photo_character import photo_character_service
from src.services.storage import storage_service
from src.services.image import generate_image, image_storage_scope
from src.core.utils import utcnow
from src.core.exceptions import (
    AuthorizationError,
    InternalServerError,
    NotFoundError,
    ValidationError,
)

logger = structlog.get_logger()

router = APIRouter()


async def _rollback_safely(
    db: AsyncSession,
    *,
    operation: str,
    error: Exception,
    **log_kwargs,
) -> None:
    try:
        await db.rollback()
    except Exception as rollback_error:
        logger.warning(
            "DB rollback failed",
            operation=operation,
            error=str(rollback_error),
            original_error=str(error),
            **log_kwargs,
        )


_MAX_CHARACTER_IMAGE_BYTES = 10 * 1024 * 1024


async def _validate_and_read_image(upload: UploadFile) -> bytes:
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise ValidationError("이미지 파일만 업로드 가능합니다.")

    contents = await upload.read()
    if len(contents) > _MAX_CHARACTER_IMAGE_BYTES:
        raise ValidationError("파일 크기는 10MB 이하여야 합니다.")
    return contents


def _normalize_character_payload(character_data: dict) -> tuple[dict, dict]:
    appearance = character_data.get("appearance", {})
    clothing = character_data.get("clothing", {})

    normalized_appearance = {
        "age_visual": appearance.get("age_visual", "알 수 없음"),
        "face": (
            f"{appearance.get('eye_color', '')} 눈, "
            f"{appearance.get('distinctive_features', [''])[0] if appearance.get('distinctive_features') else ''}"
        ).strip(", ")
        or "알 수 없음",
        "hair": f"{appearance.get('hair_color', '')} {appearance.get('hair_style', '')}".strip()
        or "알 수 없음",
        "skin": appearance.get("skin_tone", "알 수 없음"),
        "body": appearance.get("body_type", "알 수 없음"),
    }

    accessories_list = clothing.get("accessories", [])
    normalized_clothing = {
        "top": clothing.get("top", "알 수 없음"),
        "bottom": clothing.get("bottom", "알 수 없음"),
        "shoes": clothing.get("shoes", "알 수 없음"),
        "accessories": ", ".join(accessories_list)
        if isinstance(accessories_list, list)
        else str(accessories_list) or "없음",
    }
    return normalized_appearance, normalized_clothing


def _content_type_to_extension(content_type: Optional[str]) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if not content_type:
        return ".jpg"
    return mapping.get(content_type.lower(), ".jpg")


def _build_character_dict(
    character: Character,
    *,
    normalized_appearance: dict,
    normalized_clothing: dict,
) -> dict:
    return {
        "character_id": character.id,
        "name": character.name,
        "master_description": character.master_description,
        "appearance": CharacterAppearance(**normalized_appearance).model_dump(),
        "clothing": CharacterClothing(**normalized_clothing).model_dump(),
        "personality_traits": character.personality_traits,
        "visual_style_notes": character.visual_style_notes,
        "created_at": character.created_at,
    }



async def _existing_by_idempotency_key(
    db: AsyncSession, user_key: str, idempotency_key: Optional[str]
) -> Optional[Character]:
    """같은 시도키로 이미 만든 캐릭터를 반환한다(H17/G19 #9).

    사진·그림 캐릭터 생성은 요청 안에서 vision 분석 + 시트 이미지를 동기 수행해 수분이
    걸린다. 클라 타임아웃 후 서버는 완주하므로, 재시도를 그대로 처리하면 중복 캐릭터가
    쌓이고 vision·이미지 비용이 이중 지출된다. Job/PodOrder 멱등과 동일한 계약.
    """
    if not idempotency_key:
        return None
    return (
        await db.execute(
            select(Character).where(
                Character.user_key == user_key,
                Character.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def _generate_character_sheet_urls(
    *,
    character_data: dict,
    style: str,
    character_id: str,
) -> list[str]:
    scene_prompts = character_data.get("sheet_scene_prompts")
    if not isinstance(scene_prompts, list):
        scene_prompts = []
    normalized_scenes = [
        str(item).strip() for item in scene_prompts if str(item).strip()
    ][:3]

    if not normalized_scenes:
        normalized_scenes = [
            "front full-body pose, neutral smile, clean background",
            "side walking pose, gentle motion, clean background",
            "happy expression pose, arms open, clean background",
        ]

    master_description = character_data.get(
        "master_description",
        "cute storybook character",
    )
    negative_prompt = (
        "blurry, low quality, extra limbs, deformed face, watermark, "
        "logo, text, scary, violent, nsfw"
    )

    urls: list[str] = []
    # 시트 이미지를 캐릭터 스코프 키(characters/{id}/sheets/...)에 저장해 동의 철회/계정
    # 삭제의 delete_prefix가 닿게 한다(추적 불가한 images/{provider}/{uuid} 영구 잔존 방지).
    with image_storage_scope(f"characters/{character_id}/sheets"):
        for index, scene in enumerate(normalized_scenes, start=1):
            prompt_text = (
                f"{master_description}. Character sheet turn-around frame {index}. "
                f"{scene}. Keep identity and colors consistent. "
                f"Children storybook illustration, {style}."
            )

            try:
                image_url = await generate_image(
                    ImagePrompt(
                        page=index,
                        positive_prompt=prompt_text,
                        negative_prompt=negative_prompt,
                        seed=random.randint(1, 2_147_483_647),
                        aspect_ratio="3:4",
                        guidance_notes="character_sheet",
                    )
                )
                if image_url:
                    urls.append(image_url)
            except Exception as exc:
                logger.warning(
                    "Character sheet image generation failed",
                    error=str(exc),
                    frame=index,
                )
    return urls


@router.post("", response_model=CharacterResponse)
async def create_character(
    request: CreateCharacterRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    새 캐릭터 저장

    - 책 생성 후 캐릭터 시트를 저장하여 재사용
    - 시리즈 생성 시 character_id로 참조
    """
    character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    character = Character(
        id=character_id,
        name=request.name,
        master_description=request.master_description,
        appearance=request.appearance.model_dump(),
        clothing=request.clothing.model_dump(),
        personality_traits=request.personality_traits,
        visual_style_notes=request.visual_style_notes,
        distinctive_features=request.distinctive_features,
        user_key=user_key,
    )

    db.add(character)
    try:
        await db.commit()
        await db.refresh(character)
    except Exception as e:
        await _rollback_safely(
            db,
            operation="create_character",
            error=e,
            user_key=user_key[:8] + "...",
        )
        logger.error(
            "Character creation failed",
            user_key=user_key[:8] + "...",
            error=str(e),
        )
        raise InternalServerError(
            "캐릭터 저장에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e

    return CharacterResponse(
        character_id=character.id,
        name=character.name,
        master_description=character.master_description,
        appearance=CharacterAppearance(**character.appearance),
        clothing=CharacterClothing(**character.clothing),
        personality_traits=character.personality_traits,
        visual_style_notes=character.visual_style_notes,
        distinctive_features=character.distinctive_features,
        created_at=character.created_at,
    )


class FromPresetRequest(BaseModel):
    preset_id: str
    name: Optional[str] = None
    language: Optional[str] = None


def _normalize_language(language: Optional[str]) -> str:
    """요청 언어를 지원 언어로 정규화(미지정·미지원은 기본 언어 ko 폴백)."""
    if language and language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


@router.get("/presets")
async def list_character_presets(language: Optional[str] = None):
    """기본 제공 캐릭터 프리셋 목록(외형 묘사 + 썸네일 asset). '기본 이미지 선택' 경로.

    language 로 표시 텍스트(name/appearance/clothing/visual_style_notes)를 로케일별로
    서빙한다(미지정·미지원은 ko 폴백). master_description 은 이미지 최적 영어로 고정.
    """
    lang = _normalize_language(language)
    presets = [
        get_preset_localized(preset["preset_id"], lang) for preset in CHARACTER_PRESETS
    ]
    return {"presets": presets}


@router.post("/from-preset", response_model=CharacterResponse)
async def create_character_from_preset(
    request: FromPresetRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """기본 캐릭터 프리셋으로 주인공 캐릭터를 생성한다(아이 이름 지정 가능).

    표시 텍스트(name/appearance/clothing/visual_style_notes)는 요청 언어로 저장하고,
    master_description 은 이미지 최적 영어로 고정 저장한다(G31 불변식).
    """
    lang = _normalize_language(request.language)
    preset = get_preset_localized(request.preset_id, lang)
    if preset is None:
        raise NotFoundError("캐릭터 프리셋", request.preset_id)

    character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    character = Character(
        id=character_id,
        name=request.name or preset["name"],
        master_description=preset["master_description"],
        appearance=preset["appearance"],
        clothing=preset["clothing"],
        personality_traits=preset["personality_traits"],
        visual_style_notes=preset["visual_style_notes"],
        user_key=user_key,
    )
    db.add(character)
    try:
        await db.commit()
        await db.refresh(character)
    except Exception as e:
        await _rollback_safely(
            db,
            operation="create_character_from_preset",
            error=e,
            user_key=user_key[:8] + "...",
        )
        raise InternalServerError(
            "캐릭터 저장에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e

    return CharacterResponse(
        character_id=character.id,
        name=character.name,
        master_description=character.master_description,
        appearance=CharacterAppearance(**character.appearance),
        clothing=CharacterClothing(**character.clothing),
        personality_traits=character.personality_traits,
        visual_style_notes=character.visual_style_notes,
        distinctive_features=character.distinctive_features,
        created_at=character.created_at,
    )


@router.get("", response_model=CharacterListResponse)
async def list_characters(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    limit: int = 20,
    offset: int = 0,
):
    """
    내 캐릭터 목록 조회
    """
    # Validate pagination params
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    # Get total count (efficient COUNT query)
    count_result = await db.execute(
        select(func.count(Character.id)).where(Character.user_key == user_key)
    )
    total = count_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        select(Character)
        .where(Character.user_key == user_key)
        .order_by(Character.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    characters = result.scalars().all()

    return CharacterListResponse(
        characters=[
            CharacterResponse(
                character_id=c.id,
                name=c.name,
                master_description=c.master_description,
                appearance=CharacterAppearance(
                    **{k: v or "알 수 없음" for k, v in c.appearance.items()}
                ),
                clothing=CharacterClothing(
                    **{
                        k: v or "알 수 없음" if k != "accessories" else v or "없음"
                        for k, v in c.clothing.items()
                    }
                ),
                personality_traits=c.personality_traits,
                visual_style_notes=c.visual_style_notes,
                created_at=c.created_at,
            )
            for c in characters
        ],
        total=total,
    )


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    캐릭터 상세 조회
    """
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise NotFoundError("캐릭터", character_id)

    if character.user_key != user_key:
        raise AuthorizationError()

    return CharacterResponse(
        character_id=character.id,
        name=character.name,
        master_description=character.master_description,
        appearance=CharacterAppearance(**character.appearance),
        clothing=CharacterClothing(**character.clothing),
        personality_traits=character.personality_traits,
        visual_style_notes=character.visual_style_notes,
        distinctive_features=character.distinctive_features,
        created_at=character.created_at,
    )


@router.delete("/{character_id}")
async def delete_character(
    character_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    캐릭터 삭제
    """
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise NotFoundError("캐릭터", character_id)

    if character.user_key != user_key:
        raise AuthorizationError()

    # 사진/그림 파생 여부를 행 삭제 전에 확보(삭제 후 원본 스토리지도 파기해야 함).
    was_from_photo = bool(getattr(character, "from_photo", False))

    # H7: series.character_id → characters.id는 단방향 FK(ondelete 없음)라 ORM이
    # 자동 nullify하지 못해 commit에서 IntegrityError 500이 난다. 삭제 전에 명시 해제.
    from sqlalchemy import update
    from src.models.db import Series

    await db.execute(
        update(Series)
        .where(Series.character_id == character_id)
        .values(character_id=None)
    )
    await db.delete(character)
    try:
        await db.commit()
    except Exception as e:
        await _rollback_safely(
            db,
            operation="delete_character",
            error=e,
            user_key=user_key[:8] + "...",
            character_id=character_id,
        )
        logger.error(
            "Character deletion failed",
            user_key=user_key[:8] + "...",
            character_id=character_id,
            error=str(e),
        )
        raise InternalServerError(
            "캐릭터 삭제에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e

    # 사진/그림 파생 캐릭터의 원본(아동 얼굴/그림)도 스토리지에서 파기 — 동의철회·계정삭제
    # 경로와 동일하게 '삭제=원본 즉시 파기' 약속을 집행(고아 사진 영구 잔류 방지, PIPA).
    if was_from_photo:
        try:
            await storage_service.delete_prefix(f"characters/{character_id}/")
        except Exception as storage_error:
            logger.warning(
                "Character storage cleanup failed on delete",
                character_id=character_id,
                error=str(storage_error),
            )

    return {"message": "Character deleted successfully"}


@router.post("/from-text", response_model=CharacterResponse)
async def create_character_from_text(
    name: str = Form(..., description="캐릭터 이름"),
    age: str = Form(..., description="나이 (예: 5살, 30대)"),
    traits: str = Form(..., description="특징/성격 (쉼표로 구분)"),
    style: str = Form("cartoon", description="스타일"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    텍스트 설명으로 캐릭터 생성

    - 이름, 나이, 특징만 입력
    - AI가 나머지 세부사항을 자동 생성
    """
    try:
        # 성격 특성 파싱
        personality_traits = [t.strip() for t in traits.split(",") if t.strip()]

        # AI로 캐릭터 설명 생성 (photo_character_service 재활용)
        character_data = await photo_character_service.create_character_from_text(
            name=name,
            age=age,
            traits=personality_traits,
            style=style,
        )

        # 캐릭터 ID 생성
        character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        character = Character(
            id=character_id,
            name=character_data["name"],
            master_description=character_data["master_description"],
            appearance=character_data["appearance"],
            clothing=character_data["clothing"],
            personality_traits=character_data.get(
                "personality_traits", personality_traits
            ),
            visual_style_notes=character_data.get("visual_style_notes", ""),
            distinctive_features=character_data.get("distinctive_features"),
            user_key=user_key,
        )

        db.add(character)
        await db.commit()
        await db.refresh(character)

        return CharacterResponse(
            character_id=character.id,
            name=character.name,
            master_description=character.master_description,
            appearance=CharacterAppearance(
                **{k: v or "알 수 없음" for k, v in character.appearance.items()}
            ),
            clothing=CharacterClothing(
                **{
                    k: v or "알 수 없음" if k != "accessories" else v or "없음"
                    for k, v in character.clothing.items()
                }
            ),
            personality_traits=character.personality_traits,
            visual_style_notes=character.visual_style_notes,
            distinctive_features=character.distinctive_features,
            created_at=character.created_at,
        )

    except Exception as e:
        await _rollback_safely(
            db,
            operation="create_character_from_text",
            error=e,
            user_key=user_key[:8] + "...",
        )
        logger.error("Character creation from text failed", error=str(e))
        raise InternalServerError(
            "캐릭터 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e


@router.post("/from-photo", response_model=CharacterResponse)
async def create_character_from_photo(
    photo: UploadFile = File(..., description="캐릭터 생성용 사진"),
    name: Optional[str] = Form(None, description="캐릭터 이름 (없으면 AI 제안)"),
    style: str = Form("cartoon", description="스타일"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """
    사진에서 캐릭터 생성

    - 사진을 분석하여 캐릭터 특성 추출
    - AI가 동화 스타일로 변환
    - 자동으로 캐릭터 시트 생성
    - `X-Idempotency-Key`를 보내면 재시도가 기존 캐릭터를 그대로 반환한다(재분석 없음)
    """
    await require_photo_consent(db, user_key)

    # H17/G19 #9: 같은 시도키의 재요청은 재분석·재업로드 없이 기존 결과를 반환.
    existing = await _existing_by_idempotency_key(db, user_key, idempotency_key)
    if existing is not None:
        return CharacterResponse(**_build_character_dict(
            existing,
            normalized_appearance=existing.appearance or {},
            normalized_clothing=existing.clothing or {},
        ))

    contents = await _validate_and_read_image(photo)

    try:
        character_data = await photo_character_service.create_character_from_photo(
            image_data=contents,
            user_name=name,
            style=style,
        )

        character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        ext = _content_type_to_extension(photo.content_type)
        photo_key = f"characters/{character_id}/photo{ext}"
        source_image_url = await storage_service.upload_bytes(
            data=contents,
            key=photo_key,
            content_type=photo.content_type or "image/jpeg",
        )

        normalized_appearance, normalized_clothing = _normalize_character_payload(
            character_data
        )

        character = Character(
            id=character_id,
            name=character_data["name"],
            master_description=character_data["master_description"],
            appearance=normalized_appearance,
            clothing=normalized_clothing,
            personality_traits=character_data.get("personality_traits", []),
            visual_style_notes=character_data.get("visual_style_notes", ""),
            user_key=user_key,
            from_photo=True,
            source_image_url=source_image_url,
            idempotency_key=idempotency_key,
        )

        db.add(character)
        try:
            await db.commit()
        except IntegrityError:
            # 동시 더블탭: 둘 다 pre-check를 통과해 부분 유니크에서 패배한 쪽.
            # 500 대신 승자의 캐릭터를 멱등 반환한다(중복 생성은 DB가 이미 차단).
            await db.rollback()
            winner = await _existing_by_idempotency_key(db, user_key, idempotency_key)
            if winner is None:
                raise
            return CharacterResponse(**_build_character_dict(
                winner,
                normalized_appearance=winner.appearance or {},
                normalized_clothing=winner.clothing or {},
            ))
        await db.refresh(character)

        return CharacterResponse(**_build_character_dict(
            character,
            normalized_appearance=normalized_appearance,
            normalized_clothing=normalized_clothing,
        ))

    except Exception as e:
        await _rollback_safely(
            db,
            operation="create_character_from_photo",
            error=e,
            user_key=user_key[:8] + "...",
        )
        logger.error("Character creation from photo failed", error=str(e))
        raise InternalServerError(
            "캐릭터 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e


@router.post("/from-drawing")
async def create_character_from_drawing(
    drawing: UploadFile = File(..., description="아이 그림 이미지"),
    name: Optional[str] = Form(None, description="캐릭터 이름 (없으면 AI 제안)"),
    style: str = Form("storybook_crayon", description="스타일"),
    generate_sheet: bool = Form(True, description="캐릭터 시트 생성 여부"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """
    아이 그림을 캐릭터로 변환한다.

    - 그림 분석으로 캐릭터 외형/성격 추론
    - 캐릭터 레코드 저장
    - 선택적으로 캐릭터 시트 이미지(포즈 3종) 생성
    - `X-Idempotency-Key`를 보내면 재시도가 기존 캐릭터를 반환한다(재분석·시트 재생성 없음).
      시트 URL은 생성 시점 provider 반환값이라 재현 불가 — 재시도 응답에서는 빈 배열이다.
    """
    await require_photo_consent(db, user_key)

    # H17/G19 #9: 같은 시도키의 재요청은 그림 재분석·시트 재생성 없이 기존 결과를 반환.
    existing = await _existing_by_idempotency_key(db, user_key, idempotency_key)
    if existing is not None:
        return {
            **_build_character_dict(
                existing,
                normalized_appearance=existing.appearance or {},
                normalized_clothing=existing.clothing or {},
            ),
            "source_image_url": existing.source_image_url,
            "character_sheet_urls": [],
        }

    contents = await _validate_and_read_image(drawing)
    source_image_url: Optional[str] = None

    try:
        character_data = await photo_character_service.create_character_from_drawing(
            image_data=contents,
            user_name=name,
            style=style,
        )

        character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        ext = _content_type_to_extension(drawing.content_type)
        drawing_key = f"characters/{character_id}/drawing{ext}"
        try:
            source_image_url = await storage_service.upload_bytes(
                data=contents,
                key=drawing_key,
                content_type=drawing.content_type or "image/jpeg",
            )
        except Exception as storage_error:
            logger.warning(
                "Source drawing upload failed; continuing without stored source URL",
                error=str(storage_error),
            )

        normalized_appearance, normalized_clothing = _normalize_character_payload(
            character_data
        )

        character = Character(
            id=character_id,
            name=character_data["name"],
            master_description=character_data["master_description"],
            appearance=normalized_appearance,
            clothing=normalized_clothing,
            personality_traits=character_data.get("personality_traits", []),
            visual_style_notes=character_data.get("visual_style_notes", ""),
            user_key=user_key,
            from_photo=True,
            source_image_url=source_image_url,
            idempotency_key=idempotency_key,
        )
        db.add(character)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            winner = await _existing_by_idempotency_key(db, user_key, idempotency_key)
            if winner is None:
                raise
            return {
                **_build_character_dict(
                    winner,
                    normalized_appearance=winner.appearance or {},
                    normalized_clothing=winner.clothing or {},
                ),
                "source_image_url": winner.source_image_url,
                "character_sheet_urls": [],
            }
        await db.refresh(character)

        sheet_urls: list[str] = []
        if generate_sheet:
            sheet_urls = await _generate_character_sheet_urls(
                character_data=character_data,
                style=style,
                character_id=character_id,
            )

        base = _build_character_dict(
            character,
            normalized_appearance=normalized_appearance,
            normalized_clothing=normalized_clothing,
        )
        return {
            **base,
            "source_image_url": source_image_url,
            "character_sheet_urls": sheet_urls,
        }
    except Exception as e:
        await _rollback_safely(
            db,
            operation="create_character_from_drawing",
            error=e,
            user_key=user_key[:8] + "...",
        )
        logger.error("Character creation from drawing failed", error=str(e))
        raise InternalServerError(
            "그림 기반 캐릭터 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e
