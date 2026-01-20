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

    // Production URL
    return const String.fromEnvironment(
      'PROD_API_URL',
      defaultValue: 'https://api.storybook.example.com',
    );
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
