import 'dart:io';

/// Environment configuration
class EnvConfig {
  /// Get the API base URL based on the current environment
  static String get apiBaseUrl {
    // Check for environment override
    const envUrl = String.fromEnvironment('API_BASE_URL');
    if (envUrl.isNotEmpty) {
      return envUrl;
    }

    // Check if running in debug mode
    if (_isDebugMode) {
      // For iOS simulator, use localhost
      // For Android emulator, use 10.0.2.2 (special alias for host machine)
      if (Platform.isAndroid) {
        return 'http://10.0.2.2:8000';
      }
      return 'http://localhost:8000';
    }

    // Production URL — placeholder로 릴리스되는 것을 차단(잘못된 API로 출시 방지).
    const prodUrl = String.fromEnvironment(
      'PROD_API_URL',
      defaultValue: 'https://api.storybook.example.com',
    );
    return validateProdUrl(prodUrl);
  }

  /// 릴리스 prod URL 검증 — 미설정/placeholder면 즉시 실패(빌드 사고 조기 발견).
  /// 테스트 가능하도록 분리(릴리스 모드 의존 없이 단위 검증).
  static String validateProdUrl(String url) {
    if (url.isEmpty || url.contains('example.com')) {
      throw StateError(
        'PROD_API_URL이 설정되지 않았습니다(placeholder: "$url"). '
        '릴리스 빌드는 --dart-define=PROD_API_URL=https://<실제 API 도메인> 으로 빌드하세요.',
      );
    }
    return url;
  }

  static bool get _isDebugMode {
    bool isDebug = false;
    assert(() {
      isDebug = true;
      return true;
    }());
    return isDebug;
  }
}
