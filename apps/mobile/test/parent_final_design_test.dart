import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/credits_screen.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/screens/onboarding_screen.dart';
import 'package:ai_story_book/screens/account_recovery_screen.dart';
import 'package:ai_story_book/services/public_links.dart';
import 'support/design_capture.dart';
import 'package:ai_story_book/screens/parent_dashboard_screen.dart';
import 'package:ai_story_book/screens/pod_order_screen.dart';
import 'package:ai_story_book/screens/profiles_screen.dart';
import 'package:ai_story_book/screens/settings_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/utils/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://localhost', userKey: 'design-test');
  bool fail = false;
  int reportCalls = 0;
  int creditsCalls = 0;
  int saved = 0;
  String periodEnd = '2026-10-06';
  List<Map<String, dynamic>> transactions = [];
  List<Map<String, dynamic>> profiles = [];
  Map<String, dynamic>? createdProfile;
  @override
  Future<Map<String, dynamic>> getReadingReport(
      {String period = 'weekly'}) async {
    reportCalls++;
    if (fail) throw Exception('offline');
    return {
      'total_books_read': 125,
      'total_reading_minutes': 325,
      'average_reading_minutes': 15.4,
      'preferred_theme': '동물 친구들과 함께하는 마음 다독이기',
      'daily_breakdown': List.generate(
          period == 'monthly' ? 30 : 7,
          (i) => {
                'date': '2026-09-${(i + 1).toString().padLeft(2, '0')}',
                'minutes': i
              }),
    };
  }

  @override
  Future<Map<String, dynamic>> getCreditsStatus() async {
    creditsCalls++;
    if (fail) throw Exception('offline');
    return {
      'credits': {'credits': 1250, 'total_used': 23},
      'subscription': {
        'plan': 'premium',
        'plan_name': '프리미엄 가족 독서',
        'status': 'active',
        'credits_per_month': 100,
        'current_period_end': periodEnd,
        'features': ['매일 함께하는 동화 읽기'],
      }
    };
  }

  @override
  Future<List<dynamic>> getTransactions(
          {int limit = 20, int offset = 0}) async =>
      transactions;
  @override
  Future<Map<String, dynamic>> getProfiles() async {
    if (fail) throw Exception('offline');
    return {'profiles': profiles};
  }

  @override
  Future<Map<String, dynamic>> createProfile(
      {required String name,
      required String ageBand,
      int? birthYear,
      int? birthMonth,
      bool? isDefault,
      String? preferredTheme}) async {
    createdProfile = {
      'id': 'test-profile',
      'name': name,
      'age_band': ageBand,
      'is_default': true
    };
    profiles = [createdProfile!];
    return createdProfile!;
  }

  @override
  Future<Map<String, dynamic>> getSettings() async => {'dark_mode': false};
  @override
  Future<Map<String, dynamic>> patchSettings(
      Map<String, dynamic> values) async {
    saved++;
    return values;
  }

  @override
  Future<Map<String, dynamic>> getPodQuote(
          {String country = 'KR', int quantity = 1}) async =>
      {'total_price': 123456, 'currency': 'KRW'};
}

Future<void> _pump(WidgetTester tester, Widget screen, _Api api,
    {Brightness brightness = Brightness.light,
    Size size = const Size(320, 480),
    double scale = 1.4,
    Future<Map<String, dynamic>> Function()? caps,
    List<Override> overrides = const []}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  SharedPreferences.setMockInitialValues(
      {'active_profile_id_v1': 'test-profile'});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(designCaptureBoundary(ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        ...overrides,
        apiClientProvider.overrideWithValue(api),
        capabilitiesProvider.overrideWith((ref) =>
            caps?.call() ??
            Future.value({
              'audio_supported': false,
              'pod_ordering_supported': true,
              'purchases_supported': false,
            })),
      ],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(brightness),
        locale: const Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(scale)),
            child: child!),
        home: screen,
      ))));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 250));
}

