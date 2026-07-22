import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/screens/home_screen.dart';

// H25: '오늘의 동화' 테마/토픽을 서버 안정 키(theme id + topic_id)로 로케일 표시.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('daily theme/topic labels localize by stable id (H25)', () async {
    final en = await AppLocalizations.delegate.load(const Locale('en'));
    final ja = await AppLocalizations.delegate.load(const Locale('ja'));

    // 서버가 한국어 폴백을 줘도 로케일 값으로 표시(en/ja에 한국어 미노출).
    expect(dailyThemeLabel(en, 'friendship', '우정'), en.dailyThemeFriendship);
    expect(dailyThemeLabel(en, 'friendship', '우정'), isNot('우정'));
    expect(dailyThemeLabel(ja, 'imagination', '상상'), ja.dailyThemeImagination);

    expect(
      dailyTopicLabel(en, 'courage_1', '새로운 도전'),
      en.dailyTopicCourage1,
    );
    expect(dailyTopicLabel(en, 'courage_1', '새로운 도전'), isNot('새로운 도전'));

    // 미지 id → 서버 폴백.
    expect(dailyThemeLabel(en, 'zzz', 'fallback-t'), 'fallback-t');
    expect(dailyTopicLabel(en, 'zzz_9', 'fallback-p'), 'fallback-p');
  });
}
