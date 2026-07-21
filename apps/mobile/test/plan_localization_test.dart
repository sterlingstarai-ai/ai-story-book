import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/screens/credits_screen.dart';

// M15: 구독 플랜명/features를 안정 키(plan id)로 로컬라이즈 — en/ja 사용자에게
// 서버가 내려준 한국어 '베이직'·features를 그대로 노출하지 않는다.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('plan names localize by id, not the Korean server name (M15)', () async {
    final en = await AppLocalizations.delegate.load(const Locale('en'));
    final ja = await AppLocalizations.delegate.load(const Locale('ja'));
    final ko = await AppLocalizations.delegate.load(const Locale('ko'));

    // 서버가 '베이직'을 내려줘도 로케일 값으로 표시된다.
    expect(localizedPlanName(en, 'basic', '베이직'), en.planBasic);
    expect(localizedPlanName(en, 'basic', '베이직'), isNot('베이직'));
    expect(localizedPlanName(ja, 'premium', '프리미엄'), ja.planPremium);
    expect(localizedPlanName(ko, 'free', '무료'), ko.planFree);

    // 미지 plan id는 서버 name으로 폴백(하위호환).
    expect(localizedPlanName(en, 'enterprise', 'Enterprise Plan'),
        'Enterprise Plan');
  });

  test('plan features localize and split by delimiter (M15)', () async {
    final en = await AppLocalizations.delegate.load(const Locale('en'));

    final feats = localizedPlanFeatures(en, 'basic', const ['월 10권 생성']);
    // en features는 한국어를 포함하지 않고 여러 항목으로 분리된다.
    expect(feats.length, greaterThan(1));
    expect(feats.any((f) => f.contains('월')), isFalse);
    expect(feats.any((f) => f.contains('|')), isFalse);

    // 미지 plan id는 서버 features로 폴백.
    final fallback = localizedPlanFeatures(en, 'enterprise', const ['서버 features']);
    expect(fallback, const ['서버 features']);
  });
}
