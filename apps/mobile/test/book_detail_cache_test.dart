import 'dart:convert';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/models/job_status.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _BookApi extends ApiClient {
  _BookApi(this.load)
      : super(baseUrl: 'http://localhost', userKey: 'cache-test');

  final Future<BookResult> Function() load;

  @override
  Future<BookResult> getBook(String bookId) => load();
}

BookResult _book(String title) => BookResult(
      bookId: 'book-1',
      title: title,
      coverImageUrl: '',
      pages: const [],
    );

void main() {
  const cacheKey = 'book_cache_book-1_v1';

  Future<(ProviderContainer, SharedPreferences)> setup(_BookApi api) async {
    SharedPreferences.setMockInitialValues({
      cacheKey: jsonEncode(_book('cached').toJson()),
    });
    final prefs = await SharedPreferences.getInstance();
    final container = ProviderContainer(overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
    ]);
    addTearDown(container.dispose);
    return (container, prefs);
  }

  test('reopening a book obtains fresh media URLs instead of returning cache',
      () async {
    final (container, prefs) =
        await setup(_BookApi(() async => _book('fresh')));
    final result = await container.read(bookDetailProvider('book-1').future);
    expect(result.title, 'fresh');
    expect(jsonDecode(prefs.getString(cacheKey)!)['title'], 'fresh');
  });

  test('offline reading may use the saved book', () async {
    final (container, _) = await setup(_BookApi(() async => throw ApiError(
        code: 'NETWORK_ERROR', message: 'Offline', statusCode: 0)));
    final result = await container.read(bookDetailProvider('book-1').future);
    expect(result.title, 'cached');
  });

  for (final status in [401, 403, 404]) {
    test('HTTP $status does not bypass server denial with a cached book',
        () async {
      final denial = ApiError(
          code: 'HTTP_$status', message: 'Unavailable', statusCode: status);
      final (container, prefs) =
          await setup(_BookApi(() async => throw denial));
      await expectLater(container.read(bookDetailProvider('book-1').future),
          throwsA(same(denial)));
      expect(prefs.containsKey(cacheKey), isFalse);
    });
  }
}
