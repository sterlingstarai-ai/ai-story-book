import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../core/api_error.dart';
import '../core/env_config.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../services/iap_service.dart';
import '../services/kakao_share_service.dart';
import '../services/parental_control_service.dart';
import '../services/rewarded_ad_service.dart';
import '../services/review_service.dart';
import '../services/screen_time_service.dart';
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

/// ParentalControlService Provider
final parentalControlServiceProvider = Provider<ParentalControlService>((ref) {
  return ParentalControlService();
});

/// IAP Service Provider
final iapServiceProvider = Provider<IapService>((ref) {
  return IapService();
});

/// In-App Review Service Provider
final reviewServiceProvider = Provider<ReviewService>((ref) {
  return ReviewService();
});

/// Kakao Share Service Provider
final kakaoShareServiceProvider = Provider<KakaoShareService>((ref) {
  return KakaoShareService();
});

/// Rewarded Ad Service Provider
final rewardedAdServiceProvider = Provider<RewardedAdService>((ref) {
  return const RewardedAdService();
});

/// API Base URL
final apiBaseUrlProvider = Provider<String>((ref) {
  return EnvConfig.apiBaseUrl;
});

/// API Client Provider
final apiClientProvider = Provider<ApiClient>((ref) {
  final baseUrl = ref.watch(apiBaseUrlProvider);
  final userService = ref.watch(userServiceProvider);
  final userKey = userService.getUserKey();
  final profileId = userService.getActiveProfileId();

  return ApiClient(
    baseUrl: baseUrl,
    userKey: userKey,
    profileId: profileId,
  );
});

final appThemeModeProvider =
    NotifierProvider<AppThemeModeNotifier, ThemeMode>(AppThemeModeNotifier.new);

class AppThemeModeNotifier extends Notifier<ThemeMode> {
  static const _storageKey = 'app_theme_mode_v1';

  @override
  ThemeMode build() {
    final prefs = ref.watch(sharedPreferencesProvider);
    final stored = prefs.getString(_storageKey);
    if (stored == ThemeMode.dark.name) {
      return ThemeMode.dark;
    }
    if (stored == ThemeMode.system.name) {
      return ThemeMode.system;
    }
    return ThemeMode.light;
  }

  Future<void> setDarkMode(bool enabled) async {
    final next = enabled ? ThemeMode.dark : ThemeMode.light;
    state = next;
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.setString(_storageKey, next.name);
  }
}

final screenTimeServiceProvider = Provider<ScreenTimeService>((ref) {
  return ScreenTimeService();
});

final screenTimeStateProvider =
    NotifierProvider<ScreenTimeNotifier, ScreenTimeSnapshot>(
  ScreenTimeNotifier.new,
);

class ScreenTimeNotifier extends Notifier<ScreenTimeSnapshot> {
  Timer? _heartbeatTimer;
  DateTime? _sessionStartedAt;
  bool _isSyncing = false;

  @override
  ScreenTimeSnapshot build() {
    ref.onDispose(() {
      _stopHeartbeat();
      unawaited(_flushElapsedUsage());
    });
    return ScreenTimeSnapshot.initial();
  }

