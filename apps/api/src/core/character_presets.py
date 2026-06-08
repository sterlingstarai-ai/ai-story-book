"""기본 제공 캐릭터 프리셋 — '기본 이미지 선택' 경로용 외형 텍스트 카탈로그.

설정된 이미지 프로바이더(DALL-E 3)가 image-to-image/reference를 지원하지 않으므로,
픽셀 reference가 아닌 **외형 텍스트 묘사**로 주인공을 모든 페이지에 일관 반영한다.
사진 업로드(POST /v1/characters/from-photo)의 대안 경로다.

각 프리셋은 CreateCharacterRequest 와 동일한 필드 형태(master_description/appearance/
clothing/personality_traits/visual_style_notes)를 가져 POST /from-preset 에서 그대로 캐릭터로 저장된다.
thumbnail_asset 은 모바일 번들 asset 경로(assets/images/presets/*.png).
"""

CHARACTER_PRESETS = [
    {
        "preset_id": "bright_girl",
        "name": "햇살이",
        "thumbnail_asset": "assets/images/presets/bright_girl.png",
        "master_description": "호기심 많고 밝은 6세 여자아이. 동그란 얼굴에 큰 갈색 눈, 단발머리, 활짝 웃는 표정이 특징인 따뜻한 수채화풍 주인공.",
        "appearance": {
            "age_visual": "6세 여자아이",
            "face": "동그란 얼굴, 크고 반짝이는 갈색 눈, 볼이 발그레함",
            "hair": "짙은 갈색 단발머리, 앞머리가 살짝 있음",
            "skin": "따뜻한 살구빛 피부",
            "body": "작고 통통한 어린이 체형",
        },
        "clothing": {
            "top": "노란 멜빵 원피스",
            "bottom": "흰색 반바지",
            "shoes": "빨간 운동화",
            "accessories": "노란 머리핀",
        },
        "personality_traits": ["밝음", "호기심", "용기"],
        "visual_style_notes": "부드러운 수채화풍, 따뜻한 파스텔 색감",
    },
    {
        "preset_id": "brave_boy",
        "name": "씩씩이",
        "thumbnail_asset": "assets/images/presets/brave_boy.png",
        "master_description": "씩씩하고 다정한 7세 남자아이. 짧은 검은 머리에 장난기 있는 눈, 호기심 가득한 표정의 그림책 주인공.",
        "appearance": {
            "age_visual": "7세 남자아이",
            "face": "각진 듯 부드러운 얼굴, 장난기 있는 검은 눈, 환한 미소",
            "hair": "짧고 단정한 검은 머리",
            "skin": "건강한 갈색빛 피부",
            "body": "활동적이고 다부진 어린이 체형",
        },
        "clothing": {
            "top": "파란 줄무늬 티셔츠",
            "bottom": "남색 반바지",
            "shoes": "파란 운동화",
            "accessories": "작은 백팩",
        },
        "personality_traits": ["씩씩함", "다정함", "모험심"],
        "visual_style_notes": "부드러운 수채화풍, 생기있는 색감",
    },
    {
        "preset_id": "curious_kid",
        "name": "별이",
        "thumbnail_asset": "assets/images/presets/curious_kid.png",
        "master_description": "상상력이 풍부한 5세 아이. 곱슬머리에 동그란 안경, 늘 무언가를 골똘히 바라보는 다정한 그림책 주인공.",
        "appearance": {
            "age_visual": "5세 어린이",
            "face": "동그란 얼굴, 호기심 어린 큰 눈, 동그란 안경",
            "hair": "짙은 갈색 곱슬머리",
            "skin": "밝은 살구빛 피부",
            "body": "작고 아담한 어린이 체형",
        },
        "clothing": {
            "top": "초록 후드티",
            "bottom": "베이지 멜빵바지",
            "shoes": "갈색 부츠",
            "accessories": "동그란 안경",
        },
        "personality_traits": ["상상력", "호기심", "차분함"],
        "visual_style_notes": "부드러운 수채화풍, 포근한 색감",
    },
    {
        "preset_id": "gentle_girl",
        "name": "다정이",
        "thumbnail_asset": "assets/images/presets/gentle_girl.png",
        "master_description": "마음이 따뜻한 7세 여자아이. 길게 땋은 머리에 다정한 눈빛, 친구를 잘 돕는 그림책 주인공.",
        "appearance": {
            "age_visual": "7세 여자아이",
            "face": "갸름한 얼굴, 다정한 눈, 부드러운 미소",
            "hair": "길게 양갈래로 땋은 검은 머리",
            "skin": "맑은 살구빛 피부",
            "body": "날씬한 어린이 체형",
        },
        "clothing": {
            "top": "분홍 카디건",
            "bottom": "꽃무늬 치마",
            "shoes": "흰 구두",
            "accessories": "분홍 리본",
        },
        "personality_traits": ["다정함", "배려", "성실함"],
        "visual_style_notes": "부드러운 수채화풍, 따뜻한 파스텔 색감",
    },
    {
        "preset_id": "playful_boy",
        "name": "장난이",
        "thumbnail_asset": "assets/images/presets/playful_boy.png",
        "master_description": "장난기 가득하지만 마음 따뜻한 6세 남자아이. 부스스한 갈색 머리에 개구진 미소를 가진 그림책 주인공.",
        "appearance": {
            "age_visual": "6세 남자아이",
            "face": "둥근 얼굴, 개구진 눈, 주근깨, 활짝 웃는 입",
            "hair": "부스스한 밝은 갈색 머리",
            "skin": "햇볕에 그을린 건강한 피부",
            "body": "활발한 어린이 체형",
        },
        "clothing": {
            "top": "주황 티셔츠",
            "bottom": "청 반바지",
            "shoes": "초록 운동화",
            "accessories": "야구 모자",
        },
        "personality_traits": ["장난기", "활발함", "따뜻함"],
        "visual_style_notes": "부드러운 수채화풍, 밝고 경쾌한 색감",
    },
    {
        "preset_id": "dreamy_kid",
        "name": "꿈이",
        "thumbnail_asset": "assets/images/presets/dreamy_kid.png",
        "master_description": "조용하고 사려 깊은 8세 아이. 차분한 눈빛과 단정한 머리, 책과 별을 좋아하는 그림책 주인공.",
        "appearance": {
            "age_visual": "8세 어린이",
            "face": "갸름한 얼굴, 차분하고 깊은 눈, 옅은 미소",
            "hair": "단정한 검은 단발",
            "skin": "맑고 하얀 피부",
            "body": "또래보다 조금 큰 어린이 체형",
        },
        "clothing": {
            "top": "남색 스웨터",
            "bottom": "회색 바지",
            "shoes": "남색 운동화",
            "accessories": "작은 별 목걸이",
        },
        "personality_traits": ["사려깊음", "상상력", "차분함"],
        "visual_style_notes": "부드러운 수채화풍, 잔잔한 색감",
    },
]

_BY_ID = {preset["preset_id"]: preset for preset in CHARACTER_PRESETS}


def get_preset(preset_id: str):
    """preset_id 로 프리셋 조회(없으면 None)."""
    return _BY_ID.get(preset_id)
