"""
Photo-based Character Service
사진에서 캐릭터 생성
"""

import asyncio
import base64
import json
import re
import httpx
import structlog
from typing import Optional

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError, get_backoff, get_retry_count
from src.models.dto import CreateCharacterRequest
from src.services.anthropic_contract import (
    anthropic_generation_options,
    anthropic_response_text,
)
from src.services.llm import _call_gemini, parse_json_response
from src.services.openai_contract import request_openai_json

logger = structlog.get_logger()


def validate_text_character(data: dict) -> CreateCharacterRequest:
    """Validate before persistence, normalizing only unambiguous empty attire.

    Animals may have fur rather than hair and no trousers or shoes. Preserve
    their actual description; do not invent human features or stringify objects.
    Extra keys and genuinely malformed/overlong values must still fail schema
    validation, whose diagnostics contain only owned field names and types.
    """
    if isinstance(data, dict):
        data = dict(data)
        for section in ("appearance", "clothing"):
            values = data.get(section)
            if not isinstance(values, dict):
                continue
            values = dict(values)
            for key, value in values.items():
                if isinstance(value, str):
                    values[key] = value.strip()
            if section == "appearance" and "hair" in values:
                if values["hair"] is None or values["hair"] == "":
                    values["hair"] = "없음"
            if section == "clothing":
                accessories = values.get("accessories")
                if isinstance(accessories, list) and all(
                    isinstance(item, str) for item in accessories
                ):
                    values["accessories"] = ", ".join(
                        item.strip() for item in accessories if item.strip()
                    )
                for key in ("top", "bottom", "shoes", "accessories"):
                    if key in values and (values[key] is None or values[key] == ""):
                        values[key] = "없음"
            data[section] = values
    # Reuse the owned DTO diagnostic boundary. No raw response or validation
    # exception is logged or attached to the domain error.
    return parse_json_response(json.dumps(data, ensure_ascii=False), CreateCharacterRequest)


