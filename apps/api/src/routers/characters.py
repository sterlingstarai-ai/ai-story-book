from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid
from datetime import datetime, timezone

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.models.dto import (
    CreateCharacterRequest,
    CharacterResponse,
    CharacterListResponse,
    CharacterAppearance,
    CharacterClothing,
)
from src.models.db import Character
from src.services.photo_character import photo_character_service
from src.services.storage import storage_service


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

router = APIRouter()


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
        user_key=user_key,
    )

    db.add(character)
    await db.commit()
    await db.refresh(character)

    return CharacterResponse(
        character_id=character.id,
        name=character.name,
        master_description=character.master_description,
        appearance=CharacterAppearance(**character.appearance),
        clothing=CharacterClothing(**character.clothing),
        personality_traits=character.personality_traits,
        visual_style_notes=character.visual_style_notes,
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
    # Get total count
    count_result = await db.execute(
        select(Character).where(Character.user_key == user_key)
    )
    total = len(count_result.scalars().all())

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
        raise HTTPException(status_code=404, detail="Character not found")

    if character.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    return CharacterResponse(
        character_id=character.id,
        name=character.name,
        master_description=character.master_description,
        appearance=CharacterAppearance(**character.appearance),
        clothing=CharacterClothing(**character.clothing),
        personality_traits=character.personality_traits,
        visual_style_notes=character.visual_style_notes,
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
        raise HTTPException(status_code=404, detail="Character not found")

    if character.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    await db.delete(character)
    await db.commit()

    return {"message": "Character deleted successfully"}


@router.post("/from-text")
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
        character_id = (
            f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        )

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
            user_key=user_key,
        )

        db.add(character)
        await db.commit()
        await db.refresh(character)

        return {
            "character_id": character.id,
            "name": character.name,
            "master_description": character.master_description,
            "appearance": character.appearance,
            "clothing": character.clothing,
            "personality_traits": character.personality_traits,
            "visual_style_notes": character.visual_style_notes,
            "created_at": character.created_at.isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"캐릭터 생성 실패: {str(e)}")


@router.post("/from-photo")
async def create_character_from_photo(
    photo: UploadFile = File(..., description="캐릭터 생성용 사진"),
    name: Optional[str] = Form(None, description="캐릭터 이름 (없으면 AI 제안)"),
    style: str = Form("cartoon", description="스타일"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    사진에서 캐릭터 생성

    - 사진을 분석하여 캐릭터 특성 추출
    - AI가 동화 스타일로 변환
    - 자동으로 캐릭터 시트 생성
    """
    # 파일 검증
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")

    # 파일 크기 제한 (10MB)
    contents = await photo.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다.")

    try:
        # 사진 분석 및 캐릭터 데이터 생성
        character_data = await photo_character_service.create_character_from_photo(
            image_data=contents,
            user_name=name,
            style=style,
        )

        # 캐릭터 ID 생성
        character_id = (
            f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        )

        # 원본 사진 저장
        photo_key = f"characters/{character_id}/photo.jpg"
        photo_url = await storage_service.upload_bytes(
            data=contents,
            key=photo_key,
            content_type=photo.content_type or "image/jpeg",
        )

        # 캐릭터 생성 - CharacterResponse 스키마에 맞게 정규화
        appearance = character_data.get("appearance", {})
        clothing = character_data.get("clothing", {})

        # Convert from-photo format to standard CharacterAppearance format
        normalized_appearance = {
            "age_visual": appearance.get("age_visual", "알 수 없음"),
            "face": f"{appearance.get('eye_color', '')} 눈, {appearance.get('distinctive_features', [''])[0] if appearance.get('distinctive_features') else ''}".strip(
                ", "
            )
            or "알 수 없음",
            "hair": f"{appearance.get('hair_color', '')} {appearance.get('hair_style', '')}".strip()
            or "알 수 없음",
            "skin": appearance.get("skin_tone", "알 수 없음"),
            "body": appearance.get("body_type", "알 수 없음"),
        }

        # Convert clothing - accessories as string, not list
        accessories_list = clothing.get("accessories", [])
        normalized_clothing = {
            "top": clothing.get("top", "알 수 없음"),
            "bottom": clothing.get("bottom", "알 수 없음"),
            "shoes": clothing.get("shoes", "알 수 없음"),
            "accessories": ", ".join(accessories_list)
            if isinstance(accessories_list, list)
            else str(accessories_list) or "없음",
        }

        character = Character(
            id=character_id,
            name=character_data["name"],
            master_description=character_data["master_description"],
            appearance=normalized_appearance,
            clothing=normalized_clothing,
            personality_traits=character_data.get("personality_traits", []),
            visual_style_notes=character_data.get("visual_style_notes", ""),
            user_key=user_key,
        )

        db.add(character)
        await db.commit()
        await db.refresh(character)

        return {
            "character_id": character.id,
            "name": character.name,
            "master_description": character.master_description,
            "appearance": character.appearance,
            "clothing": character.clothing,
            "personality_traits": character.personality_traits,
            "visual_style_notes": character.visual_style_notes,
            "photo_url": photo_url,
            "photo_analysis": character_data.get("photo_analysis", {}),
            "created_at": character.created_at.isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"캐릭터 생성 실패: {str(e)}")
