import 'package:ai_story_book/widgets/account_bootstrap.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('읽기 실패 동안 앱을 열지 않고 재시도가 성공하면 진입한다', (tester) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var calls = 0;
    await tester.pumpWidget(AccountBootstrap(
      initialize: () async {
        calls++;
        if (calls == 1) throw Exception('storage unavailable');
      },
      child: const MaterialApp(home: Text('Account ready')),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Account ready'), findsNothing);
    expect(find.byType(FilledButton), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byType(FilledButton));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Account ready'), findsOneWidget);
  });
}
