import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../services/user_service.dart';

// ==================== Core Providers ====================

/// SharedPreferences Provider
final sharedPreferencesProvider = Provider<SharedPreferences>((ref) {
  throw UnimplementedError('SharedPreferences must be overridden');
});

/// UserService Provider
final userServiceProvider = Provider<UserService>((ref) {
  final prefs = ref.watch(sharedPreferencesProvider);
  return UserService(prefs);
});

/// API Base URL
final apiBaseUrlProvider = Provider<String>((ref) {
  // 개발 환경에서는 localhost 사용
  // 프로덕션에서는 실제 서버 URL 사용
  return 'http://localhost:8000';
});

/// API Client Provider
final apiClientProvider = Provider<ApiClient>((ref) {
  final baseUrl = ref.watch(apiBaseUrlProvider);
  final userService = ref.watch(userServiceProvider);
  final userKey = userService.getUserKey();

  return ApiClient(
    baseUrl: baseUrl,
    userKey: userKey,
  );
});

// ==================== Library Providers ====================

/// 서재 책 목록 Provider
final libraryProvider =
    AsyncNotifierProvider<LibraryNotifier, List<LibraryBook>>(
  LibraryNotifier.new,
);

class LibraryNotifier extends AsyncNotifier<List<LibraryBook>> {
  @override
  Future<List<LibraryBook>> build() async {
    return _fetchLibrary();
  }

  Future<List<LibraryBook>> _fetchLibrary() async {
    final api = ref.read(apiClientProvider);
    final response = await api.getLibrary();
    return response.books;
  }

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchLibrary());
  }
}

// ==================== Characters Providers ====================

/// 캐릭터 목록 Provider
final charactersProvider =
    AsyncNotifierProvider<CharactersNotifier, List<Character>>(
  CharactersNotifier.new,
);

class CharactersNotifier extends AsyncNotifier<List<Character>> {
  @override
  Future<List<Character>> build() async {
    return _fetchCharacters();
  }

  Future<List<Character>> _fetchCharacters() async {
    final api = ref.read(apiClientProvider);
    return api.getCharacters();
  }

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetchCharacters());
  }
}

// ==================== Book Creation Providers ====================

/// 현재 생성 중인 Job 상태
final currentJobProvider = StateProvider<JobStatus?>((ref) => null);

/// Job 상태 폴링 Provider
final jobPollingProvider =
    StreamProvider.family<JobStatus, String>((ref, jobId) async* {
  final api = ref.read(apiClientProvider);

  while (true) {
    final status = await api.getBookStatus(jobId);
    yield status;

    if (status.isComplete || status.isFailed) {
      break;
    }

    await Future.delayed(const Duration(seconds: 2));
  }
});

/// 책 생성 Notifier
final bookCreationProvider =
    AsyncNotifierProvider<BookCreationNotifier, void>(BookCreationNotifier.new);

class BookCreationNotifier extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  Future<String> createBook(BookSpec spec) async {
    final api = ref.read(apiClientProvider);

    state = const AsyncValue.loading();

    try {
      final response = await api.createBook(spec);

      // 현재 Job 상태 초기화
      ref.read(currentJobProvider.notifier).state = JobStatus(
        jobId: response.jobId,
        status: JobState.queued,
        progress: 0,
      );

      state = const AsyncValue.data(null);
      return response.jobId;
    } catch (e, st) {
      state = AsyncValue.error(e, st);
      rethrow;
    }
  }
}

// ==================== Book Viewer Provider ====================

/// 책 상세 조회 Provider
final bookDetailProvider =
    FutureProvider.family<BookResult, String>((ref, bookId) async {
  final api = ref.read(apiClientProvider);
  return api.getBook(bookId);
});

/// 현재 보고 있는 페이지 인덱스
final currentPageIndexProvider = StateProvider<int>((ref) => 0);

// ==================== Page Regeneration Provider ====================

/// 페이지 재생성 Notifier
final pageRegenerationProvider =
    AsyncNotifierProvider<PageRegenerationNotifier, void>(
  PageRegenerationNotifier.new,
);

class PageRegenerationNotifier extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  Future<void> regenerate(
    String jobId,
    int pageNumber, {
    required String target, // 'text', 'image', 'both'
  }) async {
    final api = ref.read(apiClientProvider);

    state = const AsyncValue.loading();

    try {
      await api.regeneratePage(jobId, pageNumber, regenerateTarget: target);
      state = const AsyncValue.data(null);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
      rethrow;
    }
  }
}