  Future<void> initialize() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final service = ref.read(screenTimeServiceProvider);
    state = await service.load(prefs);
    _restartHeartbeatIfNeeded();
  }

  void onAppResumed() {
    if (!state.enabled || state.isLocked) {
      return;
    }
    _sessionStartedAt ??= DateTime.now();
    _restartHeartbeatIfNeeded();
  }

  Future<void> onAppPaused() async {
    await _flushElapsedUsage();
    _stopHeartbeat();
  }

  Future<void> syncSettings({
    required bool enabled,
    required int dailyLimitMinutes,
  }) async {
    await _flushElapsedUsage();

    final prefs = ref.read(sharedPreferencesProvider);
    final service = ref.read(screenTimeServiceProvider);
    state = await service.syncSettings(
      prefs,
      enabled: enabled,
      dailyLimitMinutes: dailyLimitMinutes,
    );

    if (!state.enabled || state.isLocked) {
      _sessionStartedAt = null;
      _stopHeartbeat();
      return;
    }
    _sessionStartedAt ??= DateTime.now();
    _restartHeartbeatIfNeeded();
  }

  Future<void> grantExtensionMinutes(int minutes) async {
    if (minutes <= 0) {
      return;
    }
    final prefs = ref.read(sharedPreferencesProvider);
    final service = ref.read(screenTimeServiceProvider);
    state = await service.addExtensionMinutes(
      prefs,
      minutes: minutes,
    );

    if (state.enabled && !state.isLocked) {
      _sessionStartedAt ??= DateTime.now();
      _restartHeartbeatIfNeeded();
    }
  }

  Future<void> resetToday() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final service = ref.read(screenTimeServiceProvider);
    state = await service.resetToday(prefs);
    if (state.enabled && !state.isLocked) {
      _sessionStartedAt = DateTime.now();
      _restartHeartbeatIfNeeded();
    } else {
      _sessionStartedAt = null;
      _stopHeartbeat();
    }
  }

  Future<void> _flushElapsedUsage() async {
    if (_isSyncing) {
      return;
    }
    final startedAt = _sessionStartedAt;
    if (startedAt == null || !state.enabled) {
      return;
    }

    final elapsedSeconds = DateTime.now().difference(startedAt).inSeconds;
    if (elapsedSeconds <= 0) {
      return;
    }

    _isSyncing = true;
    try {
      _sessionStartedAt = DateTime.now();
      final prefs = ref.read(sharedPreferencesProvider);
      final service = ref.read(screenTimeServiceProvider);
      state = await service.addUsageSeconds(
        prefs,
        seconds: elapsedSeconds,
      );
      if (state.isLocked) {
        _sessionStartedAt = null;
        _stopHeartbeat();
      }
    } finally {
      _isSyncing = false;
    }
  }

  void _restartHeartbeatIfNeeded() {
    _stopHeartbeat();
    if (!state.enabled || state.isLocked) {
      return;
    }
    _sessionStartedAt ??= DateTime.now();
    _heartbeatTimer = Timer.periodic(
      const Duration(seconds: 20),
      (_) => unawaited(_flushElapsedUsage()),
    );
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }
}

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

class LibraryBrowseState {
  final List<LibraryBook> books;
  final int total;
  final String? nextCursor;
  final bool hasMore;
  final bool isLoadingMore;
  final bool isOffline;
  final String sort;
  final String? style;
  final String? targetAge;

  const LibraryBrowseState({
    required this.books,
    required this.total,
    required this.nextCursor,
    required this.hasMore,
    required this.isLoadingMore,
    required this.isOffline,
    required this.sort,
    required this.style,
    required this.targetAge,
  });

  factory LibraryBrowseState.initial() {
    return const LibraryBrowseState(
      books: [],
      total: 0,
      nextCursor: null,
      hasMore: false,
      isLoadingMore: false,
      isOffline: false,
      sort: 'newest',
      style: null,
      targetAge: null,
    );
  }

  LibraryBrowseState copyWith({
    List<LibraryBook>? books,
    int? total,
    String? nextCursor,
    bool clearNextCursor = false,
    bool? hasMore,
    bool? isLoadingMore,
    bool? isOffline,
    String? sort,
    String? style,
    bool clearStyle = false,
    String? targetAge,
    bool clearTargetAge = false,
  }) {
    return LibraryBrowseState(
      books: books ?? this.books,
      total: total ?? this.total,
      nextCursor: clearNextCursor ? null : (nextCursor ?? this.nextCursor),
      hasMore: hasMore ?? this.hasMore,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      isOffline: isOffline ?? this.isOffline,
      sort: sort ?? this.sort,
      style: clearStyle ? null : (style ?? this.style),
      targetAge: clearTargetAge ? null : (targetAge ?? this.targetAge),
    );
  }
}

final libraryBrowseProvider =
    AsyncNotifierProvider<LibraryBrowseNotifier, LibraryBrowseState>(
  LibraryBrowseNotifier.new,
);

