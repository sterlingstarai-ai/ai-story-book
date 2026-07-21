import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/screens/loading_screen.dart';

// M29: 안전 차단(SAFETY_INPUT) 에러는 서버가 사용자 언어 reasons만 담아 오므로
// 클라이언트가 로컬라이즈된 접두어를 붙인다. 그 외 코드는 서버 메시지 원문.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('SAFETY_INPUT prepends the localized prefix per locale (M29)', () async {
    for (final code in ['ko', 'en', 'ja']) {
      final l = await AppLocalizations.delegate.load(Locale(code));
      final text = composeJobErrorText(l, 'SAFETY_INPUT', 'unsafe topic');
      // 로컬라이즈된 접두어가 붙는다.
      expect(text, contains(l.loadingSafetyBlockedPrefix));
      // 서버가 준 사용자 언어 reason은 그대로 보존된다.
      expect(text, contains('unsafe topic'));
      // 비-한국어 로캘에는 한국어 접두어가 하드코딩돼 있지 않다.
      if (code != 'ko') {
        expect(text, isNot(contains('입력이 안전하지 않습니다')));
      }
    }
  });

  test('non-safety errors render the server message verbatim (M29)', () async {
    final l = await AppLocalizations.delegate.load(const Locale('en'));
    final text = composeJobErrorText(l, 'LLM_TIMEOUT', 'timed out');
    expect(text, 'timed out');
    expect(text, isNot(contains(l.loadingSafetyBlockedPrefix)));
  });

  test('null message falls back to the unknown-error label (M29)', () async {
    final l = await AppLocalizations.delegate.load(const Locale('en'));
    final text = composeJobErrorText(l, null, null);
    expect(text, l.loadingUnknownError);
  });
}
