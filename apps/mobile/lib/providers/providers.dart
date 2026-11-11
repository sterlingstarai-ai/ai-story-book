import 'dart:async';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:path_provider/path_provider.dart';
import '../core/api_error.dart';
import '../core/env_config.dart';
import '../models/models.dart';
import '../models/generation_options.dart';
import '../services/api_client.dart';
import '../services/job_polling.dart';
import '../services/account_recovery_service.dart';
import '../services/local_media_cleanup.dart';
import '../services/book_media_registry.dart';
import '../services/book_cleanup_plan_journal.dart';
import '../services/book_media_store.dart';
import '../services/book_scoped_cache_manager.dart';
import '../services/scoped_reading_progress.dart';
import '../services/iap_service.dart';
import '../services/iap_purchase_recovery.dart';
import '../services/kakao_share_service.dart';
import '../services/parental_control_service.dart';
import '../services/review_service.dart';
import '../services/notification_scheduler.dart';
import '../services/reading_trend.dart';
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

final iapPurchaseRecoveryProvider = Provider<IapPurchaseRecovery>((ref) {
  final recovery = IapPurchaseRecovery(
    iap: ref.watch(iapServiceProvider),
    verify: (payload) => ref.read(apiClientProvider).verifyIap(payload),
  );
  recovery.start();
  ref.onDispose(recovery.dispose);
  return recovery;
});

/// In-App Review Service Provider
final reviewServiceProvider = Provider<ReviewService>((ref) {
  return ReviewService();
});

/// Kakao Share Service Provider
final kakaoShareServiceProvider = Provider<KakaoShareService>((ref) {
  return KakaoShareService();
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

  final client = ApiClient(
    baseUrl: baseUrl,
    userKey: userKey,
    profileId: profileId,
  );
  ref.onDispose(client.close);
  return client;
});

String bookMediaProfileDigest(String? profileId) => sha256
    .convert(
      utf8.encode(
        'asb:media-profile:v1\u0000${profileId == null ? 'none' : 'profile:$profileId'}',
      ),
    )
    .toString();

String _bookMediaBinding(String baseUrl, String credential) =>
    'book_media_scope_binding_v1_${sha256.convert(utf8.encode('asb:scope-binding:v1\u0000$baseUrl\u0000$credential'))}';
String _localBookMediaScope(String baseUrl, String credential) => sha256
    .convert(
      utf8.encode('asb:local-media-scope:v1\u0000$baseUrl\u0000$credential'),
    )
    .toString();
String _bookMediaAlias(String baseUrl, String serverScope) =>
    'book_media_storage_scope_v1_${sha256.convert(utf8.encode('asb:media-server:v1\u0000$baseUrl\u0000$serverScope'))}';
String _profileMediaScope(String accountScope, String profileDigest) => sha256
    .convert(
      utf8.encode(
        'asb:profile-media-scope:v2\u0000$accountScope\u0000$profileDigest',
      ),
    )
    .toString();
String _profileMediaBinding(String accountScope, String profileDigest) =>
    'book_media_profile_scope_v2_${accountScope}_$profileDigest';

bool _scopeHasOtherAliases(
  SharedPreferences prefs,
  String scope,
  String? currentAlias,
) => prefs
    .getKeys()
    .where(
      (key) =>
          key.startsWith('book_media_storage_scope_v1_') && key != currentAlias,
    )
    .any((key) => prefs.getString(key) == scope);

class BookMediaContext {
  const BookMediaContext(
    this.store, {
    required this.serverVerified,
    this.legacyDeletions = const [],
  });
  final BookMediaStore store;
  final bool serverVerified;
  final List<PendingBookDeletion> legacyDeletions;
}

class BookMediaScopeConflict implements Exception {
  const BookMediaScopeConflict();
}

final bookMediaRegistryProvider = Provider<BookMediaRegistry>((ref) {
  final registry = BookMediaRegistry(
    ref.watch(sharedPreferencesProvider),
    baseDirectory: getTemporaryDirectory,
    journalDirectory: getApplicationSupportDirectory,
  );
  ref.onDispose(() => unawaited(registry.close().catchError((Object _) {})));
  return registry;
});

final bookIllustrationCacheProvider = Provider.autoDispose
    .family<BookScopedCacheManager, ({BookMediaStore store, String bookId})>((
      ref,
      scope,
    ) {
      final manager = BookScopedCacheManager(
        store: scope.store,
        bookId: scope.bookId,
        fileExtension: 'img',
        reuseConnections: true,
      );
      ref.onDispose(() => unawaited(manager.dispose()));
      return manager;
    });

