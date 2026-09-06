import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/widgets/age_gate_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Parent extends ParentalControlService {
  int challenges = 0;
  int sessions = 0;

  @override
  AgeChallenge createChallenge() {
    challenges++;
    return const AgeChallenge(left: 123, right: 7);
  }

  @override
  Future<void> persistAgeGateSession(SharedPreferences prefs) async {
    sessions++;
    await super.persistAgeGateSession(prefs);
  }
}

class _GateLauncher extends ConsumerWidget {
  const _GateLauncher(this.results);

  final List<bool> results;

  @override
  Widget build(BuildContext context, WidgetRef ref) => ElevatedButton(
        onPressed: () async {
          final passed = await showAgeGateDialog(context, ref);
          results.add(passed);
          if (!passed || !context.mounted) return;
          await showModalBottomSheet<void>(
            context: context,
            isScrollControlled: true,
            builder: (_) => const Padding(
              padding: EdgeInsets.all(20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('report-form'),
                  TextField(key: Key('report-input')),
                ],
              ),
            ),
          );
        },
        child: const Text('open-gate'),
      );
}

Future<SharedPreferences> _pumpGate(
  WidgetTester tester,
  _Parent parent,
  List<bool> results, {
  ValueNotifier<bool>? launcherVisible,
}) async {
  SharedPreferences.setMockInitialValues({});
  final prefs = await SharedPreferences.getInstance();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      parentalControlServiceProvider.overrideWithValue(parent),
    ],
    child: MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: launcherVisible == null
            ? _GateLauncher(results)
            : ValueListenableBuilder<bool>(
                valueListenable: launcherVisible,
                builder: (_, visible, __) => visible
                    ? _GateLauncher(results)
                    : const Text('launcher-removed'),
              ),
      ),
    ),
  ));
  await tester.tap(find.text('open-gate'));
  await tester.pumpAndSettle();
  return prefs;
}

Future<void> _confirm(WidgetTester tester) async {
  final l = await AppLocalizations.delegate.load(const Locale('ko'));
  final button = find.widgetWithText(ElevatedButton, l.ageGateConfirm);
  await tester.ensureVisible(button);
  await tester.tap(button);
  // Render both routes during the closing/opening animation, where the former
  // function-owned controller was disposed while TextField still used it.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('typed answer transitions directly to the next modal safely',
      (tester) async {
    final parent = _Parent();
    final results = <bool>[];
    final prefs = await _pumpGate(tester, parent, results);
    await tester.enterText(find.byType(TextField), '861');
    expect(tester.testTextInput.isVisible, isTrue);
    await _confirm(tester);
    expect(results, [true]);
    expect(parent.sessions, 1);
    expect(parent.isAgeGateVerifiedForSession, isTrue);
    expect(prefs.getInt(ParentalControlService.ageGateSessionKey), isNotNull);
    expect(find.text('report-form'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
    await tester.enterText(find.byKey(const Key('report-input')), '문제 설명');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'wrong answer stays blocked and correction uses the same challenge',
      (tester) async {
    final parent = _Parent();
    final results = <bool>[];
    final prefs = await _pumpGate(tester, parent, results);
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await tester.enterText(find.byType(TextField), '0');
    await _confirm(tester);
    expect(find.text(l.ageGateWrongAnswer), findsOneWidget);
    expect(find.text('123 × 7 = ?'), findsOneWidget);
    expect(results, isEmpty);
    expect(parent.sessions, 0);
    expect(parent.isAgeGateVerifiedForSession, isFalse);
    expect(
        prefs.containsKey(ParentalControlService.ageGateSessionKey), isFalse);
    await tester.enterText(find.byType(TextField), '861');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(results, [true]);
    expect(parent.challenges, 1);
    expect(parent.sessions, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('cancel after typing does not grant a parent session',
      (tester) async {
    final parent = _Parent();
    final results = <bool>[];
    final prefs = await _pumpGate(tester, parent, results);
    final l = await AppLocalizations.delegate.load(const Locale('ko'));
    await tester.enterText(find.byType(TextField), '861');
    await tester.tap(find.text(l.ageGateCancel));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pumpAndSettle();
    expect(results, [false]);
    expect(parent.sessions, 0);
    expect(
        prefs.containsKey(ParentalControlService.ageGateSessionKey), isFalse);
    expect(find.text('report-form'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'keyboard and large text keep the answer and confirmation reachable',
      (tester) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    tester.view.viewInsets = const FakeViewPadding(bottom: 180);
    tester.platformDispatcher.textScaleFactorTestValue = 1.4;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final parent = _Parent();
    final results = <bool>[];
    await _pumpGate(tester, parent, results);
    await tester.ensureVisible(find.byType(TextField));
    await tester.enterText(find.byType(TextField), '861');
    await _confirm(tester);
    expect(results, [true]);
    expect(find.text('report-form'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'removing the caller during the dialog cannot grant or use its ref',
      (tester) async {
    final visible = ValueNotifier(true);
    addTearDown(visible.dispose);
    final parent = _Parent();
    final results = <bool>[];
    final prefs =
        await _pumpGate(tester, parent, results, launcherVisible: visible);
    visible.value = false;
    await tester.pump();
    await tester.enterText(find.byType(TextField), '861');
    await _confirm(tester);
    expect(results, [false]);
    expect(parent.sessions, 0);
    expect(
        prefs.containsKey(ParentalControlService.ageGateSessionKey), isFalse);
    expect(find.text('report-form'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
