import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/core/env_config.dart';

void main() {
  test(
    'release document URLs reject missing placeholders and credentials but allow document paths',
    () {
      for (final value in [
        '',
        'http://policies.org/privacy',
        'https://example.com/privacy',
        'https://example.com./privacy',
        'https://localhost/privacy',
        'https://user:secret@policies.org/privacy',
        '/privacy',
        'https://policies.org/privacy?token=private',
      ]) {
        expect(
          () => EnvConfig.validatePublicDocumentUrl(value),
          throwsStateError,
        );
      }
      expect(
        EnvConfig.validatePublicDocumentUrl(
          'https://storybook.pages.dev/privacy/',
        ),
        'https://storybook.pages.dev/privacy/',
      );
    },
  );
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

  for (final url in [
    'http://api.aistorybook.app',
    'https://localhost',
    'https://127.0.0.1',
    'https://10.0.2.2',
    'https://[::1]',
    'https://service.local',
    'https://service.lan',
    'https://service.home',
    'https://service.test',
    'https://example.org',
    'https://api.example.org.',
    'https://api.aistorybook.app/v1',
    'https://api.aistorybook.app?secret=value',
    'https://user:password@api.aistorybook.app',
    'https://api.aistorybook.app/#x',
  ]) {
    test('release rejects unsafe origin through either define: $url', () {
      expect(() => EnvConfig.validateProdUrl(url), throwsStateError);
      expect(
        () => EnvConfig.resolveApiBaseUrl(
          isDebug: false,
          overrideUrl: url,
          productionUrl: 'https://api.aistorybook.app',
        ),
        throwsStateError,
      );
    });
  }

  test(
    'debug override retains local HTTP and release normalizes HTTPS origin',
    () {
      expect(
        EnvConfig.resolveApiBaseUrl(
          isDebug: true,
          overrideUrl: 'http://localhost:9000',
        ),
        'http://localhost:9000',
      );
      expect(
        EnvConfig.resolveApiBaseUrl(
          isDebug: false,
          productionUrl: 'https://api.aistorybook.app/',
        ),
        'https://api.aistorybook.app',
      );
    },
  );

  test('release rejects a public debug override even with a valid origin', () {
    expect(
      () => EnvConfig.resolveApiBaseUrl(
        isDebug: false,
        overrideUrl: 'https://staging.aistorybook.app',
        productionUrl: 'https://api.aistorybook.app',
      ),
      throwsStateError,
    );
  });

  test('디버그/테스트 모드에서는 localhost로 안전하게 해석(throw 없음)', () {
    // 테스트는 debug 모드 → prod 가드 경로에 닿지 않고 localhost 계열 반환
    final url = EnvConfig.apiBaseUrl;
    expect(url.contains('localhost') || url.contains('10.0.2.2'), isTrue);
  });
}
