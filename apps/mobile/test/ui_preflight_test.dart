import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _scrollViewKey = Key('ui-preflight-scroll-view');

Widget _buildSheetHarness({
  double textScale = 1.0,
  String? title,
  String? subtitle,
}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(
        size: const Size(320, 480),
        textScaler: TextScaler.linear(textScale),
      ),
      child: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Material(
            color: Colors.white,
            child: AdaptiveModalSheet(
              title: title,
              subtitle: subtitle,
              scrollViewKey: _scrollViewKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: List.generate(
                  12,
                  (index) => ListTile(
                    title: Text('액션 ${index + 1}'),
                    subtitle: const Text('프리플라이트용 더미 액션'),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

Finder _sheetScrollable() {
  return find.descendant(
    of: find.byKey(_scrollViewKey),
    matching: find.byType(Scrollable),
  );
}

void _setPhoneViewport(WidgetTester tester) {
  tester.view.devicePixelRatio = 1.0;
  tester.view.physicalSize = const Size(320, 480);
}

void _resetViewport(WidgetTester tester) {
  tester.view.resetPhysicalSize();
  tester.view.resetDevicePixelRatio();
}

void main() {
  group('AdaptiveModalSheet', () {
    testWidgets('keeps the final action reachable on a short viewport',
        (tester) async {
      _setPhoneViewport(tester);
      addTearDown(() => _resetViewport(tester));

      await tester.pumpWidget(_buildSheetHarness(title: '옵션'));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(
        find.text('액션 12'),
        240,
        scrollable: _sheetScrollable(),
      );
      await tester.pumpAndSettle();

      expect(find.text('액션 12'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('handles larger text scales without overflow',
        (tester) async {
      _setPhoneViewport(tester);
      addTearDown(() => _resetViewport(tester));

      await tester.pumpWidget(
        _buildSheetHarness(
          textScale: 1.4,
          title: '공유하기',
          subtitle: '작은 화면에서도 마지막 버튼까지 확인할 수 있어야 해요.',
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('공유하기'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.text('액션 12'),
        240,
        scrollable: _sheetScrollable(),
      );
      await tester.pumpAndSettle();

      expect(find.text('액션 12'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
