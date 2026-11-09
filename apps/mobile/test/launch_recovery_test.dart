import 'dart:async';
import 'dart:io';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/settings_screen.dart';
import 'package:ai_story_book/screens/account_deletion_screen.dart';
import 'package:ai_story_book/screens/voice_profiles_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/book_cleanup_plan_journal.dart';
import 'package:ai_story_book/services/book_media_registry.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:ai_story_book/services/user_service.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _MemoryCleanupPlan extends BookCleanupPlanJournal {
  _MemoryCleanupPlan() : super(baseDirectory: () async => Directory.systemTemp);
  String? value;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String plan) async {
    value = plan;
  }

  @override
  Future<void> clear() async {
    value = null;
  }
}

class _MemoryRegistry extends BookMediaRegistry {
  _MemoryRegistry(super.preferences)
    : super(baseDirectory: () async => Directory.systemTemp);
  @override
  Future<bool> hasScopeData(String scope) async => false;
  @override
  Future<void> purgeScopes(
    Set<String> scopes, {
    bool eraseJournal = false,
  }) async {}
}

class _EmptyCharacters extends CharactersNotifier {
  @override
  Future<List<Character>> build() async => [];
}

class _VerifiedParent extends ParentalControlService {
  _VerifiedParent() {
    markAgeGateVerified();
  }
  @override
  Future<void> loadAgeGateSession(SharedPreferences prefs) async {}
}

class _RecoveryApi extends ApiClient {
  _RecoveryApi() : super(baseUrl: 'http://test', userKey: 'test-user-key');

  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor, BookStyle.cartoon]);

  bool settingsFail = false;
  int settingsReads = 0;
  int settingsWrites = 0;
  int creates = 0;
  BookSpec? lastBookSpec;
  int revocations = 0;
  bool? consentPurgeIncomplete;
  bool purgePending = false;
  int accountDeletions = 0;
  Completer<void>? deletionGate;
  Completer<void>? creationGate;
  List<Map<String, dynamic>> voiceProfiles = [];

  @override
  Future<Map<String, dynamic>> getSettings() async {
    settingsReads++;
    if (settingsFail) throw StateError('settings unavailable');
    return {'dark_mode': true, 'language': 'ko'};
  }

  @override
  Future<void> patchSettings(Map<String, dynamic> data) async {
    settingsWrites++;
  }

  @override
  Future<Map<String, dynamic>> revokeConsent() async => {
    if (consentPurgeIncomplete != null)
      'purge_incomplete': consentPurgeIncomplete,
  };

  @override
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    creates++;
    lastBookSpec = spec;
    await creationGate?.future;
    return CreateBookResponse(jobId: 'one-job', status: 'queued');
  }

  @override
  Future<Map<String, dynamic>> getVoiceProfiles() async => {
    'profiles': voiceProfiles,
  };

  @override
  Future<Map<String, dynamic>> revokeVoiceProfileConsent(String id) async {
    revocations++;
    if (purgePending) {
      voiceProfiles = [];
      throw const StoragePurgePending();
    }
    return {'id': id};
  }

  @override
  Future<void> deleteVoiceProfile(String id) async {
    voiceProfiles = [];
    if (purgePending) throw const StoragePurgePending();
  }

  @override
  Future<void> deleteMyData() async {
    accountDeletions++;
    await deletionGate?.future;
    if (purgePending) throw const StoragePurgePending();
  }
}

class _LibraryApi extends ApiClient {
  _LibraryApi() : super(baseUrl: 'http://test', userKey: 'test-user-key');
  bool deletionFails = false;
  bool purgePending = false;
  @override
  Future<String> getAccountMediaScope() async => 'a' * 64;

  @override
  Future<Map<String, dynamic>> deleteBookWithReceipt(
    String bookId,
    String requestId,
  ) async {
    try {
      await deleteBook(bookId);
    } on StoragePurgePending {
      return {'deletion_committed': true, 'purge_retry_pending': true};
    }
    return {'deletion_committed': true, 'purge_retry_pending': false};
  }

