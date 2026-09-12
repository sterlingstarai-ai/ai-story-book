import 'dart:async';

import 'package:ai_story_book/models/library_book.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://localhost', userKey: 'library-test');
  final requests = <Completer<LibraryResponse>>[];
  final sorts = <String>[];

  @override
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
    String? cursor,
    String sort = 'newest',
    String? style,
    String? targetAge,
  }) {
    sorts.add(sort);
    final request = Completer<LibraryResponse>();
    requests.add(request);
    return request.future;
  }
}

LibraryResponse _page(List<String> ids, {String? cursor}) => LibraryResponse(
  books: ids
      .map(
        (id) => LibraryBook(
          id: id,
          title: id,
          coverImageUrl: '',
          targetAge: '5-7',
          style: 'watercolor',
          createdAt: DateTime(2026),
        ),
      )
      .toList(),
  total: 3,
  nextCursor: cursor,
  hasMore: cursor != null,
);

void main() {
  late _Api api;
  late ProviderContainer container;
  late LibraryBrowseNotifier notifier;

  setUp(() async {
    api = _Api();
    container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(api)],
    );
    final initial = container.read(libraryBrowseProvider.future);
    api.requests.single.complete(_page(['first'], cursor: 'first'));
    await initial;
    notifier = container.read(libraryBrowseProvider.notifier);
  });
  tearDown(() {
    container.dispose();
    api.close();
  });

  test('refresh wins over stale pagination success and failure', () async {
    for (final fail in [false, true]) {
      final index = api.requests.length;
      final more = notifier.loadMore();
      final refresh = notifier.refresh();
      api.requests[index + 1].complete(_page(['fresh'], cursor: 'fresh'));
      await refresh;
      if (fail) {
        api.requests[index].completeError(Exception('old request'));
      } else {
        api.requests[index].complete(_page(['stale']));
      }
      await more;
      final state = container.read(libraryBrowseProvider).requireValue;
      expect(state.books.map((b) => b.id), ['fresh']);
      expect(state.isLoadingMore, isFalse);
    }
  });

  test(
    'switching back during a pending filter keeps the latest choice',
    () async {
      final title = notifier.setSort('title');
      final newest = notifier.setSort('newest');
      expect(api.sorts, ['newest', 'title', 'newest']);
      api.requests[2].complete(_page(['newest']));
      await newest;
      api.requests[1].complete(_page(['title']));
      await title;
      final state = container.read(libraryBrowseProvider).requireValue;
      expect(state.sort, 'newest');
      expect(state.books.single.id, 'newest');
    },
  );

  test('pagination coalesces overlap and excludes duplicate books', () async {
    final more = notifier.loadMore();
    await notifier.loadMore();
    expect(api.requests.length, 2);
    api.requests.last.complete(_page(['first', 'second', 'second']));
    await more;
    final state = container.read(libraryBrowseProvider).requireValue;
    expect(state.books.map((b) => b.id), ['first', 'second']);
    expect(state.nextCursor, isNull);
    expect(state.hasMore, isFalse);
  });

  test('disposed provider ignores a pending pagination result', () async {
    final more = notifier.loadMore();
    container.dispose();
    api.requests.last.complete(_page(['stale']));
    await more;
  });
}