/// Older/offline servers use a local credential-bound scope, never a shared
/// cache for new writes; only a verified server scope enables receipt handling.
final FutureProvider<BookMediaContext>
bookMediaStoreProvider = FutureProvider<BookMediaContext>((ref) async {
  final prefs = ref.watch(sharedPreferencesProvider);
  if (prefs.getBool(localMediaCleanupPendingKey) == true) {
    throw StateError('Local media cleanup is pending');
  }
  final api = ref.watch(apiClientProvider);
  final registry = ref.watch(bookMediaRegistryProvider);
  final user = ref.watch(userServiceProvider);
  final credential = user.getUserKey();
  final profileDigest = bookMediaProfileDigest(user.getActiveProfileId());
  final baseUrl = ref.watch(apiBaseUrlProvider);
  var active = true;
  ref.onDispose(() => active = false);
  final binding = _bookMediaBinding(baseUrl, credential);
  final previous = prefs.getString(binding);
  String? serverScope;
  try {
    serverScope = await api.getAccountMediaScope().timeout(
      const Duration(seconds: 5),
    );
  } on DioException catch (error) {
    if (error.response?.statusCode == 401 ||
        error.response?.statusCode == 403) {
      throw StateError('Account media access is not authorized');
    }
  } catch (_) {
    // Legacy/unconfigured or offline servers cannot authorize receipt use.
  }
  if (!active) throw StateError('Account changed during media setup');
  if (previous != null && serverScope != null && previous != serverScope) {
    throw const BookMediaScopeConflict();
  }
  final localFallback = _localBookMediaScope(baseUrl, credential);
  final knownServerScope = serverScope ?? previous;
  final alias = knownServerScope == null
      ? null
      : _bookMediaAlias(baseUrl, knownServerScope);
  var localScope = alias == null ? null : prefs.getString(alias);
  if (_scopeHasOtherAliases(prefs, localFallback, alias) ||
      (localScope != null && _scopeHasOtherAliases(prefs, localScope, alias))) {
    throw const BookMediaScopeConflict();
  }
  localScope ??= localFallback;
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(localScope)) {
    throw StateError('Invalid local media scope');
  }
  if (serverScope != null &&
      alias != null &&
      prefs.getString(alias) == null &&
      !await prefs.setString(alias, localScope)) {
    throw StateError('Could not persist local media scope');
  }
  if (serverScope != null &&
      previous == null &&
      !await prefs.setString(binding, serverScope)) {
    throw StateError('Could not persist account media scope');
  }
  if (!active) throw StateError('Account changed during media setup');
  final legacyDeletions = <PendingBookDeletion>[];
  for (final legacyScope in {localFallback, localScope}) {
    if (await registry.hasScopeData(legacyScope)) {
      final legacyStore = registry.forScope(legacyScope);
      final pending = await legacyStore.pendingRequests();
      if (serverScope != null) {
        for (final request in pending.where(
          (item) => item.profileDigest == profileDigest,
        )) {
          if (!active) break;
          try {
            await api.confirmBookDeletion(request.bookId, request.requestId);
            if (!active) break;
            await legacyStore.confirmDeletion(
              request.bookId,
              request.requestId,
              profileDigest: profileDigest,
            );
          } catch (_) {
            // Keep the original request and files for the next retry.
          }
        }
      }
      // Confirmed legacy records and their media are deliberately kept:
      // a v1 directory does not identify which profile owns each file.
      legacyDeletions.addAll(
        (await legacyStore.unfinishedDeletions()).where(
          (item) => item.profileDigest == profileDigest,
        ),
      );
    }
  }
  if (!active) throw StateError('Account changed during media setup');
  final profileScope = _profileMediaScope(localScope, profileDigest);
  final profileBinding = _profileMediaBinding(localScope, profileDigest);
  await registry.guardProfileRegistration(() async {
    if (!active ||
        prefs.getBool(localMediaCleanupPendingKey) == true ||
        prefs.getBool(UserService.deletionRequestedKey) == true ||
        prefs.getBool(UserService.deletionCommittedKey) == true) {
      throw StateError('Account cleanup is pending');
    }
    final savedProfileScope = prefs.getString(profileBinding);
    if (savedProfileScope != null && savedProfileScope != profileScope) {
      throw const BookMediaScopeConflict();
    }
    if (savedProfileScope == null &&
        !await prefs.setString(profileBinding, profileScope)) {
      throw StateError('Could not persist profile media scope');
    }
  });
  if (!active) throw StateError('Account changed during media setup');
  final store = registry.forScope(profileScope);
  await store.initialize();
  Future<void> clearBook(String bookId, String profile) async {
    for (final key in [
      scopedBookCacheKey(store.scopeDigest, profile, bookId),
    ]) {
      if (!await prefs.remove(key)) {
        throw StateError('Could not clear deleted book data');
      }
    }
    await clearScopedBookProgress(prefs, store.scopeDigest, bookId);
  }

  try {
    for (final request in await store.confirmedDeletions()) {
      if (!active) break;
      await clearBook(request.bookId, request.profileDigest);
    }
    await store.retryPending();
    for (final request
        in serverScope == null
            ? <PendingBookDeletion>[]
            : await store.pendingRequests()) {
      if (!active || request.profileDigest != profileDigest) continue;
      try {
        await api.confirmBookDeletion(request.bookId, request.requestId);
        if (!active) break;
        await store.confirmDeletion(
          request.bookId,
          request.requestId,
          profileDigest: profileDigest,
        );
        await clearBook(request.bookId, request.profileDigest);
        await store.purgeBook(request.bookId);
      } catch (_) {
        // An unavailable or ambiguous receipt never confirms deletion.
      }
    }
  } catch (_) {
    // Per-book tombstones remain blocked; other books can still be opened.
  }
  if (!active) throw StateError('Account changed during media setup');
  return BookMediaContext(
    store,
    serverVerified: serverScope != null,
    legacyDeletions: legacyDeletions,
  );
});

final readingProgressProvider =
    FutureProvider.family<ScopedReadingProgress, String>((ref, bookId) async {
      final api = ref.watch(apiClientProvider);
      final prefs = ref.watch(sharedPreferencesProvider);
      var active = true;
      ref.onDispose(() => active = false);
      final media = await ref.watch(bookMediaStoreProvider.future);
      if (!active) throw StateError('Reading scope changed');
      return ScopedReadingProgress(prefs, media.store, bookId, () {
        if (!active) return false;
        return identical(ref.read(apiClientProvider), api) &&
            !ref.read(bookMediaBlockedProvider(bookId));
      });
    });

final homeReadingProgressProvider = FutureProvider.family<int, String>((
  ref,
  bookId,
) async {
  try {
    final progress = await ref.watch(readingProgressProvider(bookId).future);
    return await progress.page() ?? 0;
  } catch (_) {
    return 0;
  }
});

final bookMediaBlockedProvider = Provider.family<bool, String>((ref, bookId) {
  ref.watch(bookMediaStoreProvider);
  final prefs = ref.watch(sharedPreferencesProvider);
  final user = ref.watch(userServiceProvider);
  final baseUrl = ref.watch(apiBaseUrlProvider);
  String credential;
  try {
    credential = user.getUserKey();
  } on UserKeyUnavailable {
    // The account is unavailable: block media instead of crashing the viewer.
    return true;
  }
  final serverScope = prefs.getString(_bookMediaBinding(baseUrl, credential));
  final accountScope = serverScope == null
      ? _localBookMediaScope(baseUrl, credential)
      : prefs.getString(_bookMediaAlias(baseUrl, serverScope)) ??
            _localBookMediaScope(baseUrl, credential);
  final profile = bookMediaProfileDigest(user.getActiveProfileId());
  final scope = _profileMediaScope(accountScope, profile);
  return BookMediaStore.isBookBlocked(prefs, scope, bookId) ||
      BookMediaStore.isLegacyBookBlockedForProfile(
        prefs,
        accountScope,
        bookId,
        profile,
      ) ||
      BookMediaStore.isLegacyBookBlockedForProfile(
        prefs,
        _localBookMediaScope(baseUrl, credential),
        bookId,
        profile,
      );
});

final pendingBookDeletionsProvider = FutureProvider<List<PendingBookDeletion>>((
  ref,
) async {
  final media = await ref.watch(bookMediaStoreProvider.future);
  final profile = bookMediaProfileDigest(
    ref.watch(userServiceProvider).getActiveProfileId(),
  );
  return [
    ...(await media.store.unfinishedDeletions()).where(
      (request) => request.profileDigest == profile,
    ),
    ...media.legacyDeletions,
  ];
});

final localMediaCachePurgerProvider = Provider<Future<void> Function()>(
  (ref) => purgeAppImageCache,
);
final bookCleanupPlanJournalProvider = Provider<BookCleanupPlanJournal>(
  (ref) =>
      BookCleanupPlanJournal(baseDirectory: getApplicationSupportDirectory),
);

