/// 책 생성 요청 모델
class BookSpec {
  final String topic;
  final String language;
  final String targetAge;
  final String style;
  final int pageCount;
  final String? theme;
  final String? characterId;
  final List<String>? forbiddenElements;

  BookSpec({
    required this.topic,
    this.language = 'ko',
    required this.targetAge,
    required this.style,
    this.pageCount = 8,
    this.theme,
    this.characterId,
    this.forbiddenElements,
  });

  Map<String, dynamic> toJson() => {
        'topic': topic,
        'language': language,
        'target_age': targetAge,
        'style': style,
        'page_count': pageCount,
        if (theme != null) 'theme': theme,
        if (characterId != null) 'character_id': characterId,
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
  claymation('claymation', '클레이');

  final String value;
  final String label;
  const BookStyle(this.value, this.label);
}

/// 테마 옵션
enum BookTheme {
  emotionalCoaching('감정코칭', '감정코칭'),
  friendship('우정', '우정'),
  family('가족', '가족'),
  adventure('모험', '모험'),
  nature('자연', '자연'),
  science('과학', '과학');

  final String value;
  final String label;
  const BookTheme(this.value, this.label);
}
