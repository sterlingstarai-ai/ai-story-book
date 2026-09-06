import 'book_spec.dart';

class GenerationOptions {
  const GenerationOptions(this.allowedStyles);
  final List<BookStyle> allowedStyles;

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
    return GenerationOptions(List.unmodifiable(known));
  }
}