  List<LibraryBook> books = [
    LibraryBook(
      id: 'book-1',
      title: 'Original title',
      coverImageUrl: '',
      targetAge: '5-7',
      style: 'watercolor',
      createdAt: DateTime(2026),
    ),
  ];

  @override
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
    String? cursor,
    String sort = 'newest',
    String? style,
    String? targetAge,
  }) async => LibraryResponse(
    books: books,
    total: books.length,
    nextCursor: null,
    hasMore: false,
  );

  @override
  Future<void> deleteBook(String bookId) async {
    if (deletionFails) throw StateError('offline');
    books = [];
    if (purgePending) throw const StoragePurgePending();
  }

  @override
  Future<BookResult> getBook(String bookId) async => throw ApiError(
    code: 'NOT_FOUND',
    message: 'Book unavailable',
    statusCode: 404,
  );

  @override
  Future<LibraryBook> updateBookTitle(String bookId, String title) async {
    final old = books.single;
    final updated = LibraryBook(
      id: bookId,
      title: title,
      coverImageUrl: old.coverImageUrl,
      targetAge: old.targetAge,
      style: old.style,
      createdAt: old.createdAt,
    );
    books = [updated];
    return updated;
  }
}

class _DelayedRenameApi extends _LibraryApi {
  final started = Completer<void>();
  final response = Completer<LibraryBook>();

  @override
  Future<LibraryBook> updateBookTitle(String bookId, String title) {
    started.complete();
    return response.future;
  }
}

