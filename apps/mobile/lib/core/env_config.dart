import 'dart:io';
import 'package:flutter/foundation.dart';
import 'release_policy_gate.dart';

/// Environment configuration. Both release URL defines share the same gate.
class EnvConfig {
  static const _apiOverride = String.fromEnvironment('API_BASE_URL');
  static const _productionApi = String.fromEnvironment('PROD_API_URL');

  static void validateReleaseConfiguration() {
    // Referencing the constant also enforces missing values at build time.
    if (releasePolicyGate.release || !_isDebugMode) {
      resolveApiBaseUrl(
        isDebug: false,
        overrideUrl: _apiOverride,
        productionUrl: _productionApi,
      );
      validatePublicDocumentUrl(releasePolicyGate.privacy);
      validatePublicDocumentUrl(releasePolicyGate.terms);
    }
  }

  static String validatePublicDocumentUrl(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null || uri.hasQuery || uri.hasFragment || url.trim() != url) {
      throw StateError('A public HTTPS document URL is required for release.');
    }
    if (!uri.hasAuthority || uri.scheme != 'https' || uri.userInfo.isNotEmpty) {
      throw StateError('A public HTTPS document URL is required for release.');
    }
    validateProdUrl(uri.origin);
    return uri.toString();
  }

  static String get apiBaseUrl => resolveApiBaseUrl(
    isDebug: _isDebugMode,
    isAndroid: !kIsWeb && Platform.isAndroid,
    overrideUrl: _apiOverride,
    productionUrl: _productionApi,
  );

  static String resolveApiBaseUrl({
    required bool isDebug,
    bool isAndroid = false,
    String overrideUrl = '',
    String productionUrl = '',
  }) {
    if (isDebug) {
      if (overrideUrl.isNotEmpty) return overrideUrl;
      return isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
    }
    if (overrideUrl.isNotEmpty) {
      throw StateError('API_BASE_URL is available only in debug builds.');
    }
    return validateProdUrl(productionUrl);
  }

  /// Release credentials and child content may only be sent to an explicit,
  /// public HTTPS origin. Error text never echoes a possibly sensitive URL.
  static String validateProdUrl(String url) {
    final uri = Uri.tryParse(url);
    final host = uri?.host.toLowerCase().replaceFirst(RegExp(r'\.$'), '') ?? '';
    final reserved =
        host == 'localhost' ||
        !host.contains('.') ||
        InternetAddress.tryParse(host) != null ||
        [
          '.localhost',
          '.local',
          '.internal',
          '.lan',
          '.home',
          '.test',
          '.invalid',
          '.example',
        ].any(host.endsWith) ||
        [
          'example.com',
          'example.net',
          'example.org',
        ].any((domain) => host == domain || host.endsWith('.$domain'));
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
