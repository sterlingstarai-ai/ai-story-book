import 'json_parsing.dart';

/// 서재의 책 모델
class LibraryBook {
  final String id;
  final String title;
  final String coverImageUrl;
  final String targetAge;
  final String style;
  final String? theme;
  final DateTime createdAt;

  /// 시리즈 그룹핑용 메타데이터 (없으면 단권)
  final String? seriesId;
  final int? seriesIndex;
  final String? characterId;

  LibraryBook({
    required this.id,
    required this.title,
    required this.coverImageUrl,
    required this.targetAge,
    required this.style,
    this.theme,
    required this.createdAt,
    this.seriesId,
    this.seriesIndex,
    this.characterId,
  });

  factory LibraryBook.fromJson(Map<String, dynamic> json) {
    return LibraryBook(
      id: JsonParsing.asRequiredString(
        json['book_id'] ?? json['id'],
        field: 'book_id',
      ),
      title: JsonParsing.asRequiredString(json['title'], field: 'title'),
      coverImageUrl: JsonParsing.asRequiredString(
        json['cover_image_url'],
        field: 'cover_image_url',
      ),
      targetAge: JsonParsing.asRequiredString(
        json['target_age'],
        field: 'target_age',
      ),
      style: JsonParsing.asRequiredString(json['style'], field: 'style'),
      theme: JsonParsing.asOptionalString(json['theme']),
      createdAt: JsonParsing.asRequiredDateTime(
        json['created_at'],
        field: 'created_at',
      ),
      seriesId: JsonParsing.asOptionalString(json['series_id']),
      seriesIndex: JsonParsing.asOptionalInt(json['series_index'],
          field: 'series_index'),
      characterId: JsonParsing.asOptionalString(json['character_id']),
    );
  }
}

/// 서재 응답
class LibraryResponse {
  final List<LibraryBook> books;
  final int total;
  final String? nextCursor;
  final bool hasMore;

  LibraryResponse({
    required this.books,
    required this.total,
    required this.nextCursor,
    required this.hasMore,
  });

  factory LibraryResponse.fromJson(Map<String, dynamic> json) {
    final books = JsonParsing.asList(json['books'], field: 'books')
        .map((book) => LibraryBook.fromJson(
              JsonParsing.asMap(book, field: 'books[]'),
            ))
        .toList();

    return LibraryResponse(
      books: books,
      total: JsonParsing.asOptionalInt(json['total'], field: 'total') ??
          books.length,
      nextCursor: JsonParsing.asOptionalString(json['next_cursor']),
      hasMore:
          JsonParsing.asOptionalBool(json['has_more'], field: 'has_more') ??
              false,
    );
  }
}
