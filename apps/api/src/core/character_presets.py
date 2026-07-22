"""기본 제공 캐릭터 프리셋 — '기본 이미지 선택' 경로용 외형 텍스트 카탈로그.

설정된 이미지 프로바이더(DALL-E 3)가 image-to-image/reference를 지원하지 않으므로,
픽셀 reference가 아닌 **외형 텍스트 묘사**로 주인공을 모든 페이지에 일관 반영한다.
사진 업로드(POST /v1/characters/from-photo)의 대안 경로다.

각 프리셋은 CreateCharacterRequest 와 동일한 필드 형태(master_description/appearance/
clothing/personality_traits/visual_style_notes)를 가져 POST /from-preset 에서 그대로 캐릭터로 저장된다.
thumbnail_asset 은 모바일 번들 asset 경로(assets/images/presets/*.png).

**언어 정책(G31 / M27·M28 불변식)**:
- `master_description` 은 이미지 프롬프트·캐릭터 일관성 목적이라 **항상 영어(이미지 최적)** 로 고정한다.
  (photo_character / 캐릭터 시트와 동일 불변식 — 이미지 프롬프트 언어=영어.)
- `name` 및 표시용 외형 텍스트(appearance/clothing/visual_style_notes)만 **로케일별로 서빙**한다.
  CHARACTER_PRESETS 원본은 기본 언어(ko) 표시 텍스트이며, en/ja/zh/es 변형은 PRESET_LOCALIZED 에 둔다.
- `preset_id`/`thumbnail_asset`/`personality_traits` 는 비텍스트 식별자로 로케일 무관하게 유지한다.

로케일 서빙은 get_preset_localized(preset_id, language) 를 통해 이루어진다(미지원 언어는 ko 폴백).
"""

from typing import Optional

from src.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

