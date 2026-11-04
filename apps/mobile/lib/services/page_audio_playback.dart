import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:just_audio/just_audio.dart';

/// The player boundary deliberately treats play() as a long-lived future.
/// just_audio completes it when playback finishes or pauses, not when it starts.
abstract class PageAudioPlayer {
  bool get completed;
  Future<void> loadFile(String path);
  Future<void> seek(Duration position);
  Future<void> play();
  Future<void> pause();
  Future<void> stop();
}

class JustAudioPagePlayer implements PageAudioPlayer {
  JustAudioPagePlayer(this.player);
  final AudioPlayer player;
  @override
  bool get completed => player.processingState == ProcessingState.completed;
  @override
  Future<void> loadFile(String path) async {
    await player.setFilePath(path);
  }

  @override
  Future<void> seek(Duration position) => player.seek(position);
  @override
  Future<void> play() => player.play();
  @override
  Future<void> pause() => player.pause();
  @override
  Future<void> stop() => player.stop();
}

String pageAudioCacheKey(
  String bookId,
  int page,
  String language,
  String text, {
  String voice = 'default',
  String style = 'legacy',
  String? provider,
}) =>
    'story_audio_${sha256.convert(utf8.encode('$bookId/$page/$language/$text${voice == 'default' ? '' : '/voice/$voice'}${style == 'legacy' ? '' : '/style/$style'}${provider == null || (voice == 'default' && style == 'legacy') ? '' : '/provider/$provider'}'))}';

/// Unknown provider values never become cache identifiers. Older servers do
/// not advertise a provider and continue using their historical cache keys.
String? narrationAudioProvider(Map<String, dynamic>? capabilities) {
  final value = capabilities?['narration_audio_provider'];
  return const {
        'mock',
        'openai',
        'openai_realtime',
        'google',
        'google_gemini',
        'elevenlabs',
      }.contains(value)
      ? value as String
      : null;
}

/// Older servers expose only the combined audio capability. A present but
/// invalid new value fails closed instead of falling back to the old flag.
bool narrationSupported(Map<String, dynamic>? capabilities) {
  if (capabilities == null) return false;
  if (capabilities.containsKey('narration_supported')) {
    return capabilities['narration_supported'] == true;
  }
  return capabilities['audio_supported'] == true;
}

/// Narrator choice is kept on this device and is never an impersonation of a
/// person. Unknown values fail back to the existing default narration.
const narrationStylePreferenceKey = 'narration_style_v1';
String narrationStyleOrDefault(String? value) =>
    const {'natural', 'animated', 'bedtime'}.contains(value)
    ? value!
    : 'legacy';

const narrationVoicePreferenceKey = 'narration_voice_v1';
String narrationVoiceOrDefault(String? value) =>
    value == 'warm' || value == 'deep' ? value! : 'default';

/// An offset from another synthesized voice/style/provider can skip text.
/// Old unscoped offsets are retained only for the historical default audio.
Duration narrationResumePosition(
  String? value, {
  required int page,
  required String language,
  required String voice,
  required String style,
  required String? provider,
}) {
  final saved = value?.split('|');
  if (saved == null ||
      saved.length < 3 ||
      saved.length > 6 ||
      saved[0] != '$page' ||
      saved[1] != language ||
      (saved.length == 3 ? voice != 'default' : saved[3] != voice) ||
      (saved.length < 5 ? style != 'legacy' : saved[4] != style) ||
      (saved.length < 6
          ? (voice != 'default' || style != 'legacy')
          : saved[5] != (provider ?? 'unknown'))) {
    return Duration.zero;
  }
  return Duration(
    milliseconds: (int.tryParse(saved[2]) ?? 0).clamp(0, 3600000),
  );
}

