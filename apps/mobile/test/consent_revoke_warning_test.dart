import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';

// F1(감사 Q1): 동의 철회는 이 아이 사진으로 만든 캐릭터·책을 즉시·불가역 파기한다.
// 철회 확인 다이얼로그 문구가 그 사실(삭제 + 복구 불가)을 명시해야 사용자가 실수로
// 파기하지 않는다. 예전 문구("앱 이용이 제한되며 데이터 삭제를 진행할 수 있습니다")는
// 불가역 삭제를 알리지 않았다 — 약한 문구로의 회귀를 세 로캘에서 잠근다.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('revoke-consent dialog warns of permanent, irreversible deletion', () async {
    // (로캘, 삭제 표현, 불가역 표현)
    const cases = {
      'ko': ['삭제', '복구'],
      'en': ['delete', 'cannot be undone'],
      'ja': ['削除', '復元でき'],
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
    }
  });
}
