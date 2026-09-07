import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/screens/loading_screen.dart';

// M29: 안전 차단(SAFETY_INPUT) 에러는 서버가 사용자 언어 reasons만 담아 오므로
// 클라이언트가 로컬라이즈된 접두어를 붙인다. 일반 실패는 앱 언어로 표시한다.
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

  // 서버(core/errors.py)는 SAFETY_* 외의 모든 실패 메시지를 한국어 상수 하나로
  // 바꿔 저장·서빙한다. 그래서 '원문 그대로'는 곧 'en/ja 사용자에게 한국어'였다.
  // 비-안전 코드는 로컬라이즈된 문구로 고정한다.
  test(
    'non-safety errors use a localized message, never the server text',
    () async {
      for (final code in ['ko', 'en', 'ja']) {
        final l = await AppLocalizations.delegate.load(Locale(code));
        final text = composeJobErrorText(
          l,
          'LLM_TIMEOUT',
          '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.',
        );
        expect(text, l.loadingGenericFailure);
        expect(text, isNot(contains(l.loadingSafetyBlockedPrefix)));
        if (code != 'ko') {
          expect(text, isNot(contains('요청을 처리하지 못했습니다')));
        }
      }
    },
  );

  test(
    'SAFETY_OUTPUT keeps the server-authored reason (client-safe code)',
    () async {
      final l = await AppLocalizations.delegate.load(const Locale('en'));
      expect(
        composeJobErrorText(l, 'SAFETY_OUTPUT', 'blocked reason'),
        'blocked reason',
      );
    },
  );

  test('null code and message fall back to the localized failure', () async {
    final l = await AppLocalizations.delegate.load(const Locale('en'));
    expect(composeJobErrorText(l, null, null), l.loadingGenericFailure);
  });

  test(
    'image quality failure localizes without diagnostics or refund claims',
    () async {
      for (final code in ['ko', 'en', 'ja']) {
        final l = await AppLocalizations.delegate.load(Locale(code));
        for (final message in [
          null,
          'provider diagnostics; refund completed',
        ]) {
          expect(
            composeJobErrorText(l, 'IMAGE_QUALITY_FAILED', message),
            l.loadingImageQualityFailed,
          );
        }
      }
    },
  );

  test(
    'TIMEOUT shows localized message, not raw TimeoutException (H17)',
    () async {
      for (final code in ['ko', 'en', 'ja']) {
        final l = await AppLocalizations.delegate.load(Locale(code));
        // 폴링 타임아웃은 원문(TimeoutException…) 대신 로컬라이즈 문구로 매핑된다.
        final text = composeJobErrorText(l, 'TIMEOUT', 'TimeoutException: ...');
        expect(text, l.loadingTimeoutMessage);
        expect(text, isNot(contains('TimeoutException')));
      }
    },
  );
}
