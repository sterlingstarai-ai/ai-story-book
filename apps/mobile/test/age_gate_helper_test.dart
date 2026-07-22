import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:ai_story_book/widgets/age_gate_dialog.dart';

// M24: 두 사진 진입점이 공유하는 공용 게이트. 세션 검증 상태에 따라 다이얼로그를
// 띄우거나 통과시키는지 검증(진입점 간 이중 보호 일치의 토대).
Widget _host(ParentalControlService svc, void Function(bool) onResult) {
  return ProviderScope(
    overrides: [parentalControlServiceProvider.overrideWithValue(svc)],
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: Consumer(
          builder: (context, ref, _) => ElevatedButton(
            onPressed: () async => onResult(await ensureAgeGate(context, ref)),
            child: const Text('go'),
          ),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('ensureAgeGate passes without a dialog when already verified (M24)',
      (tester) async {
    final svc = ParentalControlService()..markAgeGateVerified();
    bool? result;
    await tester.pumpWidget(_host(svc, (r) => result = r));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    expect(result, isTrue);
    expect(find.byType(AlertDialog), findsNothing); // 재검증 불필요
  });

  testWidgets('ensureAgeGate shows the age gate when not verified (M24)',
      (tester) async {
    final svc = ParentalControlService(); // 미검증
    await tester.pumpWidget(_host(svc, (_) {}));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    // 보호자 게이트 다이얼로그가 먼저 표시된다.
    expect(find.byType(AlertDialog), findsOneWidget);
  });
}
