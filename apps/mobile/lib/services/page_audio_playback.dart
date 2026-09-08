import 'dart:async';
import 'dart:convert';

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
  String text,
) =>
    'story_audio_${sha256.convert(utf8.encode('$bookId/$page/$language/$text'))}';

/// Uses the same bounded cache that account/photo erasure already purges.
/// A text change invalidates the audio; refreshed signed URLs do not.
Future<String> cachedPageAudio(
  String key,
  Future<String> Function() resolveUrl, {
  BaseCacheManager? cache,
  bool Function()? isCurrent,
}) async {
  final manager = cache ?? DefaultCacheManager();
  final cached = await manager.getFileFromCache(key);
  if (cached != null && await cached.file.exists()) return cached.file.path;
  final file = await manager.getSingleFile(await resolveUrl(), key: key);
  if (isCurrent != null && !isCurrent()) {
    // Erasure/route disposal can finish while a download is still in flight.
    // Remove this late file instead of repopulating the cleared media cache.
    await manager.removeFile(key);
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
  String? _loadedKey;
  Future<void> _commands = Future<void>.value();

  bool get loading => _loading;
  bool get hasLoadedSource => _loadedKey != null;

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
