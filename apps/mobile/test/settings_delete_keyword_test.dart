import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';

// H21: 삭제 확인 키워드가 '삭제' 하드코딩이라 en/ja 사용자가 삭제 불가하던 버그.
// 확인 프롬프트가 로캘 키워드를 표시하고, 비교도 같은 l.settingsDeleteKeyword를 쓰므로
// 표시 키워드 == 비교 대상이 되도록 정합함을 검증한다.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('delete keyword prompt uses the localized keyword per locale (H21)',
      () async {
    const expected = {'ko': '삭제', 'en': 'Delete', 'ja': '削除'};
    for (final entry in expected.entries) {
      final l = await AppLocalizations.delegate.load(Locale(entry.key));
      // 로캘별 키워드(사용자가 입력해야 하는 값 == 비교 대상).
      expect(l.settingsDeleteKeyword, entry.value);
      // 프롬프트가 그 키워드를 안내한다(플레이스홀더로 주입).
      final prompt = l.settingsFinalConfirmPrompt(l.settingsDeleteKeyword);
      expect(prompt, contains(l.settingsDeleteKeyword));
      // en/ja 프롬프트에 한국어 '삭제' 하드코딩이 남아있지 않다.
      if (entry.key != 'ko') {
        expect(prompt, isNot(contains('삭제')));
      }
    }
  });
}