/// Called only after explicit on-device confirmation and a committed account
/// deletion. Historical scopes are never guessed from unrelated accounts.
final clearLegacyAccountMediaProvider = Provider<Future<void> Function()>((
  ref,
) {
  return () async {
    final prefs = ref.read(sharedPreferencesProvider);
    if (prefs.getBool(UserService.deletionCommittedKey) != true ||
        prefs.getBool(localMediaCleanupPendingKey) != true) {
      throw StateError('Account deletion is not committed');
    }
    final user = ref.read(userServiceProvider);
    await user.resumeKeyForDeletion();
    final credential = user.getUserKey();
    final baseUrl = ref.read(apiBaseUrlProvider);
    final binding = _bookMediaBinding(baseUrl, credential);
    final serverScope = prefs.getString(binding);
    final alias = serverScope == null
        ? null
        : _bookMediaAlias(baseUrl, serverScope);
    final localScope = alias == null ? null : prefs.getString(alias);
    final expected = <String>{
      _localBookMediaScope(baseUrl, credential),
      if (localScope != null) localScope,
    };
    if (expected.any(
      (scope) =>
          !RegExp(r'^[0-9a-f]{64}$').hasMatch(scope) ||
          _scopeHasOtherAliases(prefs, scope, alias),
    )) {
      throw StateError('Account media ownership requires reconciliation');
    }
    final journal = ref.read(bookCleanupPlanJournalProvider);
    final raw = await reconcileBookCleanupPlan(
      prefs,
      journal.read,
      journal.write,
    );
    if (raw == null) throw StateError('Cleanup plan is missing');
    final plan = jsonDecode(raw);
    if (plan is! Map<String, dynamic> ||
        (plan['kind'] != null && plan['kind'] != 'account') ||
        (plan['legacy_scopes'] ?? plan['scopes']) is! List) {
      throw StateError('Historical media ownership requires reconciliation');
    }
    final planned = Set<String>.from(
      (plan['legacy_scopes'] ?? plan['scopes']) as List,
    );
    if (planned.length != expected.length || !planned.containsAll(expected)) {
      throw StateError('Account cleanup scopes differ');
    }
    await ref
        .read(bookMediaRegistryProvider)
        .purgeScopes(planned, eraseJournal: true);
  };
});
final localMediaCleanupProvider = Provider<LocalMediaCleanup>((ref) {
  final preferences = ref.watch(sharedPreferencesProvider);
  final purgeCache = ref.watch(localMediaCachePurgerProvider);
  final planJournal = ref.watch(bookCleanupPlanJournalProvider);
  Future<String> ensurePlan(String kind) async {
    var planText = await reconcileBookCleanupPlan(
      preferences,
      planJournal.read,
      planJournal.write,
    );
    if (planText == null) {
      final user = ref.read(userServiceProvider);
      String credential;
      try {
        credential = user.getUserKey();
      } on UserKeyUnavailable {
        await user.resumeKeyForDeletion();
        credential = user.getUserKey();
      }
      final baseUrl = ref.read(apiBaseUrlProvider);
      final binding = _bookMediaBinding(baseUrl, credential);
      final serverScope = preferences.getString(binding);
      if (serverScope != null &&
          !RegExp(r'^[0-9a-f]{64}$').hasMatch(serverScope)) {
        throw StateError('Invalid account media binding');
      }
      final alias = serverScope == null
          ? null
          : _bookMediaAlias(baseUrl, serverScope);
      final localScope = alias == null ? null : preferences.getString(alias);
      final scopes = <String>{
        _localBookMediaScope(baseUrl, credential),
        if (localScope != null) localScope,
      };
      if (scopes.any(
        (scope) => _scopeHasOtherAliases(preferences, scope, alias),
      )) {
        throw StateError('Account media scopes require reconciliation');
      }
      if (scopes.any((scope) => !RegExp(r'^[0-9a-f]{64}$').hasMatch(scope))) {
        throw StateError('Invalid account media scope');
      }
      final legacyScopes = scopes.toSet();
      final profileKeys = <String>[];
      for (final base in legacyScopes) {
        final prefix = 'book_media_profile_scope_v2_${base}_';
        for (final key in preferences.getKeys().where(
          (key) => key.startsWith(prefix),
        )) {
          final profile = key.substring(prefix.length);
          if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(profile)) {
            throw StateError('Invalid profile binding');
          }
          final expected = _profileMediaScope(base, profile);
          if (preferences.getString(key) != expected) {
            throw StateError('Invalid profile scope');
          }
          scopes.add(expected);
          profileKeys.add(key);
        }
      }
      planText = jsonEncode({
        'scopes': scopes.toList(),
        'legacy_scopes': legacyScopes.toList(),
        'metadata_keys': [binding, if (alias != null) alias, ...profileKeys],
        'kind': kind,
      });
      await planJournal.write(planText);
      if (!await preferences.setString(bookMediaCleanupPlanKey, planText)) {
        throw StateError('Could not persist account media cleanup plan');
      }
    }
    return planText;
  }

  return LocalMediaCleanup(
    preferences,
    clearPlan: planJournal.clear,
    preparePlan: () async {
      final plan = jsonDecode(await ensurePlan('account_requested'));
      if (plan is! Map<String, dynamic> ||
          plan['kind'] != 'account_requested') {
        throw StateError('Existing cleanup plan requires reconciliation');
      }
    },
    onComplete: () {
      ref.read(bookMediaRegistryProvider).releasePurgedScopes();
      ref.invalidate(bookMediaStoreProvider);
    },
    purge: () async {
      // Dispose pending detail requests before erasing offline data so a late
      // response cannot restore a book cache after consent/account deletion.
      ref.invalidate(bookDetailProvider);
      ref.invalidate(bookMediaStoreProvider);
      ref.invalidate(libraryProvider);
      ref.invalidate(libraryBrowseProvider);
      ref.invalidate(charactersProvider);
      var planText = await ensurePlan(
        preferences.getBool(UserService.deletionCommittedKey) == true
            ? 'account'
            : 'consent',
      );
      var plan = jsonDecode(planText);
      if (plan is! Map<String, dynamic> || plan['scopes'] is! List) {
        throw StateError('Invalid account media cleanup plan');
      }
      if (plan['kind'] == 'account_requested' &&
          preferences.getBool(UserService.deletionCommittedKey) != true) {
        throw StateError('Account deletion is not confirmed');
      }
      if (preferences.getBool(UserService.deletionCommittedKey) == true &&
          plan['kind'] != 'account') {
        plan = {...plan, 'kind': 'account'};
        planText = jsonEncode(plan);
        await planJournal.write(planText);
        if (!await preferences.setString(bookMediaCleanupPlanKey, planText)) {
          throw StateError('Could not persist account cleanup commitment');
        }
      }
      final legacy = plan['legacy_scopes'];
      // Old plans have no profile inventory. Preserve all of their scopes.
      final legacyScopes = legacy is List
          ? Set<String>.from(legacy)
          : Set<String>.from(plan['scopes'] as List);
      final newScopes = Set<String>.from(plan['scopes'] as List)
        ..removeAll(legacyScopes);
      void verifyProfileInventory() {
        for (final base in legacyScopes) {
          final prefix = 'book_media_profile_scope_v2_${base}_';
          for (final key in preferences.getKeys().where(
            (key) => key.startsWith(prefix),
          )) {
            final profile = key.substring(prefix.length);
            if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(profile) ||
                preferences.getString(key) !=
                    _profileMediaScope(base, profile) ||
                !newScopes.contains(_profileMediaScope(base, profile))) {
              throw StateError('Profile scope changed during cleanup');
            }
          }
        }
      }

      await ref.read(bookMediaRegistryProvider).guardProfileRegistration(
        () async {
          verifyProfileInventory();
        },
      );
      await ref
          .read(bookMediaRegistryProvider)
          .purgeScopes(
            newScopes,
            eraseJournal:
                preferences.getBool(UserService.deletionCommittedKey) == true,
          );
      verifyProfileInventory();
      for (final oldScope in legacyScopes) {
        if (await ref.read(bookMediaRegistryProvider).hasScopeData(oldScope)) {
          throw StateError('Historical media ownership is unresolved');
        }
      }
      await purgeCache();
      ref.invalidate(bookMediaStoreProvider);
    },
  );
});

