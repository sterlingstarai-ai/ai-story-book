import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/widgets/vocab_game_card.dart';

Widget _host(VocabGameCard card) => MaterialApp(home: Scaffold(body: card));

void main() {
  final item = VocabItem(word: '용감', meaning: '겁이 없고 씩씩함');
  const all = ['겁이 없고 씩씩함', '아주 큼', '빠르게 달림', '슬프고 외로움', '맛이 달콤함'];

  testWidgets('질문과 4지선다(정답 포함)를 렌더한다', (tester) async {
    await tester.pumpWidget(_host(
      VocabGameCard(item: item, allMeanings: all),
    ));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('vocab_game_card')), findsOneWidget);
    expect(find.text('"용감"의 뜻은?'), findsOneWidget);
    // 보기는 정확히 4개(정답 1 + 오답 3), 정답 포함
    expect(find.bySemanticsLabel(RegExp(r'^보기: ')), findsNWidgets(4));
    expect(find.text('겁이 없고 씩씩함'), findsOneWidget);
  });

  testWidgets('정답 선택 → 보상(잘했어요 ⭐) + onAnswered(true), 1회만 채점', (tester) async {
    final answers = <bool>[];
    await tester.pumpWidget(_host(
      VocabGameCard(item: item, allMeanings: all, onAnswered: answers.add),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('겁이 없고 씩씩함'));
    await tester.pumpAndSettle();

    expect(find.text('잘했어요! ⭐'), findsOneWidget);
    expect(answers, [true]);

    // 채점 후 다른 보기를 눌러도 추가 채점되지 않음(잠금)
    await tester.tap(find.text('아주 큼'));
    await tester.pumpAndSettle();
    expect(answers, [true]); // 변화 없음
  });

  testWidgets('오답 선택 → 정답 안내 + onAnswered(false)', (tester) async {
    final answers = <bool>[];
    await tester.pumpWidget(_host(
      VocabGameCard(item: item, allMeanings: all, onAnswered: answers.add),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('아주 큼'));
    await tester.pumpAndSettle();

    expect(find.textContaining('다시 한 번 기억해요'), findsOneWidget);
    expect(find.textContaining('겁이 없고 씩씩함'), findsWidgets); // 정답 노출
    expect(answers, [false]);
    expect(find.text('잘했어요! ⭐'), findsNothing);
  });

  testWidgets('정답 시 햅틱 피드백 호출', (tester) async {
    final haptics = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'HapticFeedback.vibrate') {
          haptics.add(call.arguments as String? ?? 'default');
        }
        return null;
      },
    );
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    await tester.pumpWidget(_host(VocabGameCard(item: item, allMeanings: all)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('겁이 없고 씩씩함'));
    await tester.pumpAndSettle();

    expect(haptics, isNotEmpty); // mediumImpact 발생
  });

  testWidgets('보기 부족 시(뜻 3종 미만) 중복 없이 가능한 만큼만', (tester) async {
    // 정답 + 오답 1개만 제공 → 보기 2개(중복 없음). 게임 자체는 viewer가 게이트하지만
    // 위젯 단독으로도 안전하게 동작해야 한다.
    await tester.pumpWidget(_host(
      VocabGameCard(item: item, allMeanings: const ['겁이 없고 씩씩함', '아주 큼']),
    ));
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel(RegExp(r'^보기: ')), findsNWidgets(2));
  });
}