/// Uses the same bounded cache that account/photo erasure already purges.
/// A text change invalidates the audio; refreshed signed URLs do not.
Future<String> cachedPageAudio(
  String key,
  Future<String> Function() resolveUrl, {
  BaseCacheManager? cache,
  bool Function()? isCurrent,
  bool Function()? shouldRemoveLateFile,
  Future<String?> Function()? refreshRejectedUrl,
}) async {
  final manager = cache ?? DefaultCacheManager();
  void requireCurrent() {
    if (isCurrent != null && !isCurrent()) {
      throw StateError('Narration request is no longer active');
    }
  }

  requireCurrent();
  final cached = await manager.getFileFromCache(key);
  requireCurrent();
  if (cached != null && await cached.file.exists()) {
    requireCurrent();
    return cached.file.path;
  }
  requireCurrent();
  final url = await resolveUrl();
  requireCurrent();
  late final File file;
  try {
    file = await manager.getSingleFile(url, key: key);
  } on HttpExceptionWithStatus catch (error) {
    // A previously issued signed URL may be rejected before its advertised
    // expiry (for example after credential rotation). Refresh only once and
    // only when the caller knows the rejected URL came from a cached book.
    if (refreshRejectedUrl == null ||
        !const {401, 403, 404}.contains(error.statusCode)) {
      rethrow;
    }
    requireCurrent();
    final freshUrl = await refreshRejectedUrl();
    requireCurrent();
    if (freshUrl == null || freshUrl.isEmpty || freshUrl == url) rethrow;
    file = await manager.getSingleFile(freshUrl, key: key);
  }
  if (isCurrent != null && !isCurrent()) {
    // Erasure/route disposal can finish while a download is still in flight.
    // Remove the late file unless the caller says this shared cache key may
    // still be in use by a newer request.
    if (shouldRemoveLateFile?.call() ?? true) {
      await manager.removeFile(key);
    }
    throw StateError('Narration request is no longer active');
  }
  return file.path;
}

/// Cancels obsolete page/language loads and resumes a paused source in place.
class PageAudioPlayback extends ChangeNotifier {
  PageAudioPlayback(this.player, {required this.onError});
  final PageAudioPlayer player;
  final void Function(Object error) onError;
  bool _loading = false;
  bool _disposed = false;
  int _epoch = 0;
  int? _completedEpoch;
  String? _loadedKey;
  Future<void> _commands = Future<void>.value();

  bool get loading => _loading;
  bool get hasLoadedSource => _loadedKey != null;

  /// Native state changes can emit completion again while stopping a source.
  bool takeCompletion() {
    if (_disposed ||
        _loadedKey == null ||
        !player.completed ||
        _completedEpoch == _epoch) {
      return false;
    }
    _completedEpoch = _epoch;
    return true;
  }

  /// Capture from resolveFile while play() is active. A later stop, play or
  /// disposal invalidates this particular request even if the user returns to
  /// the same page and language.
  bool Function() captureRequestGuard() {
    final epoch = _epoch;
    return () => !_disposed && epoch == _epoch;
  }

  void _setLoading(bool value) {
    if (_disposed || _loading == value) return;
    _loading = value;
    notifyListeners();
  }

  Future<void> _serialized(Future<void> Function() command) {
    final result = _commands.then((_) => command());
    _commands = result.catchError((Object _) {});
    return result;
  }

  Future<void> play(
    String key,
    Future<String> Function() resolveFile, {
    bool restart = false,
    Duration initialPosition = Duration.zero,
  }) async {
    if (_disposed || _loading) return;
    final epoch = ++_epoch;
    _setLoading(true);
    try {
      final file = _loadedKey == key ? null : await resolveFile();
      if (_disposed || epoch != _epoch) return;
      await _serialized(() async {
        if (_disposed || epoch != _epoch) return;
        if (file != null) {
          await player.stop();
          if (_disposed || epoch != _epoch) return;
          await player.loadFile(file);
          if (_disposed || epoch != _epoch) return;
          _loadedKey = key;
          await player.seek(initialPosition);
        } else if (restart || player.completed) {
          await player.seek(Duration.zero);
        }
        if (_disposed || epoch != _epoch) return;
        // A playback error may arrive after this command has returned.
        unawaited(
          player.play().catchError((Object error) {
            if (!_disposed && epoch == _epoch) onError(error);
          }),
        );
      });
    } catch (error) {
      if (!_disposed && epoch == _epoch) onError(error);
    } finally {
      if (epoch == _epoch) _setLoading(false);
    }
  }

  Future<void> pause() => _serialized(player.pause);

  Future<void> stop() {
    ++_epoch;
    _loadedKey = null;
    _setLoading(false);
    return _serialized(player.stop);
  }

  @override
  void dispose() {
    _disposed = true;
    ++_epoch;
    super.dispose();
  }
}
