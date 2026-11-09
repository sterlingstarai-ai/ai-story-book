/// S3 credentials expire independently of the book. Refresh before playback/viewing.
bool mediaUrlNeedsRefresh(String? value, {DateTime? now}) {
  final uri = value == null ? null : Uri.tryParse(value);
  if (uri == null) return false;
  final date = uri.queryParameters['X-Amz-Date'];
  final seconds = int.tryParse(uri.queryParameters['X-Amz-Expires'] ?? '');
  if (date == null || seconds == null) return false;
  final issued = DateTime.tryParse(date);
  if (issued == null) return true;
  return !issued
      .add(Duration(seconds: seconds))
      .isAfter((now ?? DateTime.now()).toUtc().add(const Duration(minutes: 2)));
}

bool hasS3MediaSignature(String value) =>
    Uri.tryParse(value)?.queryParameters.containsKey('X-Amz-Signature') ??
    false;

final _generatedIllustration = RegExp(
  r'/(?:jobs/[^/]+/|images/(?:[^/]+/)+|books/[^/]+/edits/[^/]+/)'
  r'[a-f0-9]{32}\.(?:png|jpe?g|webp)$',
);
const _s3SigningParameters = {
  'X-Amz-Algorithm',
  'X-Amz-Credential',
  'X-Amz-Date',
  'X-Amz-Expires',
  'X-Amz-Security-Token',
  'X-Amz-Signature',
  'X-Amz-SignedHeaders',
};

/// Generated illustrations use a new UUID filename for each replacement.
/// Strip rotating S3 credentials only for those immutable object URLs.
String illustrationCacheIdentity(String url) {
  final uri = Uri.tryParse(url);
  if (uri == null ||
      !const {'http', 'https'}.contains(uri.scheme) ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      !_generatedIllustration.hasMatch(uri.path)) {
    return url;
  }
  final remaining = <String>[];
  final signing = <String, String>{};
  for (final part in uri.query.split('&')) {
    final separator = part.indexOf('=');
    final name = separator < 0 ? part : part.substring(0, separator);
    if (!_s3SigningParameters.contains(name)) {
      remaining.add(part);
      continue;
    }
    if (separator < 0 || signing.containsKey(name)) return url;
    signing[name] = part.substring(separator + 1);
  }
  if (signing['X-Amz-Algorithm'] != 'AWS4-HMAC-SHA256' ||
      (signing['X-Amz-Signature'] ?? '').isEmpty) {
    return url;
  }
  return uri.replace(query: remaining.join('&')).toString();
}