CHARACTER_PRESETS = [
    {
        "preset_id": "bright_girl",
        "name": "햇살이",
        "thumbnail_asset": "assets/images/presets/bright_girl.png",
        "master_description": (
            "A curious, cheerful 6-year-old girl with a round face, big brown eyes, "
            "a short bob haircut, and a bright beaming smile. Warm watercolor "
            "storybook heroine."
        ),
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
        "master_description": (
            "A brave, kind-hearted 7-year-old boy with short black hair, playful eyes, "
            "and a curious expression. Warm watercolor storybook hero."
        ),
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
        "master_description": (
            "An imaginative 5-year-old child with curly hair, round glasses, and a "
            "gentle, thoughtful gaze. Warm watercolor storybook character."
        ),
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
        "master_description": (
            "A warm-hearted 7-year-old girl with long braided hair, kind eyes, and a "
            "caring smile who loves helping friends. Warm watercolor storybook heroine."
        ),
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
        "master_description": (
            "A playful yet warm-hearted 6-year-old boy with tousled brown hair, "
            "freckles, and a mischievous grin. Warm watercolor storybook hero."
        ),
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
        "master_description": (
            "A quiet, thoughtful 8-year-old child with calm eyes and neat hair who "
            "loves books and stars. Warm watercolor storybook character."
        ),
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

# 표시용 로케일 변형(name/appearance/clothing/visual_style_notes).
# 기본 언어(ko)는 CHARACTER_PRESETS 원본을 사용하므로 여기엔 en/ja/zh/es 만 둔다.
# master_description(영어)·preset_id·personality_traits·thumbnail_asset 은 로케일 무관.
PRESET_LOCALIZED = {
    "bright_girl": {
        "en": {
            "name": "Sunny",
            "appearance": {
                "age_visual": "6-year-old girl",
                "face": "round face, big sparkling brown eyes, rosy cheeks",
                "hair": "dark brown bob with light bangs",
                "skin": "warm apricot skin",
                "body": "small, chubby child build",
            },
            "clothing": {
                "top": "yellow pinafore dress",
                "bottom": "white shorts",
                "shoes": "red sneakers",
                "accessories": "yellow hairpin",
            },
            "visual_style_notes": "soft watercolor style, warm pastel palette",
        },
        "ja": {
            "name": "ひなた",
            "appearance": {
                "age_visual": "6歳の女の子",
                "face": "丸い顔、大きく輝く茶色の瞳、赤らんだ頬",
                "hair": "濃い茶色のボブ、軽い前髪",
                "skin": "温かみのあるアプリコット色の肌",
                "body": "小柄でふっくらした子ども体型",
            },
            "clothing": {
                "top": "黄色いサロペットワンピース",
                "bottom": "白いショートパンツ",
                "shoes": "赤いスニーカー",
                "accessories": "黄色いヘアピン",
            },
            "visual_style_notes": "やわらかな水彩風、温かいパステルカラー",
        },
        "zh": {
            "name": "阳阳",
            "appearance": {
                "age_visual": "6岁女孩",
                "face": "圆脸，明亮的大棕色眼睛，红润的脸颊",
                "hair": "深棕色波波头，微微刘海",
                "skin": "温暖的杏色肌肤",
                "body": "娇小圆润的儿童体型",
            },
            "clothing": {
                "top": "黄色背带连衣裙",
                "bottom": "白色短裤",
                "shoes": "红色运动鞋",
                "accessories": "黄色发夹",
            },
            "visual_style_notes": "柔和的水彩风格，温暖的粉彩色调",
        },
        "es": {
            "name": "Solecita",
            "appearance": {
                "age_visual": "niña de 6 años",
                "face": "cara redonda, grandes ojos castaños brillantes, mejillas sonrosadas",
                "hair": "melena corta castaña oscura con flequillo ligero",
                "skin": "piel cálida color albaricoque",
                "body": "cuerpo infantil pequeño y rellenito",
            },
            "clothing": {
                "top": "vestido peto amarillo",
                "bottom": "pantalón corto blanco",
                "shoes": "zapatillas rojas",
                "accessories": "horquilla amarilla",
            },
            "visual_style_notes": "estilo acuarela suave, paleta pastel cálida",
        },
    },
    "brave_boy": {
        "en": {
            "name": "Max",
            "appearance": {
                "age_visual": "7-year-old boy",
                "face": "softly angular face, playful dark eyes, bright smile",
                "hair": "short, tidy black hair",
                "skin": "healthy tan skin",
                "body": "active, sturdy child build",
            },
            "clothing": {
                "top": "blue striped t-shirt",
                "bottom": "navy shorts",
                "shoes": "blue sneakers",
                "accessories": "small backpack",
            },
            "visual_style_notes": "soft watercolor style, vivid palette",
        },
        "ja": {
            "name": "げんき",
            "appearance": {
                "age_visual": "7歳の男の子",
                "face": "少し角ばった柔らかな顔、いたずらっぽい黒い瞳、明るい笑顔",
                "hair": "短くきちんとした黒髪",
                "skin": "健康的な小麦色の肌",
                "body": "活発でがっしりした子ども体型",
            },
            "clothing": {
                "top": "青いボーダーのTシャツ",
                "bottom": "紺色のショートパンツ",
                "shoes": "青いスニーカー",
                "accessories": "小さなリュック",
            },
            "visual_style_notes": "やわらかな水彩風、生き生きとした色合い",
        },
        "zh": {
            "name": "壮壮",
            "appearance": {
                "age_visual": "7岁男孩",
                "face": "略带棱角的柔和脸庞，调皮的黑眼睛，灿烂的微笑",
                "hair": "短而整齐的黑发",
                "skin": "健康的小麦色肌肤",
                "body": "活泼结实的儿童体型",
            },
            "clothing": {
                "top": "蓝色条纹T恤",
                "bottom": "藏青色短裤",
                "shoes": "蓝色运动鞋",
                "accessories": "小背包",
            },
            "visual_style_notes": "柔和的水彩风格，生动的色彩",
        },
        "es": {
            "name": "Valentín",
            "appearance": {
                "age_visual": "niño de 7 años",
                "face": "rostro suavemente anguloso, ojos oscuros traviesos, sonrisa radiante",
                "hair": "cabello negro corto y ordenado",
                "skin": "piel morena saludable",
                "body": "cuerpo infantil activo y robusto",
            },
            "clothing": {
                "top": "camiseta de rayas azules",
                "bottom": "pantalón corto azul marino",
                "shoes": "zapatillas azules",
                "accessories": "mochila pequeña",
            },
            "visual_style_notes": "estilo acuarela suave, paleta viva",
        },
    },
    "curious_kid": {
        "en": {
            "name": "Star",
            "appearance": {
                "age_visual": "5-year-old child",
                "face": "round face, big curious eyes, round glasses",
                "hair": "dark brown curly hair",
                "skin": "light apricot skin",
                "body": "small, petite child build",
            },
            "clothing": {
                "top": "green hoodie",
                "bottom": "beige overalls",
                "shoes": "brown boots",
                "accessories": "round glasses",
            },
            "visual_style_notes": "soft watercolor style, cozy palette",
        },
        "ja": {
            "name": "ほし",
            "appearance": {
                "age_visual": "5歳の子ども",
                "face": "丸い顔、好奇心いっぱいの大きな瞳、丸い眼鏡",
                "hair": "濃い茶色の巻き毛",
                "skin": "明るいアプリコット色の肌",
                "body": "小柄でこぢんまりした子ども体型",
            },
            "clothing": {
                "top": "緑のパーカー",
                "bottom": "ベージュのサロペット",
                "shoes": "茶色のブーツ",
                "accessories": "丸い眼鏡",
            },
            "visual_style_notes": "やわらかな水彩風、ほのぼのとした色合い",
        },
        "zh": {
            "name": "星星",
            "appearance": {
                "age_visual": "5岁孩子",
                "face": "圆脸，充满好奇的大眼睛，圆框眼镜",
                "hair": "深棕色卷发",
                "skin": "明亮的杏色肌肤",
                "body": "娇小玲珑的儿童体型",
            },
            "clothing": {
                "top": "绿色连帽衫",
                "bottom": "米色背带裤",
                "shoes": "棕色靴子",
                "accessories": "圆框眼镜",
            },
            "visual_style_notes": "柔和的水彩风格，温馨的色调",
        },
        "es": {
            "name": "Estrella",
            "appearance": {
                "age_visual": "niño de 5 años",
                "face": "cara redonda, grandes ojos curiosos, gafas redondas",
                "hair": "cabello castaño oscuro rizado",
                "skin": "piel clara color albaricoque",
                "body": "cuerpo infantil pequeño y menudo",
            },
            "clothing": {
                "top": "sudadera verde con capucha",
                "bottom": "peto beige",
                "shoes": "botas marrones",
                "accessories": "gafas redondas",
            },
            "visual_style_notes": "estilo acuarela suave, paleta acogedora",
        },
    },
    "gentle_girl": {
        "en": {
            "name": "Grace",
            "appearance": {
                "age_visual": "7-year-old girl",
                "face": "oval face, kind eyes, gentle smile",
                "hair": "long black hair in two braids",
                "skin": "clear apricot skin",
                "body": "slim child build",
            },
            "clothing": {
                "top": "pink cardigan",
                "bottom": "floral skirt",
                "shoes": "white shoes",
                "accessories": "pink ribbon",
            },
            "visual_style_notes": "soft watercolor style, warm pastel palette",
        },
        "ja": {
            "name": "めぐみ",
            "appearance": {
                "age_visual": "7歳の女の子",
                "face": "細面の顔、優しい瞳、柔らかな笑顔",
                "hair": "長い黒髪を左右の三つ編みに",
                "skin": "澄んだアプリコット色の肌",
                "body": "すらりとした子ども体型",
            },
            "clothing": {
                "top": "ピンクのカーディガン",
                "bottom": "花柄のスカート",
                "shoes": "白い靴",
                "accessories": "ピンクのリボン",
            },
            "visual_style_notes": "やわらかな水彩風、温かいパステルカラー",
        },
        "zh": {
            "name": "暖暖",
            "appearance": {
                "age_visual": "7岁女孩",
                "face": "鹅蛋脸，温柔的眼睛，柔和的微笑",
                "hair": "黑色长发梳成两条辫子",
                "skin": "清透的杏色肌肤",
                "body": "纤细的儿童体型",
            },
            "clothing": {
                "top": "粉色开衫",
                "bottom": "碎花裙",
                "shoes": "白色皮鞋",
                "accessories": "粉色蝴蝶结",
            },
            "visual_style_notes": "柔和的水彩风格，温暖的粉彩色调",
        },
        "es": {
            "name": "Dulce",
            "appearance": {
                "age_visual": "niña de 7 años",
                "face": "cara ovalada, ojos amables, sonrisa suave",
                "hair": "cabello negro largo en dos trenzas",
                "skin": "piel clara color albaricoque",
                "body": "cuerpo infantil esbelto",
            },
            "clothing": {
                "top": "chaqueta rosa de punto",
                "bottom": "falda de flores",
                "shoes": "zapatos blancos",
                "accessories": "lazo rosa",
            },
            "visual_style_notes": "estilo acuarela suave, paleta pastel cálida",
        },
    },
    "playful_boy": {
        "en": {
            "name": "Milo",
            "appearance": {
                "age_visual": "6-year-old boy",
                "face": "round face, mischievous eyes, freckles, wide grin",
                "hair": "tousled light brown hair",
                "skin": "healthy sun-kissed skin",
                "body": "lively child build",
            },
            "clothing": {
                "top": "orange t-shirt",
                "bottom": "denim shorts",
                "shoes": "green sneakers",
                "accessories": "baseball cap",
            },
            "visual_style_notes": "soft watercolor style, bright and lively palette",
        },
        "ja": {
            "name": "げんた",
            "appearance": {
                "age_visual": "6歳の男の子",
                "face": "丸い顔、いたずらっぽい瞳、そばかす、満面の笑み",
                "hair": "くしゃっとした明るい茶色の髪",
                "skin": "日焼けした健康的な肌",
                "body": "活発な子ども体型",
            },
            "clothing": {
                "top": "オレンジのTシャツ",
                "bottom": "デニムのショートパンツ",
                "shoes": "緑のスニーカー",
                "accessories": "野球帽",
            },
            "visual_style_notes": "やわらかな水彩風、明るく軽やかな色合い",
        },
        "zh": {
            "name": "皮皮",
            "appearance": {
                "age_visual": "6岁男孩",
                "face": "圆脸，调皮的眼睛，雀斑，咧嘴大笑",
                "hair": "蓬松的浅棕色头发",
                "skin": "阳光晒过的健康肌肤",
                "body": "活泼的儿童体型",
            },
            "clothing": {
                "top": "橙色T恤",
                "bottom": "牛仔短裤",
                "shoes": "绿色运动鞋",
                "accessories": "棒球帽",
            },
            "visual_style_notes": "柔和的水彩风格，明亮轻快的色彩",
        },
        "es": {
            "name": "Pícaro",
            "appearance": {
                "age_visual": "niño de 6 años",
                "face": "cara redonda, ojos traviesos, pecas, amplia sonrisa",
                "hair": "cabello castaño claro despeinado",
                "skin": "piel saludable bronceada por el sol",
                "body": "cuerpo infantil enérgico",
            },
            "clothing": {
                "top": "camiseta naranja",
                "bottom": "pantalón corto vaquero",
                "shoes": "zapatillas verdes",
                "accessories": "gorra de béisbol",
            },
            "visual_style_notes": "estilo acuarela suave, paleta luminosa y alegre",
        },
    },
    "dreamy_kid": {
        "en": {
            "name": "Sky",
            "appearance": {
                "age_visual": "8-year-old child",
                "face": "oval face, calm deep eyes, faint smile",
                "hair": "neat black bob",
                "skin": "clear fair skin",
                "body": "child build, a little taller than peers",
            },
            "clothing": {
                "top": "navy sweater",
                "bottom": "gray trousers",
                "shoes": "navy sneakers",
                "accessories": "small star necklace",
            },
            "visual_style_notes": "soft watercolor style, calm and gentle palette",
        },
        "ja": {
            "name": "ゆめ",
            "appearance": {
                "age_visual": "8歳の子ども",
                "face": "細面の顔、落ち着いた深い瞳、淡い微笑み",
                "hair": "きちんとした黒のボブ",
                "skin": "澄んだ白い肌",
                "body": "同年代より少し背の高い子ども体型",
            },
            "clothing": {
                "top": "紺色のセーター",
                "bottom": "グレーのズボン",
                "shoes": "紺色のスニーカー",
                "accessories": "小さな星のネックレス",
            },
            "visual_style_notes": "やわらかな水彩風、穏やかな色合い",
        },
        "zh": {
            "name": "梦梦",
            "appearance": {
                "age_visual": "8岁孩子",
                "face": "鹅蛋脸，沉静深邃的眼睛，浅浅的微笑",
                "hair": "整齐的黑色短发",
                "skin": "清透白皙的肌肤",
                "body": "比同龄人略高的儿童体型",
            },
            "clothing": {
                "top": "藏青色毛衣",
                "bottom": "灰色长裤",
                "shoes": "藏青色运动鞋",
                "accessories": "小小的星星项链",
            },
            "visual_style_notes": "柔和的水彩风格，宁静的色调",
        },
        "es": {
            "name": "Sueñito",
            "appearance": {
                "age_visual": "niño de 8 años",
                "face": "cara ovalada, ojos serenos y profundos, leve sonrisa",
                "hair": "melena negra corta y ordenada",
                "skin": "piel clara y luminosa",
                "body": "cuerpo infantil algo más alto que sus compañeros",
            },
            "clothing": {
                "top": "suéter azul marino",
                "bottom": "pantalón gris",
                "shoes": "zapatillas azul marino",
                "accessories": "collar con una pequeña estrella",
            },
            "visual_style_notes": "estilo acuarela suave, paleta serena",
        },
    },
}

_BY_ID = {preset["preset_id"]: preset for preset in CHARACTER_PRESETS}


def get_preset(preset_id: str):
    """preset_id 로 프리셋(기본 언어 ko 표시 + 영어 master_description) 조회(없으면 None)."""
    return _BY_ID.get(preset_id)


def get_preset_localized(
    preset_id: str, language: Optional[str] = None
) -> Optional[dict]:
    """요청 언어의 표시 텍스트로 프리셋을 반환한다(없으면 None).

    - name/appearance/clothing/visual_style_notes 는 요청 언어 변형(미지원 언어는
      i18n.DEFAULT_LANGUAGE=ko 로 폴백).
    - master_description 은 언어 무관하게 항상 영어(이미지 최적, G31 불변식).
    - preset_id/thumbnail_asset/personality_traits 는 로케일 무관하게 원본 유지.
    """
    base = _BY_ID.get(preset_id)
    if base is None:
        return None

    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    result = dict(base)
    # ko 는 CHARACTER_PRESETS 원본이 곧 표시 텍스트이므로 변형이 없다.
    variant = PRESET_LOCALIZED.get(preset_id, {}).get(lang)
    if variant is not None:
        result["name"] = variant["name"]
        result["appearance"] = variant["appearance"]
        result["clothing"] = variant["clothing"]
        result["visual_style_notes"] = variant["visual_style_notes"]
    # master_description 은 base(영어) 그대로, personality_traits/thumbnail_asset 유지.
    return result