class LibraryBrowseNotifier extends AsyncNotifier<LibraryBrowseState> {
  static const int _pageSize = 20;
  bool _loadMoreInFlight = false;

  @override
  Future<LibraryBrowseState> build() async {
    return _fetchFirstPage(
      const LibraryBrowseState(
        books: [],
        total: 0,
        nextCursor: null,
        hasMore: false,
        isLoadingMore: false,
        isOffline: false,
        sort: 'newest',
        style: null,
        targetAge: null,
      ),
    );
  }

  Future<LibraryBrowseState> _fetchFirstPage(LibraryBrowseState current) async {
    final api = ref.read(apiClientProvider);
    final response = await api.getLibrary(
      limit: _pageSize,
      sort: current.sort,
      style: current.style,
      targetAge: current.targetAge,
    );
    return current.copyWith(
      books: response.books,
      total: response.total,
      nextCursor: response.nextCursor,
      hasMore: response.hasMore,
      isLoadingMore: false,
      isOffline: false,
    );
  }

  Future<void> refresh() async {
    final current = state.valueOrNull ?? LibraryBrowseState.initial();
    try {
      final next = await _fetchFirstPage(current);
      state = AsyncValue.data(next);
    } catch (error, stackTrace) {
      if (_isOfflineError(error) && current.books.isNotEmpty) {
        state = AsyncValue.data(current.copyWith(isOffline: true));
        return;
      }
      state = AsyncValue.error(error, stackTrace);
    }
  }

  Future<void> setSort(String sort) async {
    final current = state.valueOrNull ?? LibraryBrowseState.initial();
    if (current.sort == sort) {
      return;
    }
    final nextState = current.copyWith(sort: sort, isLoadingMore: false);
    await _reload(nextState);
  }

  Future<void> setStyleFilter(String? style) async {
    final current = state.valueOrNull ?? LibraryBrowseState.initial();
    final normalized = (style == null || style.isEmpty) ? null : style;
    if (current.style == normalized) {
      return;
    }
    final nextState = normalized == null
        ? current.copyWith(clearStyle: true)
        : current.copyWith(style: normalized);
    await _reload(nextState);
  }

  Future<void> setTargetAgeFilter(String? targetAge) async {
    final current = state.valueOrNull ?? LibraryBrowseState.initial();
    final normalized =
        (targetAge == null || targetAge.isEmpty) ? null : targetAge;
    if (current.targetAge == normalized) {
      return;
    }
    final nextState = normalized == null
        ? current.copyWith(clearTargetAge: true)
        : current.copyWith(targetAge: normalized);
    await _reload(nextState);
  }

  Future<void> clearFilters() async {
    final current = state.valueOrNull ?? LibraryBrowseState.initial();
    if (current.style == null && current.targetAge == null) {
      return;
    }
    final nextState = current.copyWith(clearStyle: true, clearTargetAge: true);
    await _reload(nextState);
  }

  Future<void> _reload(LibraryBrowseState nextState) async {
    try {
      final loaded = await _fetchFirstPage(
        nextState.copyWith(
          books: const [],
          total: 0,
          clearNextCursor: true,
          hasMore: false,
          isLoadingMore: false,
          isOffline: false,
        ),
      );
      state = AsyncValue.data(loaded);
    } catch (error, stackTrace) {
      final current = state.valueOrNull;
      if (current != null &&
          _isOfflineError(error) &&
          current.books.isNotEmpty) {
        state = AsyncValue.data(current.copyWith(isOffline: true));
        return;
      }
      state = AsyncValue.error(error, stackTrace);
    }
  }

