import 'book_spec.dart';

class GenerationOptions {
  const GenerationOptions(
    this.allowedStyles, {
    this.firstBookTrialAvailable = false,
    this.generationAccessAllowed = true,
  });
  final List<BookStyle> allowedStyles;
  final bool firstBookTrialAvailable;
  final bool generationAccessAllowed;

  factory GenerationOptions.fromJson(Map<String, dynamic> json) {
    final raw = json['allowed_styles'];
    if (raw is! List || raw.isEmpty || raw.any((value) => value is! String)) {
      throw const FormatException('Invalid allowed styles');
    }
    final known = BookStyle.values
        .where((style) => raw.contains(style.value))
        .toList(growable: false);
    if (known.isEmpty) {
      throw const FormatException('No supported allowed style');
    }
    return GenerationOptions(
      List.unmodifiable(known),
      firstBookTrialAvailable: json['first_book_trial_available'] == true,
      generationAccessAllowed: json['generation_access_allowed'] != false,
    );
  }
}
