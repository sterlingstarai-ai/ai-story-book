import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/core/env_config.dart';

void main() {
  group('EnvConfig.validateProdUrl', () {
    test('placeholder(example.com) URL은 차단(릴리스 빌드 사고 방지)', () {
      expect(
        () => EnvConfig.validateProdUrl('https://api.storybook.example.com'),
        throwsStateError,
      );
    });

    test('빈 URL도 차단', () {
      expect(() => EnvConfig.validateProdUrl(''), throwsStateError);
    });

    test('실제 도메인은 통과', () {
      expect(
        EnvConfig.validateProdUrl('https://api.aistorybook.app'),
        'https://api.aistorybook.app',
      );
    });
  });

  test('디버그/테스트 모드에서는 localhost로 안전하게 해석(throw 없음)', () {
    // 테스트는 debug 모드 → prod 가드 경로에 닿지 않고 localhost 계열 반환
    final url = EnvConfig.apiBaseUrl;
    expect(url.contains('localhost') || url.contains('10.0.2.2'), isTrue);
  });
}
