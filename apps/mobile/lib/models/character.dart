import 'json_parsing.dart';

/// 캐릭터 시트 모델
class Character {
  final String id;
  final String name;
  final String masterDescription;
  final Appearance appearance;
  final Clothing clothing;
  final List<String> personalityTraits;
  final String? visualStyleNotes;

  /// 식별 가능한 고유 특징(안경/주근깨 등) — 같은 캐릭터를 일관되게 유지
  final List<String>? distinctiveFeatures;
  final DateTime createdAt;

  Character({
    required this.id,
    required this.name,
    required this.masterDescription,
    required this.appearance,
    required this.clothing,
    required this.personalityTraits,
    this.visualStyleNotes,
    this.distinctiveFeatures,
    required this.createdAt,
  });

  factory Character.fromJson(Map<String, dynamic> json) {
    final personalityTraits = JsonParsing.asList(
      json['personality_traits'],
      field: 'personality_traits',
    )
        .map((trait) =>
            JsonParsing.asRequiredString(trait, field: 'personality_traits[]'))
        .toList();

    return Character(
      id: JsonParsing.asRequiredString(
        json['character_id'] ?? json['id'],
        field: 'character_id',
      ),
      name: JsonParsing.asRequiredString(json['name'], field: 'name'),
      masterDescription: JsonParsing.asRequiredString(
        json['master_description'],
        field: 'master_description',
      ),
      appearance: Appearance.fromJson(
        JsonParsing.asMap(json['appearance'], field: 'appearance'),
      ),
      clothing: Clothing.fromJson(
        JsonParsing.asMap(json['clothing'], field: 'clothing'),
      ),
      personalityTraits: personalityTraits,
      visualStyleNotes:
          JsonParsing.asOptionalString(json['visual_style_notes']),
      distinctiveFeatures: json['distinctive_features'] is List
          ? (json['distinctive_features'] as List).whereType<String>().toList()
          : null,
      createdAt: JsonParsing.asRequiredDateTime(json['created_at'],
          field: 'created_at'),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'master_description': masterDescription,
        'appearance': appearance.toJson(),
        'clothing': clothing.toJson(),
        'personality_traits': personalityTraits,
        if (visualStyleNotes != null) 'visual_style_notes': visualStyleNotes,
        if (distinctiveFeatures != null && distinctiveFeatures!.isNotEmpty)
          'distinctive_features': distinctiveFeatures,
      };
}

/// 캐릭터 외형
class Appearance {
  final String ageVisual;
  final String face;
  final String hair;
  final String skin;
  final String body;

  Appearance({
    required this.ageVisual,
    required this.face,
    required this.hair,
    required this.skin,
    required this.body,
  });

  factory Appearance.fromJson(Map<String, dynamic> json) {
    return Appearance(
      ageVisual:
          JsonParsing.asRequiredString(json['age_visual'], field: 'age_visual'),
      face: JsonParsing.asRequiredString(json['face'], field: 'face'),
      hair: JsonParsing.asRequiredString(json['hair'], field: 'hair'),
      skin: JsonParsing.asRequiredString(json['skin'], field: 'skin'),
      body: JsonParsing.asRequiredString(json['body'], field: 'body'),
    );
  }

  Map<String, dynamic> toJson() => {
        'age_visual': ageVisual,
        'face': face,
        'hair': hair,
        'skin': skin,
        'body': body,
      };
}

/// 캐릭터 의상
class Clothing {
  final String top;
  final String bottom;
  final String shoes;
  final String accessories;

  Clothing({
    required this.top,
    required this.bottom,
    required this.shoes,
    required this.accessories,
  });

  factory Clothing.fromJson(Map<String, dynamic> json) {
    return Clothing(
      top: JsonParsing.asRequiredString(json['top'], field: 'top'),
      bottom: JsonParsing.asRequiredString(json['bottom'], field: 'bottom'),
      shoes: JsonParsing.asRequiredString(json['shoes'], field: 'shoes'),
      accessories: JsonParsing.asRequiredString(json['accessories'],
          field: 'accessories'),
    );
  }

  Map<String, dynamic> toJson() => {
        'top': top,
        'bottom': bottom,
        'shoes': shoes,
        'accessories': accessories,
      };
}

/// 캐릭터 생성 요청
class CharacterCreate {
  final String name;
  final String masterDescription;
  final Appearance appearance;
  final Clothing clothing;
  final List<String> personalityTraits;
  final String? visualStyleNotes;

  CharacterCreate({
    required this.name,
    required this.masterDescription,
    required this.appearance,
    required this.clothing,
    required this.personalityTraits,
    this.visualStyleNotes,
  });

  Map<String, dynamic> toJson() => {
        'name': name,
        'master_description': masterDescription,
        'appearance': appearance.toJson(),
        'clothing': clothing.toJson(),
        'personality_traits': personalityTraits,
        if (visualStyleNotes != null) 'visual_style_notes': visualStyleNotes,
      };
}
