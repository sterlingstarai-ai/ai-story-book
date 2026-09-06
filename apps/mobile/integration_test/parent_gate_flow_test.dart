import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/viewer_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/widgets/content_report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _bookId = 'parent-gate-native-regression-book';
const _preferencesMarker = 'parent_gate_native_regression_only';

class _OfflineReaderApi extends ApiClient {
  _OfflineReaderApi()
      : super(
          baseUrl: 'http://127.0.0.1',
          userKey: 'parent-gate-native-regression',
          enableLogging: false,
        ) {
    // An unexpected, non-overridden API call cannot leave the test process.
    close();
  }

  @override
  Future<Map<String, dynamic>> getSettings() async =>
      {'allow_kakao_share': false};

  @override
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async =>
      {};
}

BookResult _book() => BookResult(
      bookId: _bookId,
      title: '보호자 확인 테스트 동화',
      // Empty media paths exercise the reader's local fallback without a URL.
      coverImageUrl: '',
      pages: [
        PageResult(pageNumber: 1, text: '첫 번째 이야기예요.', imageUrl: ''),
        PageResult(pageNumber: 2, text: '두 번째 이야기예요.', imageUrl: ''),
      ],
    );

Future<void> _finishTransition(WidgetTester tester) async {
  // Pump intermediate route frames too: the original crash occurred while the
  // completed dialog was reversing and the report sheet was already opening.
  for (var frame = 0; frame < 8; frame++) {
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.takeException(), isNull);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('fresh parent check opens the report sheet on a native reader',
      (tester) async {
    // This replaces the preference plugin with isolated memory for this test
    // process. Production bootstrap and secure account storage are never used.
    SharedPreferences.setMockInitialValues({_preferencesMarker: true});
    final prefs = await SharedPreferences.getInstance();
    final parental = ParentalControlService();
    final api = _OfflineReaderApi();
    final container = ProviderContainer(overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      parentalControlServiceProvider.overrideWithValue(parental),
      apiClientProvider.overrideWithValue(api),
      bookDetailProvider(_bookId).overrideWith((ref) async => _book()),
      capabilitiesProvider.overrideWith((ref) async => {
            'audio_supported': false,
            'pod_enabled': false,
            'inpaint_supported': false,
          }),
    ]);
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 4));
      container.dispose();
    });

    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(
        locale: Locale('ko'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: ViewerScreen(bookId: _bookId),
      ),
    ));
    await _finishTransition(tester);
    final l = AppLocalizations.of(tester.element(find.byType(ViewerScreen)));
    expect(parental.isAgeGateVerifiedForSession, isFalse);
    expect(prefs.getInt(ParentalControlService.ageGateSessionKey), isNull);

    await tester.tap(find.byTooltip(l.viewerMoreOptionsTooltip));
    await _finishTransition(tester);
    await tester.tap(find.text(l.reportContentTitle));
    await _finishTransition(tester);
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.byType(ContentReportSheet), findsNothing);

    // Solve the visible, randomly generated challenge from the real service.
    // Do not pre-verify the session or inject an always-successful gate.
    final challengePattern = RegExp(r'^(\d+)\s*×\s*(\d+)\s*=\s*\?$');
    final challengeText = tester
        .widgetList<Text>(find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(Text),
        ))
        .map((text) => text.data ?? '')
        .singleWhere(challengePattern.hasMatch);
    final challenge = challengePattern.firstMatch(challengeText)!;
    final answer =
        int.parse(challenge.group(1)!) * int.parse(challenge.group(2)!);
    final input = find.descendant(
      of: find.byType(AlertDialog),
      matching: find.byType(TextField),
    );
    await tester.ensureVisible(input);
    await tester.enterText(input, '$answer');
    await tester.pump();
    final confirm = find.widgetWithText(ElevatedButton, l.ageGateConfirm);
    await tester.ensureVisible(confirm);
    await tester.tap(confirm);
    await tester.pump();
    await _finishTransition(tester);

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(ContentReportSheet), findsOneWidget);
    expect(find.text(l.reportContentCover), findsOneWidget);
    expect(parental.isAgeGateVerifiedForSession, isTrue);
    expect(prefs.getInt(ParentalControlService.ageGateSessionKey), isNotNull);
    expect(prefs.getBool(_preferencesMarker), isTrue);

    // The newly opened sheet must remain interactive after input disposal.
    final cancel = find.widgetWithText(TextButton, l.reportContentCancel);
    await tester.ensureVisible(cancel);
    await tester.tap(cancel);
    await _finishTransition(tester);
    expect(find.byType(ContentReportSheet), findsNothing);
    expect(find.byType(ViewerScreen), findsOneWidget);
  });
}