Future<void> _pump(
  WidgetTester tester,
  Widget screen,
  _RecoveryApi api, {
  bool audioSupported = false,
  List<Override> overrides = const [],
  double scale = 1,
  Locale locale = const Locale('ko'),
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  UserService.resetCacheForTest();
  FlutterSecureStorage.setMockInitialValues({
    'user_key': '11111111-2222-4333-8444-555555555555',
  });
  await UserService.bootstrapUserKey(prefs);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        localMediaCachePurgerProvider.overrideWithValue(() async {}),
        bookMediaRegistryProvider.overrideWithValue(_MemoryRegistry(prefs)),
        bookCleanupPlanJournalProvider.overrideWithValue(_MemoryCleanupPlan()),
        apiClientProvider.overrideWithValue(api),
        capabilitiesProvider.overrideWith(
          (ref) async => {
            'audio_supported': audioSupported,
            'pod_ordering_supported': false,
          },
        ),
        charactersProvider.overrideWith(_EmptyCharacters.new),
        ...overrides,
      ],
      child: MaterialApp(
        locale: locale,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
        home: screen,
        onGenerateRoute: (settings) => MaterialPageRoute<void>(
          builder: (_) => Scaffold(body: Text('route:${settings.name}')),
        ),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  for (final status in [true, false, null]) {
    testWidgets('consent revocation reports file status $status', (
      tester,
    ) async {
      final api = _RecoveryApi()..consentPurgeIncomplete = status;
      await _pump(
        tester,
        const SettingsScreen(),
        api,
        overrides: [
          parentalControlServiceProvider.overrideWithValue(_VerifiedParent()),
        ],
      );
      final l = AppLocalizations.of(
        tester.element(find.byType(SettingsScreen)),
      );
      await tester.scrollUntilVisible(
        find.text(l.settingsRevokeParentalConsent),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text(l.settingsRevokeParentalConsent));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, l.settingsRevoke));
      await tester.pumpAndSettle();
      expect(find.text('route:/consent'), findsOneWidget);
      expect(
        find.text(
          status == false
              ? l.settingsConsentRevoked
              : l.consentDeletionUnconfirmed,
        ),
        findsOneWidget,
      );
    });
  }

  testWidgets('generation submits once while the server response is pending', (
    tester,
  ) async {
    final api = _RecoveryApi()..creationGate = Completer<void>();
    await _pump(tester, const CreateScreen(), api);
    await tester.enterText(find.byType(TextFormField).first, '우주를 여행하는 토끼');
    await tester.ensureVisible(find.byType(PrimaryButton));
    final button = tester.widget<PrimaryButton>(find.byType(PrimaryButton));
    // A second callback can arrive before Flutter rebuilds the disabled button.
    button.onPressed!();
    button.onPressed!();
    await tester.pump();
    expect(api.creates, 1);
    api.creationGate!.complete();
    await tester.pumpAndSettle();
    expect(api.creates, 1);
    expect(api.lastBookSpec?.pageCount, 12);
    expect(find.text('route:/loading'), findsOneWidget);
  });

  for (final locale in const [Locale('ko'), Locale('en'), Locale('ja')]) {
    testWidgets(
      'short story selection submits eight pages in ${locale.languageCode}',
      (tester) async {
        tester.view.physicalSize = const Size(320, 480);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = _RecoveryApi();
        await _pump(
          tester,
          const CreateScreen(),
          api,
          scale: 1.4,
          locale: locale,
        );
        final list = find.byType(ListView).first;
        final scrollable = find
            .descendant(of: list, matching: find.byType(Scrollable))
            .first;
        await tester.scrollUntilVisible(
          find.byType(TextFormField),
          150,
          scrollable: scrollable,
        );
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextFormField), '우주를 여행하는 토끼');
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        final standard = find.byKey(const ValueKey('story-length-12'));
        final short = find.byKey(const ValueKey('story-length-8'));
        await tester.scrollUntilVisible(short, 200, scrollable: scrollable);
        await tester.ensureVisible(short);
        await tester.pumpAndSettle();
        expect(tester.widget<ChoiceChip>(standard).selected, isTrue);
        expect(tester.getSize(short).height, greaterThanOrEqualTo(64));
        expect(find.byKey(const ValueKey('story-length-4')), findsNothing);
        await tester.tap(short);
        await tester.pump();
        expect(tester.widget<ChoiceChip>(short).selected, isTrue);
        expect(tester.widget<ChoiceChip>(standard).selected, isFalse);

        await tester.ensureVisible(find.byType(PrimaryButton));
        expect(tester.takeException(), isNull);
        await tester.tap(find.byType(PrimaryButton));
        await tester.pumpAndSettle();
        expect(api.creates, 1);
        expect(api.lastBookSpec?.pageCount, 8);
        expect(api.lastBookSpec?.language, locale.languageCode);
        expect(find.text('route:/loading'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('failed status lookup retries the same job without raw errors', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var reads = 0;
    await _pump(
      tester,
      const LoadingScreen(jobId: 'existing-job'),
      _RecoveryApi(),
      scale: 1.4,
      overrides: [
        jobPollingProvider('existing-job').overrideWith((ref) {
          reads++;
          if (reads == 1) {
            return Stream.error(
              ApiError(
                code: 'CONNECTION_ERROR',
                message: 'private diagnostic text',
                statusCode: 0,
              ),
            );
          }
          return Stream.value(
            JobStatus(
              jobId: 'existing-job',
              status: JobState.running,
              progress: 30,
            ),
          );
        }),
      ],
    );
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.loadingStatusUnavailable), findsOneWidget);
    expect(find.textContaining('private diagnostic'), findsNothing);
    expect(find.text(l.loadingRetryButton), findsNothing);
    await tester.ensureVisible(find.text(l.loadingCheckStatusButton));
    await tester.tap(find.text(l.loadingCheckStatusButton));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(reads, 2);
    expect(find.text(l.loadingStatusUnavailable), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('failed settings load cannot save defaults and offers retry', (
    tester,
  ) async {
    final api = _RecoveryApi()..settingsFail = true;
    await _pump(tester, const SettingsScreen(), api);
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.settingsSave), findsNothing);
    expect(find.byType(SwitchListTile), findsNothing);
    expect(api.settingsWrites, 0);
    api.settingsFail = false;
    await tester.tap(find.text(l.retry));
    await tester.pumpAndSettle();
    expect(api.settingsReads, 2);
    expect(find.text(l.settingsSave), findsOneWidget);
    final dark = tester.widget<SwitchListTile>(
      find.widgetWithText(SwitchListTile, l.settingsDarkMode),
    );
    expect(dark.value, isTrue);
    expect(find.text(l.settingsFamilyVoice), findsNothing);
    await tester.scrollUntilVisible(
      find.text(l.settingsSavedVoices),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text(l.settingsSavedVoices), findsOneWidget);
  });

  testWidgets('completed job with missing result offers status recovery', (
    tester,
  ) async {
    await _pump(
      tester,
      const LoadingScreen(jobId: 'existing-job'),
      _RecoveryApi(),
      overrides: [
        jobPollingProvider('existing-job').overrideWith(
          (ref) => Stream.value(
            JobStatus(
              jobId: 'existing-job',
              status: JobState.done,
              progress: 100,
            ),
          ),
        ),
      ],
    );
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.loadingCheckStatusButton), findsOneWidget);
    expect(find.text(l.loadingTitle), findsNothing);
  });

  testWidgets('disabled voice screen offers no registration', (tester) async {
    await _pump(tester, const VoiceProfilesScreen(), _RecoveryApi());
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.byIcon(Icons.add), findsNothing);
    expect(find.text(l.voiceProfilesUnavailable), findsOneWidget);
  });

  testWidgets('disabled voice screen keeps existing sample revocation', (
    tester,
  ) async {
    final api = _RecoveryApi()
      ..voiceProfiles = [
        {'id': 'voice-1', 'label': '부모님', 'consented': true, 'active': true},
      ];
    await _pump(tester, const VoiceProfilesScreen(), api);
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    expect(find.text(l.voiceProfilesMenuEdit), findsNothing);
    expect(find.text(l.voiceProfilesMenuDelete), findsOneWidget);
    await tester.tap(find.text(l.voiceProfilesMenuRevoke));
    await tester.pumpAndSettle();
    expect(api.revocations, 1);
  });

  for (final action in ['revoke', 'delete']) {
    testWidgets('voice $action explains pending file deletion and refreshes', (
      tester,
    ) async {
      final api = _RecoveryApi()
        ..purgePending = true
        ..voiceProfiles = [
          {'id': 'voice-1', 'label': '부모님', 'consented': true, 'active': true},
        ];
      await _pump(tester, const VoiceProfilesScreen(), api);
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(
        find.text(
          action == 'revoke'
              ? l.voiceProfilesMenuRevoke
              : l.voiceProfilesMenuDelete,
        ),
      );
      await tester.pumpAndSettle();
      if (action == 'delete') {
        await tester.tap(
          find.widgetWithText(FilledButton, l.voiceProfilesDelete),
        );
        await tester.pumpAndSettle();
      }
      expect(find.text('부모님'), findsNothing);
      expect(find.text(l.voiceDeletionPending), findsOneWidget);
      expect(find.text(l.voiceProfilesDeleteError), findsNothing);
      expect(find.text(l.voiceProfilesRevokeError), findsNothing);
    });
  }

  testWidgets(
    'account purge pending clears local data and returns to consent',
    (tester) async {
      FlutterSecureStorage.setMockInitialValues({
        'user_key': '11111111-2222-4333-8444-555555555555',
      });
      final api = _RecoveryApi()..purgePending = true;
      final parent = _VerifiedParent();
      var clearCalls = 0;
      var clearAccountCalls = 0;
      await _pump(
        tester,
        const SettingsScreen(),
        api,
        overrides: [
          parentalControlServiceProvider.overrideWithValue(parent),
          legacyCleanupProvider.overrideWithValue((prefs) async {
            clearCalls++;
            await prefs.remove('book_cache_private_v1');
          }),
          clearLegacyAccountMediaProvider.overrideWithValue(() async {
            clearAccountCalls++;
          }),
        ],
      );
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('book_cache_private_v1', 'private child content');
      await prefs.setString('active_profile_id_v1', 'old-profile');
      final l = await AppLocalizations.delegate.load(const Locale('ko'));
      await tester.scrollUntilVisible(
        find.text(l.settingsDeleteAllData),
        400,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text(l.settingsDeleteAllData));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.settingsContinue));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), l.settingsDeleteKeyword);
      await tester.tap(
        find.widgetWithText(TextButton, l.settingsDeleteKeyword),
      );
      await tester.pumpAndSettle();
      expect(api.accountDeletions, 1);
      expect(prefs.containsKey('book_cache_private_v1'), isTrue);
      expect(prefs.getBool('account_deletion_committed_v1'), isTrue);
      expect(prefs.getBool('local_media_cleanup_pending_v1'), isTrue);
      expect(find.text('route:/consent'), findsNothing);
      expect(find.text(l.settingsDeleteLegacyUnresolved), findsOneWidget);
      await tester.pump(const Duration(seconds: 2));
      expect(api.accountDeletions, 1);
      await tester.tap(find.text(l.accountRetry));
      await tester.pumpAndSettle();
      expect(api.accountDeletions, 1);
      expect(find.text(l.settingsDeleteLegacyUnresolved), findsOneWidget);
      await tester.tap(find.text(l.legacyAccountCleanupAction));
      await tester.pumpAndSettle();
      expect(find.text(l.legacyAccountCleanupWarning), findsOneWidget);
      await tester.tap(find.text(l.legacyCleanupCancel));
      await tester.pumpAndSettle();
      expect(clearAccountCalls, 0);
      await tester.tap(find.text(l.legacyAccountCleanupAction));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.legacyCleanupConfirm));
      await tester.pumpAndSettle();
      expect(clearAccountCalls, 1);
      expect(api.accountDeletions, 1);
      await tester.tap(find.text(l.legacyCleanupAction));
      await tester.pumpAndSettle();
      expect(find.text(l.legacyCleanupWarning), findsOneWidget);
      await tester.tap(find.text(l.legacyCleanupCancel));
      await tester.pumpAndSettle();
      expect(clearCalls, 0);
      expect(prefs.containsKey('book_cache_private_v1'), isTrue);
      await tester.tap(find.text(l.legacyCleanupAction));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.legacyCleanupConfirm));
      await tester.pumpAndSettle();
      expect(clearCalls, 1);
      expect(api.accountDeletions, 1);
      expect(find.text('route:/consent'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('committed deletion clears the account after leaving Settings', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues({
      'user_key': '11111111-2222-4333-8444-555555555555',
    });
    final gate = Completer<void>();
    final api = _RecoveryApi()..deletionGate = gate;
    final parent = _VerifiedParent();
    await _pump(
      tester,
      const SettingsScreen(),
      api,
      overrides: [parentalControlServiceProvider.overrideWithValue(parent)],
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('book_cache_private_v1', 'private child content');
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await tester.scrollUntilVisible(
      find.text(l.settingsDeleteAllData),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text(l.settingsDeleteAllData));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.settingsContinue));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), l.settingsDeleteKeyword);
    await tester.tap(find.widgetWithText(TextButton, l.settingsDeleteKeyword));
    await tester.pump();
    Navigator.of(
      tester.element(find.byType(SettingsScreen)),
    ).pushReplacementNamed('/library');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(SettingsScreen), findsNothing);
    gate.complete();
    await tester.pumpAndSettle();
    expect(api.accountDeletions, 1);
    expect(prefs.containsKey('book_cache_private_v1'), true);
    expect(prefs.getBool('account_deletion_committed_v1'), isTrue);
    expect(prefs.getBool('local_media_cleanup_pending_v1'), isTrue);
    expect(find.text('route:/library'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test(
    'late rename result cannot replace a switched profile library',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      UserService.resetCacheForTest();
      FlutterSecureStorage.setMockInitialValues({
        'user_key': '11111111-2222-4333-8444-555555555555',
      });
      await UserService.bootstrapUserKey(prefs);
      final directory = await Directory.systemTemp.createTemp(
        'asb-rename-race-',
      );
      final first = _DelayedRenameApi();
      final second = _LibraryApi();
      final selected = StateProvider<bool>((ref) => false);
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWith(
            (ref) => ref.watch(selected) ? second : first,
          ),
          bookMediaRegistryProvider.overrideWithValue(
            BookMediaRegistry(prefs, baseDirectory: () async => directory),
          ),
        ],
      );
      addTearDown(container.dispose);
      addTearDown(() async => directory.delete(recursive: true));
      await container.read(libraryBrowseProvider.future);
      final rename = container
          .read(libraryBrowseProvider.notifier)
          .renameBook('book-1', 'First profile title');
      await first.started.future;
      container.read(selected.notifier).state = true;
      container.invalidate(libraryBrowseProvider);
      await container.read(libraryBrowseProvider.future);
      first.response.complete(
        LibraryBook(
          id: 'book-1',
          title: 'First profile title',
          coverImageUrl: '',
          targetAge: '5-7',
          style: 'watercolor',
          createdAt: DateTime(2026),
        ),
      );
      await rename;
      expect(
        container.read(libraryBrowseProvider).requireValue.books.single.title,
        'Original title',
      );
    },
  );

  for (final action in [
    'delete',
    'pending-delete',
    'rename',
    'failed-delete',
  ]) {
    test('library $action synchronizes home and cached detail', () async {
      SharedPreferences.setMockInitialValues({
        'book_cache_book-1_v1': 'cached book content',
        'reading_progress_book-1_v1': 2,
        'reading_progress_audio_book-1_v1': 'saved audio position',
        'reading_progress_other_v1': 3,
      });
      final prefs = await SharedPreferences.getInstance();
      UserService.resetCacheForTest();
      FlutterSecureStorage.setMockInitialValues({
        'user_key': '11111111-2222-4333-8444-555555555555',
      });
      await UserService.bootstrapUserKey(prefs);
      final directory = await Directory.systemTemp.createTemp(
        'asb-launch-test-',
      );
      final api = _LibraryApi()
        ..deletionFails = action == 'failed-delete'
        ..purgePending = action == 'pending-delete';
      final container = ProviderContainer(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          localMediaCachePurgerProvider.overrideWithValue(() async {}),
          apiClientProvider.overrideWithValue(api),
          bookMediaRegistryProvider.overrideWithValue(
            BookMediaRegistry(prefs, baseDirectory: () async => directory),
          ),
        ],
      );
      addTearDown(container.dispose);
      addTearDown(() async => directory.delete(recursive: true));
      await container.read(libraryProvider.future);
      await container.read(libraryBrowseProvider.future);
      final notifier = container.read(libraryBrowseProvider.notifier);
      if (action == 'failed-delete') {
        await expectLater(
          notifier.deleteBook('book-1'),
          throwsA(isA<BookDeletionUnconfirmed>()),
        );
        expect(prefs.containsKey('book_cache_book-1_v1'), isTrue);
        expect(prefs.containsKey('reading_progress_book-1_v1'), isTrue);
        expect((await container.read(libraryProvider.future)).length, 1);
      } else if (action == 'delete' || action == 'pending-delete') {
        final pending = await notifier.deleteBook('book-1');
        // Historical shared cache cannot be attributed to a book, so even a
        // completed server delete must retain the local purge caveat.
        expect(pending, isTrue);
        expect(prefs.containsKey('book_cache_book-1_v1'), isTrue);
        expect(prefs.containsKey('reading_progress_book-1_v1'), isTrue);
        expect(prefs.containsKey('reading_progress_audio_book-1_v1'), isTrue);
        expect(prefs.getInt('reading_progress_other_v1'), 3);
        expect(await container.read(libraryProvider.future), isEmpty);
        expect(
          container.read(libraryBrowseProvider).requireValue.books,
          isEmpty,
        );
      } else {
        await notifier.renameBook('book-1', 'New title');
        expect(prefs.containsKey('book_cache_book-1_v1'), isTrue);
        expect(prefs.containsKey('reading_progress_book-1_v1'), isTrue);
        expect(
          (await container.read(libraryProvider.future)).single.title,
          'New title',
        );
      }
    });
  }
}