  Future<void> loadMore() async {
    final current = state.valueOrNull;
    if (current == null ||
        !current.hasMore ||
        current.isLoadingMore ||
        _loadMoreInFlight) {
      return;
    }
    _loadMoreInFlight = true;
    state = AsyncValue.data(
        current.copyWith(isLoadingMore: true, isOffline: false));

    try {
      final api = ref.read(apiClientProvider);
      final response = await api.getLibrary(
        limit: _pageSize,
        cursor: current.nextCursor,
        sort: current.sort,
        style: current.style,
        targetAge: current.targetAge,
      );
      final mergedBooks = List<LibraryBook>.from(current.books)
        ..addAll(response.books);

      state = AsyncValue.data(
        current.copyWith(
          books: mergedBooks,
          total: response.total,
          nextCursor: response.nextCursor,
          hasMore: response.hasMore,
          isLoadingMore: false,
          isOffline: false,
        ),
      );
    } catch (error, stackTrace) {
      if (_isOfflineError(error)) {
        state = AsyncValue.data(
            current.copyWith(isLoadingMore: false, isOffline: true));
      } else {
        state = AsyncValue.error(error, stackTrace);
      }
    } finally {
      _loadMoreInFlight = false;
    }
  }

  Future<void> deleteBook(String bookId) async {
    final current = state.valueOrNull;
    if (current == null) {
      return;
    }
    final api = ref.read(apiClientProvider);
    await api.deleteBook(bookId);

    final updatedBooks =
        current.books.where((book) => book.id != bookId).toList();
    final nextTotal = current.total > 0 ? current.total - 1 : 0;
    state = AsyncValue.data(
      current.copyWith(
        books: updatedBooks,
        total: nextTotal,
      ),
    );
  }

  Future<void> renameBook(String bookId, String title) async {
    final current = state.valueOrNull;
    if (current == null) {
      return;
    }
    final api = ref.read(apiClientProvider);
    final updated = await api.updateBookTitle(bookId, title);

    final updatedBooks = current.books
        .map((book) => book.id == bookId ? updated : book)
        .toList();
    state = AsyncValue.data(current.copyWith(books: updatedBooks));
  }

  void clearOfflineBanner() {
    final current = state.valueOrNull;
    if (current == null || !current.isOffline) {
      return;
    }
    state = AsyncValue.data(current.copyWith(isOffline: false));
  }

  bool _isOfflineError(Object error) {
    if (error is ApiError) {
      return error.code == 'CONNECTION_ERROR' ||
          error.code == 'NETWORK_ERROR' ||
          error.code == 'TIMEOUT';
    }
    final message = error.toString().toLowerCase();
    return message.contains('socketexception') ||
        message.contains('failed host lookup') ||
        message.contains('network') ||
        message.contains('connection');
  }
}

class HomeStreakSnapshot {
  final int currentStreak;
  final int longestStreak;
  final int totalDays;
  final bool readToday;
  final String todayThemeName;
  final String todayTopic;
  final String? todayBookId;
  final Set<String> readDates;

  const HomeStreakSnapshot({
    required this.currentStreak,
    required this.longestStreak,
    required this.totalDays,
    required this.readToday,
    required this.todayThemeName,
    required this.todayTopic,
    required this.todayBookId,
    required this.readDates,
  });
}

final homeStreakProvider = FutureProvider<HomeStreakSnapshot>((ref) async {
  final api = ref.read(apiClientProvider);
  final responses = await Future.wait<dynamic>([
    api.getStreakInfo(),
    api.getTodayStory(),
    api.getReadingHistory(days: 35),
  ]);

  final streakInfo = responses[0] as Map<String, dynamic>;
  final todayStory = responses[1] as Map<String, dynamic>;
  final history = responses[2] as List<dynamic>;

  final readDates = <String>{};
  for (final item in history) {
    if (item is! Map) {
      continue;
    }
    final date = item['date'];
    if (date == null) {
      continue;
    }
    readDates.add(date.toString());
  }

  return HomeStreakSnapshot(
    currentStreak: _toInt(streakInfo['current_streak']),
    longestStreak: _toInt(streakInfo['longest_streak']),
    totalDays: _toInt(streakInfo['total_days']),
    readToday: _toBool(streakInfo['read_today']),
    todayThemeName:
        _toStringValue(todayStory['theme_name'], fallback: '오늘의 추천'),
    todayTopic:
        _toStringValue(todayStory['topic'], fallback: '오늘의 동화를 만들어보세요!'),
    todayBookId: _toNullableString(todayStory['book_id']),
    readDates: readDates,
  );
});