final accountRecoveryServiceProvider = Provider<AccountRecoveryService>((ref) {
  final baseUrl = ref.watch(apiBaseUrlProvider);
  return AccountRecoveryService(
    userService: ref.watch(userServiceProvider),
    preferences: ref.watch(sharedPreferencesProvider),
    purgeLocalMedia: ref.watch(localMediaCleanupProvider).run,
    prepareAccountDeletion: ref
        .watch(localMediaCleanupProvider)
        .prepareAccountDeletion,
    clearCleanupPlan: ref.watch(bookCleanupPlanJournalProvider).clear,
    readCleanupPlan: ref.watch(bookCleanupPlanJournalProvider).read,
    writeCleanupPlan: ref.watch(bookCleanupPlanJournalProvider).write,
    cleanupPlanMatchesCredential: (planText) async {
      final plan = jsonDecode(planText);
      if (plan is! Map<String, dynamic> || plan['scopes'] is! List) {
        return false;
      }
      final user = ref.read(userServiceProvider);
      try {
        await user.resumeKeyForDeletion();
        return (plan['scopes'] as List).contains(
          _localBookMediaScope(baseUrl, user.getUserKey()),
        );
      } on UserKeyUnavailable {
        return false;
      }
    },
    clientForKey: (key) => ApiClient(baseUrl: baseUrl, userKey: key),
  );
});

/// Drop every account/profile-scoped in-memory value after credential rotation.
void invalidateRecoveredAccount(WidgetRef ref) {
  invalidateAccountScope(ProviderScope.containerOf(ref.context, listen: false));
}

void invalidateAccountScope(ProviderContainer container) {
  container.read(parentalControlServiceProvider).resetAgeGateSession();
  container.read(screenTimeStateProvider.notifier).forgetAccountSession();
  PaintingBinding.instance.imageCache.clear();
  PaintingBinding.instance.imageCache.clearLiveImages();
  container.invalidate(apiClientProvider);
  container.invalidate(bookMediaStoreProvider);
  container.invalidate(libraryProvider);
  container.invalidate(libraryBrowseProvider);
  container.invalidate(charactersProvider);
  container.invalidate(bookDetailProvider);
  container.invalidate(homeStreakProvider);
  container.invalidate(growthReportProvider);
  container.invalidate(peerComparisonProvider);
  container.invalidate(weeklyReadingTrendProvider);
  container.invalidate(currentJobProvider);
  container.invalidate(jobPollingProvider);
  container.invalidate(bookCreationProvider);
  container.invalidate(todayAttemptKeyProvider);
  container.invalidate(todayAttemptSigProvider);
  container.invalidate(currentPageIndexProvider);
  container.invalidate(pageRegenerationProvider);
  container.invalidate(screenTimeStateProvider);
}

/// Current account entitlements, refreshed each time the creation screen opens.
final generationOptionsProvider = FutureProvider.autoDispose<GenerationOptions>((
  ref,
) async {
  // Never infer entitlements locally or retain another account's style choices.
  final api = ref.watch(apiClientProvider);
  return api.getGenerationOptions();
});

/// 배포 환경 기능 가용성. 실패 시 보수적으로 미지원으로 처리하고 재확인한다.
final capabilitiesProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final api = ref.watch(apiClientProvider);
  Timer? retry;
  var disposed = false;
  ref.onDispose(() {
    disposed = true;
    retry?.cancel();
  });
  try {
    return await api.getCapabilities();
  } catch (_) {
    // A transient connectivity failure must not disable capabilities for the
    // remainder of the app session. Keep the conservative fallback until a
    // subsequent successful response and avoid a tight retry loop.
    if (!disposed) {
      retry = Timer(const Duration(seconds: 30), ref.invalidateSelf);
    }
    return const {'inpaint_supported': false, 'audio_supported': false};
  }
});

final appThemeModeProvider = NotifierProvider<AppThemeModeNotifier, ThemeMode>(
  AppThemeModeNotifier.new,
);

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