void main() {
  setUpAll(loadDesignFonts);
  for (final brightness in Brightness.values) {
    testWidgets(
        'reading report adapts cards and 30-day chart at 320px $brightness',
        (tester) async {
      await _pump(tester, const ParentDashboardScreen(), _Api(),
          brightness: brightness);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('월간'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('일별 읽기 시간'), 200,
          scrollable: find.byType(Scrollable).first);
      await tester.pumpAndSettle();
      final chart = find.byWidgetPredicate((widget) =>
          widget is SingleChildScrollView &&
          widget.scrollDirection == Axis.horizontal);
      await tester.ensureVisible(chart);
      await tester.drag(chart, const Offset(-1800, 0));
      await tester.pumpAndSettle();
      expect(find.text('09-30').hitTestable(), findsOneWidget);
      await captureDesign(tester, 'parent-report-chart-$brightness');
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('report error has direct retry and restores useful content',
      (tester) async {
    final api = _Api()..fail = true;
    await _pump(tester, const ParentDashboardScreen(), api);
    await tester.pumpAndSettle();
    api.fail = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(api.reportCalls, 2);
    expect(find.text('주간 리포트'), findsOneWidget);
  });
  testWidgets(
      'credits load failure does not show an invented zero balance and retries',
      (tester) async {
    final api = _Api()..fail = true;
    await _pump(tester, const CreditsScreen(), api);
    await tester.pumpAndSettle();
    expect(find.text('0'), findsNothing);
    api.fail = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(api.creditsCalls, 2);
    await tester.scrollUntilVisible(find.text('다음 갱신일'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'credits UTC timestamps render in device time including renewal date',
      (tester) async {
    // In Asia/Seoul the server timestamp is on the previous UTC day.
    final timestamp = DateTime(2026, 9, 7, 3, 5).toUtc().toIso8601String();
    final api = _Api()
      ..periodEnd = timestamp
      ..transactions = [
        {'amount': 10, 'description': '충전 내역', 'created_at': timestamp}
      ];
    await _pump(tester, const CreditsScreen(), api);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('2026.9.7'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('2026.9.7').hitTestable(), findsOneWidget);
    await tester.scrollUntilVisible(find.text('2026.9.7 3:05'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('2026.9.7 3:05').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('credits preserve local timestamps and date-only renewals',
      (tester) async {
    final api = _Api()
      ..periodEnd = '2026-10-06'
      ..transactions = [
        {
          'amount': 10,
          'description': '충전 내역',
          'created_at': '2026-09-07T03:05:00'
        }
      ];
    await _pump(tester, const CreditsScreen(), api);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('2026.10.6'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('2026.10.6').hitTestable(), findsOneWidget);
    await tester.scrollUntilVisible(find.text('2026.9.7 3:05'), 150,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('2026.9.7 3:05').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'profile load failure offers retry instead of creating a duplicate',
      (tester) async {
    final api = _Api()..fail = true;
    await _pump(tester, const ProfilesScreen(), api);
    await tester.pumpAndSettle();
    expect(find.text('첫 프로필 만들기'), findsNothing);
    api.fail = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(find.text('첫 프로필 만들기'), findsOneWidget);
  });
  testWidgets('profile form submission and cancel do not dispose a live input',
      (tester) async {
    final api = _Api();
    await _pump(tester, const ProfilesScreen(), api);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('프로필 추가'));
    await tester.pumpAndSettle();
    await captureDesign(tester, 'parent-profile-dialog');
    await tester.enterText(find.byType(TextFormField), '시우');
    await tester.tap(find.text('추가'));
    await tester.pumpAndSettle();
    expect(api.createdProfile?['name'], '시우');
    await captureDesign(tester, 'parent-profile-created');
    expect(tester.takeException(), isNull);
    await tester.tap(find.byTooltip('프로필 추가'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), '취소할 이름');
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('settings keeps save visible and hides unsupported reading timer',
      (tester) async {
    final api = _Api();
    await _pump(tester, const SettingsScreen(), api);
    await tester.pumpAndSettle();
    final save = find.byKey(const ValueKey('settings-save'));
    expect(tester.getSize(save).height, greaterThanOrEqualTo(64));
    await tester.drag(find.byType(ListView), const Offset(0, -2500));
    await tester.pumpAndSettle();
    expect(save.hitTestable(), findsOneWidget);
    await captureDesign(tester, 'parent-settings-bottom');
    expect(find.textContaining('기본 수면 타이머'), findsNothing);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.saved, 1);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'print ordering waits for capabilities and recovers loading errors',
      (tester) async {
    final caps = Completer<Map<String, dynamic>>();
    var calls = 0;
    await _pump(
        tester,
        const PodOrderScreen(bookId: 'book-test', bookTitle: '시우의 동화'),
        _Api(), caps: () {
      calls++;
      return calls == 1
          ? caps.future
          : Future.value({'pod_ordering_supported': false});
    });
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    caps.completeError(Exception('offline'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.byType(TextFormField), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'print quantity and quote stay readable and final action reachable',
      (tester) async {
    await _pump(tester,
        const PodOrderScreen(bookId: 'book-test', bookTitle: '시우의 동화'), _Api());
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('주문하기'), 200,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    expect(find.text('주문하기').hitTestable(), findsOneWidget);
    await captureDesign(tester, 'parent-print-final-action');
    await tester.tap(find.text('주문하기'));
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    expect(find.text(l.podOrderRecipientNameError), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('theme changes apply only after settings save succeeds',
      (tester) async {
    final api = _Api();
    await _pump(tester, const SettingsScreen(), api);
    await tester.pumpAndSettle();
    final container =
        ProviderScope.containerOf(tester.element(find.byType(SettingsScreen)));
    await tester.scrollUntilVisible(find.text('다크 모드'), 150,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    expect(find.text('다크 모드').hitTestable(), findsOneWidget);
    await tester.tap(find.text('다크 모드'));
    await tester.pumpAndSettle();
    expect(container.read(appThemeModeProvider), ThemeMode.light);
    expect(
        tester
            .widget<SwitchListTile>(
                find.widgetWithText(SwitchListTile, '다크 모드'))
            .value,
        isTrue);
    await tester.tap(find.byKey(const ValueKey('settings-save')));
    await tester.pumpAndSettle();
    expect(api.saved, 1);
    expect(container.read(appThemeModeProvider), ThemeMode.dark);
  });

  testWidgets('public policy page uses injected HTTPS link and launcher',
      (tester) async {
    Uri? opened;
    final links = PublicLinks(
        privacyPolicyUrl: 'https://storybook.pages.dev/privacy',
        launch: (uri) async {
          opened = uri;
          return true;
        });
    await _pump(tester, const SettingsScreen(), _Api(),
        overrides: [publicLinksProvider.overrideWithValue(links)]);
    await tester.pumpAndSettle();
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await tester.scrollUntilVisible(find.text(l.settingsPrivacyPolicy), 150,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text(l.settingsPrivacyPolicy));
    await tester.pumpAndSettle();
    expect(opened.toString(), 'https://storybook.pages.dev/privacy');
  });

  for (final size in [const Size(402, 874), const Size(800, 1000)]) {
    testWidgets(
        'profile modal intrinsic layout and save at $size with default text',
        (tester) async {
      final api = _Api();
      await _pump(tester, const ProfilesScreen(), api, size: size, scale: 1);
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('프로필 추가'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await captureDesign(
          tester, 'parent-profile-dialog-${size.width.toInt()}');
      await tester.enterText(find.byType(TextFormField), '시우');
      await tester.tap(find.text('추가'));
      await tester.pumpAndSettle();
      expect(api.createdProfile?['name'], '시우');
      expect(tester.takeException(), isNull);
    });
  }

  for (final entry in <String, Widget>{
    'onboarding': const OnboardingScreen(),
    'consent': const ConsentScreen(),
    'recovery': const AccountRecoveryScreen(restoreOnly: true),
    'settings': const SettingsScreen(),
    'profiles': const ProfilesScreen(),
    'credits': const CreditsScreen(),
    'report': const ParentDashboardScreen(),
    'print': const PodOrderScreen(bookId: 'book-test', bookTitle: '시우의 동화'),
  }.entries) {
    for (final brightness in Brightness.values) {
      testWidgets('final ${entry.key} screen at short large text $brightness',
          (tester) async {
        await _pump(tester, entry.value, _Api(), brightness: brightness);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await captureDesign(tester, 'parent-${entry.key}-${brightness.name}');
      });
    }
  }
}
