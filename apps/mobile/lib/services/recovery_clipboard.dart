import 'package:flutter/services.dart';

/// Native-only credential copy: no fallback to the unprotected system channel.
/// The native side expires copies after 60 seconds and clears only its own item.
class RecoveryClipboard {
  static const _channel = MethodChannel('ai_story_book/security');
  String? _token;
  bool _disposed = false;

  Future<void> copy(String code) async {
    if (_disposed) return;
    final token = await _channel.invokeMethod<String>('copyRecoveryCode', code);
    if (token == null) throw StateError('Recovery clipboard unavailable');
    _token = token;
    // A screen can close while the platform copy is in flight.
    if (_disposed) await clear();
  }

  Future<void> clear() async {
    final token = _token;
    if (token == null) return;
    await _channel.invokeMethod<void>('clearRecoveryCode', token);
    if (_token == token) _token = null;
  }

  Future<void> dispose() async {
    _disposed = true;
    await clear();
  }
}
