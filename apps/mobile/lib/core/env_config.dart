import 'dart:io';

/// Environment configuration. Both release URL defines share the same gate.
class EnvConfig {
  static String get apiBaseUrl => resolveApiBaseUrl(
        isDebug: _isDebugMode,
        isAndroid: Platform.isAndroid,
        overrideUrl: const String.fromEnvironment('API_BASE_URL'),
        productionUrl: const String.fromEnvironment('PROD_API_URL'),
      );

  static String resolveApiBaseUrl({
    required bool isDebug,
    bool isAndroid = false,
    String overrideUrl = '',
    String productionUrl = '',
  }) {
    if (overrideUrl.isNotEmpty) {
      return isDebug ? overrideUrl : validateProdUrl(overrideUrl);
    }
    if (isDebug) {
      return isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
    }
    return validateProdUrl(productionUrl);
  }

  /// Release credentials and child content may only be sent to an explicit,
  /// public HTTPS origin. Error text never echoes a possibly sensitive URL.
  static String validateProdUrl(String url) {
    final uri = Uri.tryParse(url);
    final host = uri?.host.toLowerCase() ?? '';
    final reserved = host == 'localhost' ||
        !host.contains('.') ||
        InternetAddress.tryParse(host) != null ||
        ['.localhost', '.local', '.internal', '.test', '.invalid', '.example']
            .any(host.endsWith) ||
        ['example.com', 'example.net', 'example.org']
            .any((domain) => host == domain || host.endsWith('.$domain'));
    if (url.trim() != url ||
        uri == null ||
        uri.scheme != 'https' ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        reserved) {
      throw StateError(
        'A public HTTPS API origin is required for release builds. '
        'Set --dart-define=PROD_API_URL=https://your-api-domain.',
      );
    }
    return uri.origin;
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
