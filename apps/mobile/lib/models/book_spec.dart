/// 책 생성 요청 모델
class BookSpec {
  final String topic;
  final String language;
  final String targetAge;
  final String style;
  final int pageCount;
  final String? theme;
  final String? protagonistName;
  final String? characterId; // 단일 캐릭터 (기존 호환)
  final List<String>? characterIds; // 다중 캐릭터 (가족 등)
  final String? characterRelationship; // 다중 캐릭터 간 관계 (남매/친구 등)
  final List<String>? forbiddenElements;

  BookSpec({
    required this.topic,
    this.language = 'ko',
    required this.targetAge,
    required this.style,
    this.pageCount = 8,
    this.theme,
    this.protagonistName,
    this.characterId,
    this.characterIds,
    this.characterRelationship,
    this.forbiddenElements,
  });

  Map<String, dynamic> toJson() => {
        'topic': topic,
        'language': language,
        'target_age': targetAge,
        'style': style,
        'page_count': pageCount,
        if (theme != null) 'theme': theme,
        if (protagonistName != null) 'protagonist_name': protagonistName,
        if (characterId != null) 'character_id': characterId,
        if (characterIds != null && characterIds!.isNotEmpty)
          'character_ids': characterIds,
        if (characterRelationship != null && characterRelationship!.isNotEmpty)
          'character_relationship': characterRelationship,
        if (forbiddenElements != null) 'forbidden_elements': forbiddenElements,
      };
}

/// 연령대 옵션
enum TargetAge {
  age3to5('3-5', '3-5세'),
  age5to7('5-7', '5-7세'),
  age7to9('7-9', '7-9세'),
  adult('adult', '성인');

  final String value;
  final String label;
  const TargetAge(this.value, this.label);
}

/// 그림 스타일 옵션
enum BookStyle {
  watercolor('watercolor', '수채화'),
  cartoon('cartoon', '카툰'),
  threeD('3d', '3D'),
  pixel('pixel', '픽셀아트'),
  oilPainting('oil_painting', '유화'),
  claymation('claymation', '클레이'),
  realistic('realistic', '실사');

  final String value;
  final String label;
  const BookStyle(this.value, this.label);
}

/// 테마 옵션
enum BookTheme {
  lunarNewYear('설날', '설날'),
  chuseok('추석', '추석'),
  childrensDay('어린이날', '어린이날'),
  christmas('크리스마스', '크리스마스'),
  lifestyle('생활습관', '생활습관'),
  emotionalCoaching('감정코칭', '감정코칭'),
  social('사회성', '사회성'),
  friendship('우정', '우정'),
  family('가족', '가족'),
  adventure('모험', '모험'),
  nature('자연', '자연'),
  science('과학', '과학'),
  timeTravel('시간여행', '시간여행'),
  animal('동물', '동물'),
  dinosaur('공룡', '공룡'),
  occupation('직업', '직업'),
  fictionWorld('작품속으로', '작품 속으로');

  final String value;
  final String label;
  const BookTheme(this.value, this.label);
}