class PhotoCharacterService:
    """사진 기반 캐릭터 생성 서비스"""

    @property
    def llm_provider(self):
        return settings.llm_provider

    @property
    def api_key(self):
        return settings.llm_api_key

    @staticmethod
    def _parse_object(content: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", content)
        try:
            value = json.loads(match.group() if match else content)
        except (TypeError, ValueError):
            # JSONDecodeError retains the complete child/provider text in .doc.
            # Keep only the owned domain error at the adapter boundary.
            raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid character response") from None
        if not isinstance(value, dict) or not value:
            raise LLMError(ErrorCode.LLM_JSON_INVALID, "Empty character response")
        return value

    async def _analyze_with_gemini(self, image_base64: str, prompt: str) -> dict:
        raw = base64.b64decode(image_base64)
        mime = "image/png" if raw.startswith(b"\x89PNG") else "image/jpeg"
        if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            mime = "image/webp"
        elif raw.startswith((b"GIF87a", b"GIF89a")):
            mime = "image/gif"
        text = await _call_gemini(
            "Analyze the supplied image and return only the requested JSON.",
            prompt, 1500, 0.3, image_base64=image_base64, image_mime_type=mime,
        )
        return self._parse_object(text)

    async def analyze_photo(self, image_data: bytes) -> dict:
        """
        사진 분석하여 캐릭터 특성 추출

        Args:
            image_data: 이미지 바이트 데이터

        Returns:
            분석된 특성 딕셔너리
        """
        return await self._analyze_media(image_data, self._get_analysis_prompt())

    async def analyze_drawing(self, image_data: bytes) -> dict:
        return await self._analyze_media(image_data, self._get_drawing_analysis_prompt())

    async def _analyze_media(self, image_data: bytes, prompt: str) -> dict:
        # Photo configuration never inherits the writing provider or its key.
        # Both photographic and drawing uploads contain potentially child data.
        from src.services.photo_processing import ensure_photo_processing_ready

        ensure_photo_processing_ready()
        if settings.photo_analysis_provider == "mock":
            return self._mock_analysis()
        encoded = base64.b64encode(image_data).decode("ascii")
        # Upload boundaries normalize media to JPEG before dispatch. Preserve PNG
        # for callers using a normalized illustration as the analysis source.
        mime = "image/png" if image_data.startswith(b"\x89PNG") else "image/jpeg"
        content = await request_openai_json(
            model=settings.photo_analysis_model,
            api_key=settings.photo_analysis_api_key,
            timeout=settings.llm_timeout,
            user_prompt=prompt,
            max_tokens=1500,
            image_url=f"data:{mime};base64,{encoded}",
        )
        return self._parse_object(content)

    async def _analyze_with_openai(self, image_base64: str, prompt: str) -> dict:
        """OpenAI Vision API로 분석"""
        content = await request_openai_json(
            model=settings.llm_model, api_key=self.api_key,
            timeout=settings.llm_timeout, user_prompt=prompt, max_tokens=1000,
            image_url=f"data:image/jpeg;base64,{image_base64}",
        )
        try:
            return self._parse_object(content)
        except json.JSONDecodeError:
            logger.error("OpenAI vision returned invalid JSON")
            raise

    async def _analyze_with_anthropic(self, image_base64: str, prompt: str) -> dict:
        """Anthropic Claude Vision으로 분석"""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": 1000,
                    **anthropic_generation_options(settings.llm_model),
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": image_base64,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": prompt,
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()

            content = anthropic_response_text(data)
            try:
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    return self._parse_object(json_match.group())
                return self._parse_object(content)
            except json.JSONDecodeError:
                # M21: 실 프로바이더 파싱 실패를 mock으로 삼키지 않고 raise(fail-open 제거).
                logger.error("Anthropic vision returned invalid JSON", response_length=len(content))
                raise

    def _get_analysis_prompt(self) -> str:
        """분석 프롬프트"""
        return """이 사진을 분석해서 동화책 캐릭터로 변환해주세요.
사진 속 인물/동물/캐릭터의 특징을 추출하여 JSON으로 응답해주세요.

응답 형식:
{
    "name_suggestion": "제안할 캐릭터 이름",
    "estimated_age": "어린이/청소년/성인 중 하나",
    "gender": "남성/여성/중성 중 하나",
    "species": "인간/고양이/강아지/토끼/곰 등",
    "appearance": {
        "hair_color": "머리 색상",
        "hair_style": "머리 스타일",
        "eye_color": "눈 색상",
        "skin_tone": "피부톤",
        "distinctive_features": ["특징1", "특징2"]
    },
    "suggested_clothing": {
        "top": "상의 설명",
        "bottom": "하의 설명",
        "accessories": ["악세서리1", "악세서리2"]
    },
    "personality_hints": ["성격 힌트1", "성격 힌트2", "성격 힌트3"],
    "visual_description": "이미지 생성용 상세 외모 설명 (영문, 50단어 이내)"
}

주의사항:
- 동화책에 적합하게 귀엽고 친근한 느낌으로 해석
- 사진의 실제 특징을 기반으로 하되 만화/일러스트 스타일로 변환
- distinctive_features에는 그 아이를 알아볼 수 있는 고유한 얼굴/머리 특징(예: 머리 모양·앞머리·눈 모양·보조개·주근깨 등)을 구체적으로 담아 모든 페이지에서 같은 아이로 일관되게 그려지도록 한다
- visual_description은 영어로 작성하며, 얼굴·머리·피부 등 정체성 식별이 가능한 외형을 또렷이 고정해 같은 아이가 반복 등장하도록 한다
"""

    def _get_drawing_analysis_prompt(self) -> str:
        """아이 그림 분석 프롬프트"""
        return """이 이미지는 아이가 그린 그림일 가능성이 높습니다.
그림 속 캐릭터를 존중하면서 동화책용 캐릭터 시트로 확장 가능한 JSON을 만들어주세요.

응답 형식:
{
    "name_suggestion": "제안할 캐릭터 이름",
    "estimated_age": "어린이/청소년/성인 중 하나",
    "gender": "남성/여성/중성 중 하나",
    "species": "인간/고양이/강아지/토끼/공룡/로봇 등",
    "appearance": {
        "hair_color": "머리 색상",
        "hair_style": "머리 스타일",
        "eye_color": "눈 색상",
        "skin_tone": "피부/외피 톤",
        "distinctive_features": ["특징1", "특징2"]
    },
    "suggested_clothing": {
        "top": "상의 설명",
        "bottom": "하의 설명",
        "accessories": ["악세서리1", "악세서리2"]
    },
    "personality_hints": ["성격 힌트1", "성격 힌트2", "성격 힌트3"],
    "visual_description": "이미지 생성용 상세 외모 설명 (영문, 60단어 이내)",
    "sheet_scene_prompts": [
        "정면 전신 포즈 설명 (영문)",
        "측면 걷기 포즈 설명 (영문)",
        "감정 표현 포즈 설명 (영문)"
    ]
}

주의사항:
- 아이 그림의 색감/형태적 특징을 최대한 유지
- 과도하게 사실적으로 바꾸지 말고 동화책 일러스트 톤 유지
- visual_description, sheet_scene_prompts는 영어로 작성
"""

    def _mock_analysis(self) -> dict:
        """테스트용 Mock 응답"""
        return {
            "name_suggestion": "미미",
            "estimated_age": "어린이",
            "gender": "여성",
            "species": "인간",
            "appearance": {
                "hair_color": "검은색",
                "hair_style": "양갈래",
                "eye_color": "갈색",
                "skin_tone": "밝은 피부",
                "distinctive_features": ["귀여운 볼", "밝은 미소"],
            },
            "suggested_clothing": {
                "top": "분홍색 원피스",
                "bottom": "",
                "accessories": ["꽃 머리핀"],
            },
            "personality_hints": ["호기심 많은", "활발한", "친절한"],
            "visual_description": "cute young girl with black pigtails, brown eyes, rosy cheeks, bright smile, wearing pink dress with flower hairpin, cartoon illustration style",
        }

    async def create_character_from_photo(
        self,
        image_data: bytes,
        user_name: Optional[str] = None,
        style: str = "cartoon",
    ) -> dict:
        """
        사진에서 캐릭터 생성

        Args:
            image_data: 이미지 바이트
            user_name: 사용자가 지정한 이름 (없으면 AI 제안 사용)
            style: 스타일 (cartoon, watercolor 등)

        Returns:
            캐릭터 생성용 데이터
        """
        # 사진 분석
        analysis = await self.analyze_photo(image_data)

        # 캐릭터 데이터 구성
        character_data = {
            "name": user_name or analysis.get("name_suggestion", "캐릭터"),
            "master_description": analysis.get(
                "visual_description", "cute cartoon character"
            ),
            "appearance": analysis.get("appearance", {}),
            "clothing": analysis.get("suggested_clothing", {}),
            "personality_traits": analysis.get(
                "personality_hints", ["친절한", "용감한"]
            ),
            "visual_style_notes": f"{style} style illustration based on photo reference",
            "photo_analysis": analysis,  # 원본 분석 결과 보존
        }

        return character_data

    async def create_character_from_drawing(
        self,
        image_data: bytes,
        user_name: Optional[str] = None,
        style: str = "storybook_crayon",
    ) -> dict:
        """
        아이 그림에서 캐릭터 생성 + 캐릭터 시트 프롬프트 생성
        """
        analysis = await self.analyze_drawing(image_data)

        sheet_scene_prompts = analysis.get("sheet_scene_prompts")
        if not isinstance(sheet_scene_prompts, list):
            sheet_scene_prompts = [
                "front full-body pose, neutral smile, clean background",
                "side walking pose, gentle motion, clean background",
                "happy jumping pose, expressive face, clean background",
            ]

        character_data = {
            "name": user_name or analysis.get("name_suggestion", "캐릭터"),
            "master_description": analysis.get(
                "visual_description", "cute storybook character based on child drawing"
            ),
            "appearance": analysis.get("appearance", {}),
            "clothing": analysis.get("suggested_clothing", {}),
            "personality_traits": analysis.get(
                "personality_hints", ["상상력이 풍부한", "용감한", "친절한"]
            ),
            "visual_style_notes": (
                f"{style} style illustration preserving child drawing aesthetics"
            ),
            "sheet_scene_prompts": [
                str(prompt).strip()
                for prompt in sheet_scene_prompts
                if str(prompt).strip()
            ][:3],
            "drawing_analysis": analysis,
        }
        return character_data

    async def create_character_from_text(
        self,
        name: str,
        age: str,
        traits: list[str],
        style: str = "cartoon",
    ) -> dict:
        """
        텍스트 설명에서 캐릭터 생성

        Args:
            name: 캐릭터 이름
            age: 나이 설명 (예: 5살, 30대)
            traits: 성격/특징 리스트
            style: 스타일 (cartoon, watercolor 등)

        Returns:
            캐릭터 생성용 데이터
        """
        if self.llm_provider == "mock":
            return validate_text_character(
                self._mock_text_character(name, age, traits, style)
            ).model_dump()

        prompt = f"""다음 정보로 동화책 캐릭터를 만들어주세요.

이름: {name}
나이: {age}
특징/성격: {", ".join(traits)}
스타일: {style}

JSON 형식으로 응답해주세요:
{{
    "name": {json.dumps(name, ensure_ascii=False)},
    "master_description": "이미지 생성용 상세 외모 설명 (영문, 50단어 이내)",
    "appearance": {{
        "age_visual": "외모 나이 설명",
        "face": "얼굴 특징",
        "hair": "머리 스타일과 색상",
        "skin": "피부톤",
        "body": "체형"
    }},
    "clothing": {{
        "top": "상의",
        "bottom": "하의",
        "shoes": "신발",
        "accessories": "악세서리"
    }},
    "personality_traits": ["성격1", "성격2", "성격3"],
    "visual_style_notes": "스타일 노트",
    "distinctive_features": ["고유 특징1", "고유 특징2"]
}}

주의:
- 나이와 성격에 맞는 외모를 상상해서 구체적으로 묘사
- master_description은 영어로, 나머지는 한국어로
- 동화책에 어울리는 귀엽고 친근한 캐릭터로
- distinctive_features: 안경·주근깨·곱슬머리·점 등 모든 그림에서 동일하게 유지할 식별 특징 2~3개
- 사용자가 토끼·곰 등 동물을 지정하면 그 종·털색·귀·의상을 그대로 유지하고 사람 아이로 바꾸지 마세요.
- 동물의 hair에는 털·귀 주변 모습을 적을 수 있습니다. 없는 머리카락이나 착용하지 않은 의복·신발·액세서리는 빈 값이나 null 대신 문자열 "없음"으로 적으세요.
- appearance와 clothing은 위의 모든 키가 있는 객체이며 각 값은 문자열입니다. accessories도 배열이 아닌 한 문자열입니다.
- 이름은 입력 이름 그대로 1~40자, master_description은 10~400자, visual_style_notes는 1~200자입니다.
- appearance 길이: age_visual 1~40자, face/hair 각각 1~120자, skin/body 각각 1~80자.
- clothing의 top/bottom/shoes/accessories는 각각 1~80자입니다.
- personality_traits는 문자열 배열 1~10개, distinctive_features는 문자열 배열 2~3개(최대 10개)입니다.
- 모든 글자 수는 공백·문장부호를 포함합니다. 지정한 키만 반환하고 긴 설명은 핵심 특징을 남겨 줄이세요.
"""

        # Schema/JSON invalidity is explicitly retryable in the existing error
        # policy. At most three total requests; each retry starts from the same
        # bounded instructions, never echoes an invalid payload or child data.
        for attempt in range(get_retry_count(ErrorCode.LLM_JSON_INVALID) + 1):
            try:
                if self.llm_provider == "openai":
                    data = await self._generate_text_character_openai(prompt)
                elif self.llm_provider == "anthropic":
                    data = await self._generate_text_character_anthropic(prompt)
                elif self.llm_provider == "gemini":
                    data = self._parse_object(await _call_gemini(
                        "Return the requested character as JSON.", prompt, 1500, 0.7,
                    ))
                else:
                    raise LLMError(ErrorCode.UNKNOWN, "Unsupported character provider")
                return validate_text_character(data).model_dump()
            except json.JSONDecodeError:
                logger.warning("Text character JSON invalid", failure_kind="json_invalid")
                error = LLMError(ErrorCode.LLM_JSON_INVALID, "캐릭터 응답 형식이 올바르지 않습니다.")
            except (KeyError, IndexError, TypeError):
                logger.warning("Text character response invalid", failure_kind="response_structure_invalid")
                error = LLMError(ErrorCode.LLM_JSON_INVALID, "캐릭터 응답 형식이 올바르지 않습니다.")
            except LLMError as exc:
                if exc.code != ErrorCode.LLM_JSON_INVALID:
                    raise LLMError(exc.code, "캐릭터 생성 공급자 요청이 실패했습니다.") from None
                error = LLMError(ErrorCode.LLM_JSON_INVALID, "캐릭터 응답 형식이 올바르지 않습니다.")
            except (httpx.TimeoutException, TimeoutError):
                raise LLMError(ErrorCode.LLM_TIMEOUT, "캐릭터 생성 요청 시간이 초과되었습니다.") from None
            except httpx.HTTPError:
                # Authentication, billing, refusal and other HTTP failures do
                # not trigger paid schema retries or expose provider bodies.
                logger.warning("Text character provider request failed", failure_kind="http_error")
                raise LLMError(ErrorCode.UNKNOWN, "캐릭터 생성 공급자 요청이 실패했습니다.") from None
            if attempt >= get_retry_count(ErrorCode.LLM_JSON_INVALID):
                raise error from None
            logger.info("Retrying text character schema", attempt=attempt + 1)
            await asyncio.sleep(get_backoff(ErrorCode.LLM_JSON_INVALID, attempt))

    async def _generate_text_character_openai(self, prompt: str) -> dict:
        """OpenAI로 텍스트 캐릭터 생성"""
        content = await request_openai_json(
            model=settings.llm_model, api_key=self.api_key,
            timeout=settings.llm_timeout, user_prompt=prompt, max_tokens=1000,
        )
        try:
            return self._parse_object(content)
        except json.JSONDecodeError:
            logger.error("OpenAI text character returned invalid JSON")
            raise

    async def _generate_text_character_anthropic(self, prompt: str) -> dict:
        """Anthropic으로 텍스트 캐릭터 생성"""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": 1000,
                    **anthropic_generation_options(settings.llm_model),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()

            content = anthropic_response_text(data)
            try:
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    return self._parse_object(json_match.group())
                return self._parse_object(content)
            except json.JSONDecodeError:
                logger.error("Anthropic text character returned invalid JSON", response_length=len(content))
                raise

    def _mock_text_character(
        self, name: str, age: str, traits: list[str], style: str
    ) -> dict:
        """테스트용 Mock 텍스트 캐릭터"""
        age_visual = age if age else "알 수 없음"
        traits_str = ", ".join(traits) if traits else "friendly"

        return {
            "name": name,
            "master_description": f"cute {style} character, {age_visual} years old appearance, {traits_str}, friendly expression, colorful illustration",
            "appearance": {
                "age_visual": age_visual,
                "face": "밝은 미소와 큰 눈",
                "hair": "정돈된 머리",
                "skin": "밝은 피부",
                "body": "건강한 체형",
            },
            "clothing": {
                "top": "편안한 상의",
                "bottom": "편안한 하의",
                "shoes": "운동화",
                "accessories": "없음",
            },
            "personality_traits": traits
            if traits
            else ["친절한", "용감한", "호기심 많은"],
            "visual_style_notes": f"{style} style illustration",
            "distinctive_features": ["둥근 안경", "주근깨"],
        }


# 싱글톤 인스턴스
photo_character_service = PhotoCharacterService()
