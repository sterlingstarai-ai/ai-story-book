import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/widgets/character_source_sheet.dart';

void main() {
  testWidgets('CharacterSourceSheet renders preset chips + photo options',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          characterPresetsProvider.overrideWith((ref) async => [
                {'preset_id': 'bright_girl', 'name': '햇살이'},
                {'preset_id': 'brave_boy', 'name': '씩씩이'},
              ]),
        ],
        child: const MaterialApp(
          home: Scaffold(body: CharacterSourceSheet()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('우리 아이를 주인공으로'), findsOneWidget);
    expect(find.text('사진 촬영'), findsOneWidget);
    expect(find.text('갤러리'), findsOneWidget);
    expect(find.byKey(const Key('preset_bright_girl')), findsOneWidget);
    expect(find.byKey(const Key('preset_brave_boy')), findsOneWidget);
    expect(find.text('햇살이'), findsOneWidget);
  });
}
