/// 서재의 책 모델
class LibraryBook {
  final String id;
  final String title;
  final String coverImageUrl;
  final String targetAge;
  final String style;
  final String? theme;
  final DateTime createdAt;

  LibraryBook({
    required this.id,
    required this.title,
    required this.coverImageUrl,
    required this.targetAge,
    required this.style,
    this.theme,
    required this.createdAt,
  });

  factory LibraryBook.fromJson(Map<String, dynamic> json) {
    return LibraryBook(
      id: (json['book_id'] ?? json['id']) as String,
      title: json['title'] as String,
      coverImageUrl: json['cover_image_url'] as String,
      targetAge: json['target_age'] as String,
      style: json['style'] as String,
      theme: json['theme'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

/// 서재 응답
class LibraryResponse {
  final List<LibraryBook> books;
  final int total;

  LibraryResponse({
    required this.books,
    required this.total,
  });

  factory LibraryResponse.fromJson(Map<String, dynamic> json) {
    return LibraryResponse(
      books: (json['books'] as List<dynamic>)
          .map((b) => LibraryBook.fromJson(b as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
    );
  }
}
