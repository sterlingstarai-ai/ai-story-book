import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';

// 철회로 인한 계정 전체 파생물 삭제와 복구 불가, 저장소 지연을 함께 안내한다.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'revoke-consent dialog warns of permanent, irreversible deletion',
    () async {
      // (로캘, 삭제 표현, 불가역 표현, 계정 범위, 지연 표현)
      const cases = {
        'ko': ['삭제', '복구', '이 계정', '지연'],
        'en': ['deletion', 'cannot be undone', 'this account', 'longer'],
        'ja': ['削除', '復元でき', 'このアカウント', '遅れる'],
      };
      for (final entry in cases.entries) {
        final l = await AppLocalizations.delegate.load(Locale(entry.key));
        final content = l.settingsRevokeConsentContent.toLowerCase();
        for (final term in entry.value) {
          expect(
            content,
            contains(term.toLowerCase()),
            reason: '${entry.key} 철회 문구에 "$term"(삭제/불가역 경고)가 없다',
          );
        }
        for (final falsePromise in ['즉시 삭제', 'immediately', '直ちに削除']) {
          expect(content, isNot(contains(falsePromise)));
        }
      }
    },
  );
}
