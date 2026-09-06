/// S3 credentials expire independently of the book. Refresh before playback/viewing.
bool mediaUrlNeedsRefresh(String? value, {DateTime? now}) {
  final uri = value == null ? null : Uri.tryParse(value);
  if (uri == null) return false;
  final date = uri.queryParameters['X-Amz-Date'];
  final seconds = int.tryParse(uri.queryParameters['X-Amz-Expires'] ?? '');
  if (date == null || seconds == null) return false;
  final issued = DateTime.tryParse(date);
  if (issued == null) return true;
  return !issued.add(Duration(seconds: seconds)).isAfter(
        (now ?? DateTime.now()).toUtc().add(const Duration(minutes: 2)),
      );
}
