import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/content_report.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/widgets/content_report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ReportApi extends ApiClient {
  _ReportApi() : super(baseUrl: 'http://127.0.0.1:1', userKey: 'test');
  int calls = 0;
  bool fail = false;
  Completer<ContentReportReceipt>? pending;
  int? page;
  ContentReportReason? reason;

  @override
  Future<ContentReportReceipt> reportBookContent(String bookId,
      {required int pageNumber, required ContentReportReason reason}) async {
    calls++;
    page = pageNumber;
    this.reason = reason;
    if (fail) throw StateError('synthetic failure');
    if (pending != null) return pending!.future;
    return const ContentReportReceipt(
        reportId: 'report_test', status: 'pending');
  }
}

Future<void> _open(WidgetTester tester, _ReportApi api,
    {bool verified = true, int pageNumber = 0}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  final parental = ParentalControlService();
  if (verified) parental.markAgeGateVerified();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      apiClientProvider.overrideWithValue(api),
      parentalControlServiceProvider.overrideWithValue(parental),
    ],
    child: MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: Consumer(builder: (context, ref, child) {
        return TextButton(
          onPressed: () => showContentReportSheet(context, ref,
              bookId: 'book_test', pageNumber: pageNumber),
          child: const Text('open report'),
        );
      })),
    ),
  ));
  await tester.tap(find.text('open report'));
  await tester.pumpAndSettle();
}

Future<void> _submit(WidgetTester tester) async {
  await tester.pump();
  final send = find.byKey(const Key('content-report-submit'));
  await tester.ensureVisible(send);
  await tester.tap(send);
  await tester.pump();
}

void main() {
  test('malformed report response cannot appear as a successful receipt', () {
    for (final json in <Map<String, dynamic>>[
      {},
      {'report_id': '', 'status': 'pending'},
      {'report_id': 'r', 'status': 'unexpected'},
    ]) {
      expect(() => ContentReportReceipt.fromJson(json), throwsFormatException);
    }
  });

  testWidgets('report is protected by the existing parent gate',
      (tester) async {
    final api = _ReportApi();
    await _open(tester, api, verified: false);
    expect(find.byType(ContentReportSheet), findsNothing);
    expect(find.byType(AlertDialog), findsOneWidget);
    final context = tester.element(find.byType(AlertDialog));
    await tester.tap(find.text(AppLocalizations.of(context).ageGateCancel));
    await tester.pumpAndSettle();
    expect(find.byType(ContentReportSheet), findsNothing);
    expect(api.calls, 0);
  });

  testWidgets(
      'cover report requires a reason and prevents repeated submissions',
      (tester) async {
    final api = _ReportApi()..pending = Completer<ContentReportReceipt>();
    await _open(tester, api);
    expect(find.text('이 표지를 신고해요'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(
        tester
            .widget<FilledButton>(
                find.byKey(const Key('content-report-submit')))
            .onPressed,
        isNull);
    await tester.tap(find.text('폭력적이거나 위험한 내용'));
    await _submit(tester);
    expect(api.calls, 1);
    expect(api.page, 0);
    expect(api.reason, ContentReportReason.harmfulContent);
    expect(
        tester
            .widget<FilledButton>(
                find.byKey(const Key('content-report-submit')))
            .onPressed,
        isNull);
    api.pending!
        .complete(const ContentReportReceipt(reportId: 'r', status: 'pending'));
    await tester.pumpAndSettle();
    expect(find.text('신고가 접수되었어요. 내용을 검토하겠습니다.'), findsOneWidget);
    await tester.tap(find.text('동화로 돌아가기'));
    await tester.pumpAndSettle();
    expect(find.byType(ContentReportSheet), findsNothing);
  });

  testWidgets('small large-text report scrolls to reason and retry action',
      (tester) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final api = _ReportApi()..fail = true;
    await _open(tester, api, pageNumber: 3);
    expect(find.text('3쪽을 신고해요'), findsOneWidget);
    final reason = find.text('그림의 오류');
    await tester.ensureVisible(reason);
    await tester.tap(reason);
    await _submit(tester);
    await tester.pumpAndSettle();
    expect(find.text('신고를 보내지 못했어요. 다시 시도해 주세요.'), findsOneWidget);
    expect(api.page, 3);
    api.fail = false;
    await _submit(tester);
    await tester.pumpAndSettle();
    expect(find.text('신고가 접수되었어요. 내용을 검토하겠습니다.'), findsOneWidget);
    expect(api.calls, 2);
    expect(tester.takeException(), isNull);
  });
}