/// 잠자리 로컬 알림 스케줄러(테스트에서 Fake 주입).
final notificationSchedulerProvider = Provider<NotificationScheduler>((ref) {
  return LocalNotificationScheduler();
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

  void forgetAccountSession() {
    _sessionStartedAt = null;
    _stopHeartbeat();
    state = ScreenTimeSnapshot.initial();
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
    state = await service.addExtensionMinutes(prefs, minutes: minutes);

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
      state = await service.addUsageSeconds(prefs, seconds: elapsedSeconds);
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
  int _requestVersion = 0;
  LibraryBrowseState? _requestedState;

  LibraryBrowseState get _filterState =>
      _requestedState ?? state.valueOrNull ?? LibraryBrowseState.initial();

  @override
  Future<LibraryBrowseState> build() async {
    _requestVersion++;
    _requestedState = null;
    _loadMoreInFlight = false;
    ref.onDispose(() => _requestVersion++);
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

  Future<void> refresh() => _reload(_filterState);

  Future<void> setSort(String sort) async {
    final current = _filterState;
    if (current.sort == sort) {
      return;
    }
    final nextState = current.copyWith(sort: sort, isLoadingMore: false);
    await _reload(nextState);
  }

  Future<void> setStyleFilter(String? style) async {
    final current = _filterState;
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
    final current = _filterState;
    final normalized = (targetAge == null || targetAge.isEmpty)
        ? null
        : targetAge;
    if (current.targetAge == normalized) {
      return;
    }
    final nextState = normalized == null
        ? current.copyWith(clearTargetAge: true)
        : current.copyWith(targetAge: normalized);
    await _reload(nextState);
  }

  Future<void> clearFilters() async {
    final current = _filterState;
    if (current.style == null && current.targetAge == null) {
      return;
    }
    final nextState = current.copyWith(clearStyle: true, clearTargetAge: true);
    await _reload(nextState);
  }

  Future<void> _reload(LibraryBrowseState nextState) async {
    final version = ++_requestVersion;
    _requestedState = nextState;
    _loadMoreInFlight = false;
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
      if (version != _requestVersion) return;
      state = AsyncValue.data(loaded);
    } catch (error, stackTrace) {
      if (version != _requestVersion) return;
      final current = state.valueOrNull;
      if (current != null &&
          _isOfflineError(error) &&
          current.books.isNotEmpty) {
        state = AsyncValue.data(
          current.copyWith(isOffline: true, isLoadingMore: false),
        );
        return;
      }
      state = AsyncValue.error(error, stackTrace);
    } finally {
      if (version == _requestVersion) _requestedState = null;
    }
  }

  Future<void> loadMore() async {
    final current = state.valueOrNull;
    if (current == null ||
        !current.hasMore ||
        current.isLoadingMore ||
        _loadMoreInFlight ||
        _requestedState != null) {
      return;
    }
    final version = _requestVersion;
    _loadMoreInFlight = true;
    state = AsyncValue.data(
      current.copyWith(isLoadingMore: true, isOffline: false),
    );

    try {
      final api = ref.read(apiClientProvider);
      final response = await api.getLibrary(
        limit: _pageSize,
        cursor: current.nextCursor,
        sort: current.sort,
        style: current.style,
        targetAge: current.targetAge,
      );
      if (version != _requestVersion) return;
      final seen = current.books.map((book) => book.id).toSet();
      final mergedBooks = [
        ...current.books,
        ...response.books.where((book) => seen.add(book.id)),
      ];

      state = AsyncValue.data(
        current.copyWith(
          books: mergedBooks,
          total: response.total,
          nextCursor: response.nextCursor,
          clearNextCursor: response.nextCursor == null,
          hasMore: response.hasMore,
          isLoadingMore: false,
          isOffline: false,
        ),
      );
    } catch (error, stackTrace) {
      if (version != _requestVersion) return;
      if (_isOfflineError(error)) {
        state = AsyncValue.data(
          current.copyWith(isLoadingMore: false, isOffline: true),
        );
      } else {
        state = AsyncValue.error(error, stackTrace);
      }
    } finally {
      if (version == _requestVersion) _loadMoreInFlight = false;
    }
  }

  Future<bool> deleteBook(String bookId) async {
    final current = state.valueOrNull;
    if (current == null) {
      throw StateError('Library is unavailable');
    }
    final api = ref.read(apiClientProvider);
    final media = await ref.read(bookMediaStoreProvider.future);
    if (!identical(ref.read(apiClientProvider), api)) {
      throw const BookDeletionUnconfirmed();
    }
    final priorRequest = (await media.store.unfinishedDeletions()).any(
      (request) => request.bookId == bookId,
    );
    if (!identical(ref.read(apiClientProvider), api)) {
      throw const BookDeletionUnconfirmed();
    }
    if (!media.serverVerified) {
      // A prior request may already have reached an older server. Do not tell
      // the user it never started merely because a new attempt is blocked.
      if (priorRequest) {
        throw const BookDeletionUnconfirmed();
      }
      throw const BookDeletionNotStarted();
    }
    {
      final user = ref.read(userServiceProvider);
      final binding = _bookMediaBinding(
        ref.read(apiBaseUrlProvider),
        user.getUserKey(),
      );
      final expected = ref.read(sharedPreferencesProvider).getString(binding);
      String current;
      try {
        current = await api.getAccountMediaScope().timeout(
          const Duration(seconds: 5),
        );
      } catch (_) {
        if (!identical(ref.read(apiClientProvider), api) || priorRequest) {
          throw const BookDeletionUnconfirmed();
        }
        throw const BookDeletionNotStarted();
      }
      if (!identical(ref.read(apiClientProvider), api) ||
          expected == null ||
          current != expected) {
        // A different account/scope must not reveal another scope's markers.
        throw const BookDeletionUnconfirmed();
      }
    }
    // Old DefaultCacheManager entries cannot yet be attributed reliably, so
    // do not claim that all stored files have been removed.
    const purgePending = true;
    final store = media.store;
    final profile = bookMediaProfileDigest(
      ref.read(userServiceProvider).getActiveProfileId(),
    );
    final request = await store.beginDeletion(bookId, profileDigest: profile);
    ref.invalidate(bookMediaBlockedProvider(bookId));
    ref.invalidate(bookDetailProvider(bookId));
    ref.invalidate(pendingBookDeletionsProvider);
    if (!identical(ref.read(apiClientProvider), api)) {
      throw const BookDeletionUnconfirmed();
    }
    // An error, timeout, 403 or 404 leaves the request pending for a later
    // scoped receipt check; it never authorizes local erasure.
    try {
      await api.deleteBookWithReceipt(bookId, request);
    } catch (_) {
      throw const BookDeletionUnconfirmed();
    }
    await store.confirmDeletion(bookId, request, profileDigest: profile);
    try {
      await store.purgeBook(bookId);
    } catch (_) {
      /* The persisted marker drives a later retry. */
    }
    ref.invalidate(pendingBookDeletionsProvider);
    if (!identical(ref.read(apiClientProvider), api)) return true;
    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();
    final prefs = ref.read(sharedPreferencesProvider);
    ref.invalidate(bookDetailProvider(bookId));
    if (media.serverVerified) {
      await prefs.remove(
        scopedBookCacheKey(media.store.scopeDigest, profile, bookId),
      );
      await clearScopedBookProgress(prefs, media.store.scopeDigest, bookId);
    }
    ref.invalidate(libraryProvider);

    final updatedBooks = current.books
        .where((book) => book.id != bookId)
        .toList();
    final nextTotal = current.total > 0 ? current.total - 1 : 0;
    state = AsyncValue.data(
      current.copyWith(books: updatedBooks, total: nextTotal),
    );
    return purgePending;
  }

  Future<void> renameBook(String bookId, String title) async {
    final current = state.valueOrNull;
    if (current == null) {
      return;
    }
    // A profile switch invalidates the client while media initialization or
    // the request is in flight. Never send using the replacement profile or
    // publish an old profile's result into the newly selected library.
    final api = ref.read(apiClientProvider);
    final version = _requestVersion;
    final profile = bookMediaProfileDigest(
      ref.read(userServiceProvider).getActiveProfileId(),
    );
    final media = await ref.read(bookMediaStoreProvider.future);
    if (version != _requestVersion ||
        !identical(ref.read(apiClientProvider), api)) {
      throw StateError('Profile changed before book rename');
    }
    final updated = await api.updateBookTitle(bookId, title);
    if (version != _requestVersion ||
        !identical(ref.read(apiClientProvider), api)) {
      return;
    }
    // Never let the detail fallback resurrect the old title after a rename.
    final prefs = ref.read(sharedPreferencesProvider);
    await prefs.remove(
      scopedBookCacheKey(media.store.scopeDigest, profile, bookId),
    );
    if (version != _requestVersion ||
        !identical(ref.read(apiClientProvider), api)) {
      return;
    }
    ref.invalidate(bookDetailProvider(bookId));
    ref.invalidate(libraryProvider);

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
  // H25: 안정 키(서버 theme id + topic_id) — 모바일이 로케일별 arb로 표시. 서버 한국어
  // theme_name/topic은 폴백으로 유지.
  final String todayThemeId;
  final String todayTopicId;
  final String? todayBookId;
  final Set<String> readDates;

  const HomeStreakSnapshot({
    required this.currentStreak,
    required this.longestStreak,
    required this.totalDays,
    required this.readToday,
    required this.todayThemeName,
    required this.todayTopic,
    this.todayThemeId = '',
    this.todayTopicId = '',
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
    // M6: 한국어 폴백을 provider 에 두면 en/ja 사용자에게 그대로 노출된다.
    // 빈 값으로 두고 표시 지점(home_screen)이 로케일 문구를 채운다.
    todayThemeName: _toStringValue(todayStory['theme_name'], fallback: ''),
    todayTopic: _toStringValue(todayStory['topic'], fallback: ''),
    todayThemeId: _toStringValue(todayStory['theme'], fallback: ''),
    todayTopicId: _toStringValue(todayStory['topic_id'], fallback: ''),
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
    required this.completion,
    required this.levelNumber,
    required this.levelKey,
    required this.levelLabel,
    required this.scoreValue,
  });

  final int booksRead;
  final int currentStreak;
  final int longestStreak;
  final int totalReadingDays;
  final int vocabLearned;
  final int quizTotal;
  final int quizCorrect;
  final double quizAccuracy;
  final double completion;
  final int levelNumber;

  /// S2: 서버가 주는 안정 키(first_steps 등). 클라이언트 l10n 의 기준이며
  /// `levelLabel`(서버 로컬라이즈 문구)은 키 매핑 실패 시 폴백이다(M5 '안정 키 우선').
  final String levelKey;
  final String levelLabel;
  final int scoreValue; // 복합 읽기 점수(0~100)
}

/// 앱 UI 로캘 코드(ko/en/ja). 지원 밖 로캘은 en 으로 접는다.
///
/// S2: 앱은 UI 로캘을 서버에 저장하지 않는다(L13에서 언어 드롭다운 제거 — 기기 추종이 정본).
/// 그래서 서버가 사용자 언어로 문구를 내려주려면 요청마다 로캘을 실어 보내야 한다.
final appLocaleCodeProvider = Provider<String>((ref) {
  const supported = {'ko', 'en', 'ja'};
  final code = WidgetsBinding.instance.platformDispatcher.locale.languageCode;
  return supported.contains(code) ? code : 'en';
});

final growthReportProvider = FutureProvider<GrowthReport>((ref) async {
  final api = ref.read(apiClientProvider);
  // 서버가 레벨 라벨을 사용자 언어로 내려주도록 기기 로캘을 전달한다(S2).
  final data = await api.getGrowthReport(
    language: ref.watch(appLocaleCodeProvider),
  );
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
    completion: (data['completion'] is num)
        ? (data['completion'] as num).toDouble()
        : 0.0,
    levelNumber: _toInt(levelMap['level'], fallback: 1),
    levelKey: _toStringValue(levelMap['key'], fallback: ''),
    // M6: 한국어 폴백 제거 — 표시 지점(reading_growth_screen)이 로케일 문구로 채운다.
    levelLabel: _toStringValue(levelMap['label'], fallback: ''),
    scoreValue: _toInt(levelMap['score']),
  );
});

/// 최근 6주 주간 읽기 추이 — /v1/streak/history(날짜 목록)에서 클라이언트 집계.
final weeklyReadingTrendProvider = FutureProvider<List<int>>((ref) async {
  final api = ref.read(apiClientProvider);
  final history = await api.getReadingHistory(days: 42);
  final dates = <DateTime>[];
  for (final item in history) {
    if (item is! Map) {
      continue;
    }
    final raw = item['date'];
    if (raw == null) {
      continue;
    }
    final dt = DateTime.tryParse(raw.toString());
    if (dt != null) {
      dates.add(dt);
    }
  }
  return weeklyReadingCounts(dates, DateTime.now());
});

/// 같은 연령대 또래 대비 비교 — /v1/growth/peers.
class PeerComparison {
  const PeerComparison({
    required this.ageBand,
    required this.peerCount,
    required this.isBaseline,
    required this.showRanking,
    required this.myBooks,
    required this.peerBooks,
    required this.myVocab,
    required this.peerVocab,
    required this.myAccuracy,
    required this.peerAccuracy,
    required this.myScore,
    required this.peerScore,
    required this.topPercent,
    required this.medal,
  });

  final String ageBand;
  final int peerCount;
  final bool isBaseline;
  final bool showRanking; // 3-5세(전조작기)는 등수 미노출 → 자기성장만
  final int myBooks;
  final double peerBooks;
  final int myVocab;
  final double peerVocab;
  final double myAccuracy;
  final double peerAccuracy;
  final int myScore; // 복합 점수(0~100)
  final int peerScore;
  final int topPercent;
  final String medal;
}

final peerComparisonProvider = FutureProvider<PeerComparison>((ref) async {
  final api = ref.read(apiClientProvider);
  final data = await api.getPeerComparison();
  final my = data['my'] is Map ? data['my'] as Map : const <dynamic, dynamic>{};
  final avg = data['peer_avg'] is Map
      ? data['peer_avg'] as Map
      : const <dynamic, dynamic>{};
  double toDouble(dynamic v) => v is num ? v.toDouble() : 0.0;
  return PeerComparison(
    ageBand: _toStringValue(data['age_band'], fallback: '5-7'),
    peerCount: _toInt(data['peer_count']),
    isBaseline: data['is_baseline'] == true,
    // fail-closed: 명시적 true일 때만 등수 노출(누락/오류 시 자기성장만 — 저연령 보호).
    showRanking: data['show_ranking'] == true,
    myBooks: _toInt(my['books_read']),
    peerBooks: toDouble(avg['books_read']),
    myVocab: _toInt(my['vocab_learned']),
    peerVocab: toDouble(avg['vocab_learned']),
    myAccuracy: toDouble(my['quiz_accuracy']),
    peerAccuracy: toDouble(avg['quiz_accuracy']),
    myScore: _toInt(my['score']),
    peerScore: _toInt(avg['score']),
    topPercent: _toInt(data['top_percent'], fallback: 50),
    medal: _toStringValue(data['medal'], fallback: 'none'),
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

/// 기본 제공 캐릭터 프리셋 Provider ('우리 아이를 주인공으로' 기본 이미지 선택)
///
/// 언어코드(앱 로케일)를 family 인자로 받아 표시 텍스트를 로케일별로 서빙받는다.
final characterPresetsProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>((
      ref,
      language,
    ) async {
      return ref
          .read(apiClientProvider)
          .getCharacterPresets(language: language);
    });

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

/// 생성 폴링 예산 — 서버 잡 SLA(10분)와 일치시킨다(H17).
/// 이전에는 maxAttempts(120×2초≈4분)가 먼저 발화해 정상 잡을 4분에 허위 실패시켰다.
const Duration kJobPollingHardTimeout = Duration(minutes: 10);

/// 폴링 예산 초과 여부(순수 헬퍼 — 결정적 단위 테스트용, H17).
bool jobPollingBudgetExceeded(Duration elapsed) =>
    elapsed > kJobPollingHardTimeout;

class _ActiveGenerationSnapshot {
  List<JobStatus> jobs = const [];
}

final _activeGenerationSnapshotProvider =
    Provider.autoDispose<_ActiveGenerationSnapshot>((ref) {
      ref.watch(apiClientProvider);
      return _ActiveGenerationSnapshot();
    });

final activeBookGenerationsProvider =
    FutureProvider.autoDispose<List<JobStatus>>((ref) async {
      final api = ref.watch(apiClientProvider);
      final snapshot = ref.watch(_activeGenerationSnapshotProvider);
      Timer? nextCheck;
      var disposed = false;
      ref.onDispose(() {
        disposed = true;
        nextCheck?.cancel();
      });
      try {
        final jobs = await api.getActiveBookGenerations();
        // Home and library can outlive the progress route.
        if (!disposed) {
          snapshot.jobs = jobs;
          if (jobs.isNotEmpty) {
            nextCheck = Timer(const Duration(seconds: 15), ref.invalidateSelf);
          }
        }
        return jobs;
      } catch (error) {
        final transientError = retryableJobReadError(error);
        if (!disposed && transientError == null) snapshot.jobs = const [];
        if (!disposed && transientError != null) {
          const retryInterval = Duration(seconds: 30);
          final retryAfter = transientError.retryAfter ?? Duration.zero;
          nextCheck = Timer(
            retryAfter > retryInterval ? retryAfter : retryInterval,
            ref.invalidateSelf,
          );
        }
        rethrow;
      }
    });

/// Keep the last verified list usable while its own account/profile retries.
/// A dependency change creates a new snapshot before any old result is shown.
final visibleActiveBookGenerationsProvider =
    Provider.autoDispose<List<JobStatus>>((ref) {
      final result = ref.watch(activeBookGenerationsProvider);
      if (!result.isLoading && !result.hasError) {
        return result.asData?.value ?? const [];
      }
      if (result.hasError && retryableJobReadError(result.error!) == null) {
        return const [];
      }
      try {
        final snapshot = ref.watch(_activeGenerationSnapshotProvider);
        return [
          for (final job in snapshot.jobs) JobStatus.rechecking(job.jobId, job),
        ];
      } on UserKeyUnavailable {
        return const [];
      }
    });

bool activeBookGenerationMayHaveFinished(
  AsyncValue<List<JobStatus>>? previous,
  AsyncValue<List<JobStatus>> next, {
  String? separatelyTrackedJob,
}) {
  final after = next.isLoading ? null : next.asData?.value;
  if (after == null) return false;
  final before = previous?.valueOrNull;
  if (before == null || before.isEmpty) {
    // A job may have finished during an outage before we saw its first status.
    final error = previous?.error;
    return error != null && retryableJobReadError(error) != null;
  }
  final activeIds = after.map((job) => job.jobId).toSet();
  return before.any(
    (job) =>
        job.jobId != separatelyTrackedJob && !activeIds.contains(job.jobId),
  );
}

/// Ordinary status waits can pause when the app leaves the foreground.
final generationInBackgroundProvider = StateProvider<bool>((ref) => false);

/// Poll only while the generation status has a listener.
final jobPollingProvider = StreamProvider.autoDispose.family<JobStatus, String>(
  (ref, jobId) {
    final api = ref.watch(apiClientProvider);
    final cancellation = CancelToken();
    Timer? timer;
    Completer<bool>? waiting;
    var canWake = false;
    void finishWaiting({bool resumed = false}) {
      timer?.cancel();
      timer = null;
      final completion = waiting;
      waiting = null;
      canWake = false;
      completion?.complete(resumed);
    }

    Future<bool> wait(Duration delay, {bool wakeOnForeground = false}) {
      if (cancellation.isCancelled) return Future<bool>.value(false);
      final completion = Completer<bool>();
      waiting = completion;
      canWake = wakeOnForeground;
      timer = Timer(delay, () {
        timer = null;
        if (!ref.read(generationInBackgroundProvider)) {
          finishWaiting();
        }
      });
      return completion.future;
    }

    ref.listen(generationInBackgroundProvider, (previous, background) {
      // A server backoff can elapse in the background, but only an ordinary
      // status wait may be interrupted before its timer expires.
      if (previous == true &&
          !background &&
          waiting != null &&
          (canWake || timer == null)) {
        finishWaiting(resumed: canWake);
      }
    });
    ref.onDispose(() {
      cancellation.cancel();
      finishWaiting();
    });
    return pollBookJob(
      jobId: jobId,
      fetch: () async {
        final status = await api.getBookStatus(
          jobId,
          cancelToken: cancellation,
        );
        if (!cancellation.isCancelled && status.isFailed) {
          ref.invalidate(activeBookGenerationsProvider);
        }
        if (!cancellation.isCancelled &&
            status.creditRefundStatus == 'refunded') {
          ref.invalidate(generationOptionsProvider);
        }
        return status;
      },
      cancelled: () => cancellation.isCancelled,
      cancelFetch: () => cancellation.cancel(),
      wait: (delay) async {
        await wait(delay);
      },
      waitBetweenReads: (delay) => wait(delay, wakeOnForeground: true),
      timeout: kJobPollingHardTimeout,
    );
  },
);

/// 책 생성 Notifier
final bookCreationProvider = AsyncNotifierProvider<BookCreationNotifier, void>(
  BookCreationNotifier.new,
);

// H18: 오늘의 동화 생성 시도-단위 멱등키(HomeScreen이 stateless라 provider로 보유).
// 재시도 시 재사용, 성공 시 null로 리셋.
final todayAttemptKeyProvider = StateProvider<String?>((ref) => null);

/// #20: 오늘의 동화 멱등키가 '어느 날짜의 생성'인지 함께 보관한다. 날짜 서명 없이
/// '??='만 쓰면 어제 실패한 키가 오늘 재사용돼 서버가 어제 잡을 그대로 돌려준다
/// (오늘의 동화가 조용히 생성되지 않음). 재시도용 요청 연령도 함께 보관한다.
final todayAttemptSigProvider = StateProvider<String?>((ref) => null);

class BookCreationNotifier extends AsyncNotifier<void> {
  static const _uuid = Uuid();
  // H18: 시도-단위 멱등키. 타임아웃 후 같은 spec 재시도에선 같은 키를 재사용해 서버가 dedup
  // (이중 생성·크레딧 이중차감 방지). 성공 시 리셋, spec이 바뀌면 새 키.
  String? _attemptKey;
  String? _attemptSig;

  @override
  Future<void> build() async {}

  Future<String> createBook(BookSpec spec) async {
    final api = ref.read(apiClientProvider);

    // 더블탭 창 축소를 위해 상태를 먼저 loading으로.
    state = const AsyncValue.loading();

    final sig = jsonEncode(spec.toJson());
    if (_attemptKey == null || _attemptSig != sig) {
      _attemptKey = _uuid.v4();
      _attemptSig = sig;
    }

    try {
      final attemptKey = _attemptKey!;
      CreateBookResponse response;
      try {
        response = await api.createBook(spec, idempotencyKey: attemptKey);
      } on DioException catch (error) {
        // A lost transport response does not mean the server rejected the book.
        // Reconcile once with the same key; explicit server refusals stay final.
        final lostResponse = const {
          DioExceptionType.connectionTimeout,
          DioExceptionType.sendTimeout,
          DioExceptionType.receiveTimeout,
          DioExceptionType.connectionError,
        }.contains(error.type);
        if (error.response != null ||
            !lostResponse ||
            !identical(api, ref.read(apiClientProvider))) {
          rethrow;
        }
        response = await api.createBook(spec, idempotencyKey: attemptKey);
      }
      ref.invalidate(generationOptionsProvider);
      ref.invalidate(activeBookGenerationsProvider);

      // 성공 → 다음 생성은 새 키.
      _attemptKey = null;
      _attemptSig = null;

      // 현재 Job 상태 초기화
      ref.read(currentJobProvider.notifier).state = JobStatus(
        jobId: response.jobId,
        status: JobState.queued,
        progress: 0,
      );

      state = const AsyncValue.data(null);
      return response.jobId;
    } catch (e, st) {
      // 키 유지 → 같은 spec 재시도 시 재사용.
      state = AsyncValue.error(e, st);
      rethrow;
    }
  }
}

// ==================== Book Viewer Provider ====================

/// 책 상세 조회 Provider
final AutoDisposeFutureProviderFamily<BookResult, String>
bookDetailProvider = FutureProvider.autoDispose.family<BookResult, String>((
  ref,
  bookId,
) async {
  final api = ref.watch(apiClientProvider);
  final prefs = ref.read(sharedPreferencesProvider);
  final user = ref.read(userServiceProvider);
  final profileId = user.getActiveProfileId();
  final profile = bookMediaProfileDigest(profileId);
  final baseUrl = ref.watch(apiBaseUrlProvider);
  final credential = user.getUserKey();
  final localScope = _localBookMediaScope(baseUrl, credential);
  final binding = _bookMediaBinding(baseUrl, credential);
  var active = true;
  ref.onDispose(() => active = false);

  bool cleanupPending() =>
      prefs.getBool(localMediaCleanupPendingKey) == true ||
      prefs.getBool(UserService.deletionRequestedKey) == true ||
      prefs.getBool(UserService.deletionCommittedKey) == true;
  String accountScope() {
    final serverScope = prefs.getString(binding);
    if (serverScope == null) return localScope;
    return prefs.getString(_bookMediaAlias(baseUrl, serverScope)) ?? localScope;
  }

  void requireReadable([String? verifiedScope]) {
    if (!active) throw StateError('Profile changed during book lookup');
    if (cleanupPending()) throw StateError('Local media cleanup is pending');
    if (user.getActiveProfileId() != profileId ||
        user.getUserKey() != credential) {
      throw StateError('Account or profile changed during book lookup');
    }
    final account = accountScope();
    final scope = _profileMediaScope(account, profile);
    if (BookMediaStore.isBookBlocked(prefs, scope, bookId) ||
        (verifiedScope != null &&
            verifiedScope != scope &&
            BookMediaStore.isBookBlocked(prefs, verifiedScope, bookId)) ||
        BookMediaStore.isLegacyBookBlockedForProfile(
          prefs,
          localScope,
          bookId,
          profile,
        ) ||
        (account != localScope &&
            BookMediaStore.isLegacyBookBlockedForProfile(
              prefs,
              account,
              bookId,
              profile,
            ))) {
      throw StateError('Book deletion requires confirmation');
    }
  }

  requireReadable();
  final mediaSetup = ref.watch(bookMediaStoreProvider.future);
  // Fetch authenticated detail while media scope initializes. Hold both
  // success and error until local access and cache scope are established.
  final detail = AsyncValue.guard(() => api.getBook(bookId));
  var mediaScopeConflict = false;
  BookMediaContext? media;
  try {
    media = await mediaSetup;
  } on BookMediaScopeConflict {
    // A missing or changed scope restricts the new media feature, not the
    // existing authenticated book text and reading flow.
    mediaScopeConflict = true;
  }
  final scope = media?.store.scopeDigest ?? accountScope();
  requireReadable(scope);
  final cacheKey = scopedBookCacheKey(scope, profile, bookId);

  try {
    final book = (await detail).requireValue;
    requireReadable(scope);
    if (!mediaScopeConflict) {
      await prefs.setString(cacheKey, jsonEncode(book.toJson()));
    }
    requireReadable(scope);
    return book;
  } catch (error) {
    requireReadable(scope);
    final apiError = error is ApiError
        ? error
        : error is DioException
        ? ApiError.fromDioException(error)
        : null;
    // Keep the scoped copy during outages. A 503 with a domain error
    // (for example PRIVACY_RECORD_UNAVAILABLE) must still fail closed.
    final temporaryFailure = switch ((apiError?.statusCode, apiError?.code)) {
      (0, 'CONNECTION_ERROR' || 'NETWORK_ERROR' || 'TIMEOUT') ||
      (502, 'BAD_GATEWAY') ||
      (503, 'SERVICE_UNAVAILABLE') ||
      (504, 'GATEWAY_TIMEOUT') => true,
      _ => false,
    };
    if (!temporaryFailure) {
      await prefs.remove(cacheKey);
      rethrow;
    }
    if (mediaScopeConflict) rethrow;
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