/// 읽기 성장 리포트 (부모 성장카드)
class GrowthReport {
  const GrowthReport({
    required this.booksRead,
    required this.currentStreak,
    required this.longestStreak,
    required this.totalReadingDays,
    required this.vocabLearned,
    required this.quizTotal,
    required this.quizCorrect,
    required this.quizAccuracy,
    required this.levelNumber,
    required this.levelLabel,
  });

  final int booksRead;
  final int currentStreak;
  final int longestStreak;
  final int totalReadingDays;
  final int vocabLearned;
  final int quizTotal;
  final int quizCorrect;
  final double quizAccuracy;
  final int levelNumber;
  final String levelLabel;
}

final growthReportProvider = FutureProvider<GrowthReport>((ref) async {
  final api = ref.read(apiClientProvider);
  final data = await api.getGrowthReport();
  final level = data['reading_level'];
  final levelMap = level is Map ? level : const <String, dynamic>{};
  return GrowthReport(
    booksRead: _toInt(data['books_read']),
    currentStreak: _toInt(data['current_streak']),
    longestStreak: _toInt(data['longest_streak']),
    totalReadingDays: _toInt(data['total_reading_days']),
    vocabLearned: _toInt(data['vocab_learned']),
    quizTotal: _toInt(data['quiz_total']),
    quizCorrect: _toInt(data['quiz_correct']),
    quizAccuracy: (data['quiz_accuracy'] is num)
        ? (data['quiz_accuracy'] as num).toDouble()
        : 0.0,
    levelNumber: _toInt(levelMap['level'], fallback: 1),
    levelLabel: _toStringValue(levelMap['label'], fallback: '성장 중'),
  );
});

int _toInt(dynamic value, {int fallback = 0}) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value) ?? fallback;
  }
  return fallback;
}

bool _toBool(dynamic value, {bool fallback = false}) {
  if (value is bool) {
    return value;
  }
  if (value is num) {
    return value != 0;
  }
  if (value is String) {
    final normalized = value.trim().toLowerCase();
    if (normalized == 'true' || normalized == '1') {
      return true;
    }
    if (normalized == 'false' || normalized == '0') {
      return false;
    }
  }
  return fallback;
}

String _toStringValue(dynamic value, {required String fallback}) {
  if (value == null) {
    return fallback;
  }
  final text = value.toString().trim();
  return text.isEmpty ? fallback : text;
}

String? _toNullableString(dynamic value) {
  if (value == null) {
    return null;
  }
  final text = value.toString().trim();
  return text.isEmpty ? null : text;
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
  final startedAt = DateTime.now();
  var attempts = 0;
  const maxAttempts = 120;
  const hardTimeout = Duration(minutes: 10);

  while (true) {
    attempts += 1;
    final elapsed = DateTime.now().difference(startedAt);
    if (elapsed > hardTimeout) {
      throw TimeoutException(
        '생성 시간이 너무 오래 걸리고 있어요. 잠시 후 다시 시도해주세요.',
      );
    }

    if (attempts > maxAttempts) {
      throw TimeoutException(
        '생성이 지연되고 있어요. 다시 시도 버튼으로 상태를 확인해주세요.',
      );
    }

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
  final prefs = ref.read(sharedPreferencesProvider);
  final cacheKey = 'book_cache_${bookId}_v1';

  try {
    final book = await api.getBook(bookId);
    await prefs.setString(cacheKey, jsonEncode(book.toJson()));
    return book;
  } catch (error) {
    final cached = prefs.getString(cacheKey);
    if (cached != null && cached.isNotEmpty) {
      try {
        final decoded = jsonDecode(cached);
        if (decoded is Map<String, dynamic>) {
          return BookResult.fromJson(decoded);
        }
      } catch (_) {
        // 캐시 파싱 실패 시 원래 에러를 그대로 전파한다.
      }
    }
    rethrow;
  }
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
