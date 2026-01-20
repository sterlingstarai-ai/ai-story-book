/// 캐릭터 시트 모델
class Character {
  final String id;
  final String name;
  final String masterDescription;
  final Appearance appearance;
  final Clothing clothing;
  final List<String> personalityTraits;
  final String? visualStyleNotes;
  final DateTime createdAt;

  Character({
    required this.id,
    required this.name,
    required this.masterDescription,
    required this.appearance,
    required this.clothing,
    required this.personalityTraits,
    this.visualStyleNotes,
    required this.createdAt,
  });

  factory Character.fromJson(Map<String, dynamic> json) {
    return Character(
      id: json['id'] as String,
      name: json['name'] as String,
      masterDescription: json['master_description'] as String,
      appearance: Appearance.fromJson(json['appearance'] as Map<String, dynamic>),
      clothing: Clothing.fromJson(json['clothing'] as Map<String, dynamic>),
      personalityTraits: (json['personality_traits'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      visualStyleNotes: json['visual_style_notes'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
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
      ageVisual: json['age_visual'] as String,
      face: json['face'] as String,
      hair: json['hair'] as String,
      skin: json['skin'] as String,
      body: json['body'] as String,
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
      top: json['top'] as String,
      bottom: json['bottom'] as String,
      shoes: json['shoes'] as String,
      accessories: json['accessories'] as String,
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
