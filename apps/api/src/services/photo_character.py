"""
Photo-based Character Service
사진에서 캐릭터 생성
"""

import base64
import httpx
from typing import Optional
import os


class PhotoCharacterService:
    """사진 기반 캐릭터 생성 서비스"""

    def __init__(self):
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
        self.api_key = os.getenv("LLM_API_KEY")

    async def analyze_photo(self, image_data: bytes) -> dict:
        """
        사진 분석하여 캐릭터 특성 추출

        Args:
            image_data: 이미지 바이트 데이터

        Returns:
            분석된 특성 딕셔너리
        """
        # Base64 인코딩
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        if self.llm_provider == "openai":
            return await self._analyze_with_openai(image_base64)
        elif self.llm_provider == "anthropic":
            return await self._analyze_with_anthropic(image_base64)
        else:
            # Mock response for testing
            return self._mock_analysis()

    async def _analyze_with_openai(self, image_base64: str) -> dict:
        """OpenAI Vision API로 분석"""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": self._get_analysis_prompt(),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_base64}",
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()

            import json

            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

    async def _analyze_with_anthropic(self, image_base64: str) -> dict:
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
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1000,
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
                                    "text": self._get_analysis_prompt(),
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()

            import json

            content = data["content"][0]["text"]
            # JSON 추출
            import re

            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(content)

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
- visual_description은 영어로 작성
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
            return self._mock_text_character(name, age, traits, style)

        prompt = f"""다음 정보로 동화책 캐릭터를 만들어주세요.

이름: {name}
나이: {age}
특징/성격: {', '.join(traits)}
스타일: {style}

JSON 형식으로 응답해주세요:
{{
    "name": "{name}",
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
    "visual_style_notes": "스타일 노트"
}}

주의:
- 나이와 성격에 맞는 외모를 상상해서 구체적으로 묘사
- master_description은 영어로, 나머지는 한국어로
- 동화책에 어울리는 귀엽고 친근한 캐릭터로
"""

        try:
            if self.llm_provider == "openai":
                return await self._generate_text_character_openai(prompt)
            elif self.llm_provider == "anthropic":
                return await self._generate_text_character_anthropic(prompt)
            else:
                return self._mock_text_character(name, age, traits, style)
        except Exception:
            return self._mock_text_character(name, age, traits, style)

    async def _generate_text_character_openai(self, prompt: str) -> dict:
        """OpenAI로 텍스트 캐릭터 생성"""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()

            import json
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

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
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()

            import json
            import re
            content = data["content"][0]["text"]
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(content)

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
            "personality_traits": traits if traits else ["친절한", "용감한", "호기심 많은"],
            "visual_style_notes": f"{style} style illustration",
        }


# 싱글톤 인스턴스
photo_character_service = PhotoCharacterService()
