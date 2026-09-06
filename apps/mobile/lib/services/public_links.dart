import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

/// Public information pages may use a hosting provider's HTTPS address.
/// A missing address stays unavailable instead of opening an unowned domain.
class PublicLinks {
  PublicLinks({
    this.privacyPolicyUrl = const String.fromEnvironment('PRIVACY_POLICY_URL'),
    this.termsOfServiceUrl =
        const String.fromEnvironment('TERMS_OF_SERVICE_URL'),
    Future<bool> Function(Uri)? launch,
  }) : _launch = launch ?? _launchExternal;

  final String privacyPolicyUrl;
  final String termsOfServiceUrl;
  final Future<bool> Function(Uri) _launch;

  static Uri? publicUri(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    return uri;
  }

  static Future<bool> _launchExternal(Uri uri) =>
      launchUrl(uri, mode: LaunchMode.externalApplication);

  Future<bool> open(String value) async {
    final uri = publicUri(value);
    if (uri == null) return false;
    try {
      return await _launch(uri);
    } catch (_) {
      return false;
    }
  }
}

final publicLinksProvider = Provider<PublicLinks>((ref) => PublicLinks());
