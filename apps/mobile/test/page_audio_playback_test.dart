import 'dart:async';
import 'dart:io';

import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:file/file.dart' as cache_fs;
import 'package:file/local.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_story_book/services/page_audio_playback.dart';

class _Player implements PageAudioPlayer {
  final loaded = <String>[];
  final seeks = <Duration>[];
  int plays = 0;
  int pauses = 0;
  int stops = 0;
  final playback = Completer<void>();
  @override
  bool completed = false;
  @override
  Future<void> loadFile(String path) async {
    loaded.add(path);
  }

  @override
  Future<void> seek(Duration position) async {
    seeks.add(position);
  }

  @override
  Future<void> play() {
    plays++;
    return playback.future;
  }

  @override
  Future<void> pause() async {
    pauses++;
  }

  @override
  Future<void> stop() async {
    stops++;
  }
}

class _Cache implements BaseCacheManager {
  _Cache(this.file);
  final File file;
  @override
  Future<FileInfo?> getFileFromCache(
    String key, {
    bool ignoreMemCache = false,
  }) async => FileInfo(
    const LocalFileSystem().file(file.path),
    FileSource.Cache,
    DateTime.now(),
    key,
  );
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _DelayedCache implements BaseCacheManager {
  _DelayedCache(this.file);
  final cache_fs.File file;
  final lookup = Completer<FileInfo?>();
  int downloads = 0;
  int removals = 0;
  final downloadStarted = Completer<void>();
  Completer<cache_fs.File>? downloadWait;
  @override
  Future<FileInfo?> getFileFromCache(
    String key, {
    bool ignoreMemCache = false,
  }) => lookup.future;
  @override
  Future<cache_fs.File> getSingleFile(
    String url, {
    String? key,
    Map<String, String>? headers,
  }) async {
    downloads++;
    if (!downloadStarted.isCompleted) downloadStarted.complete();
    return downloadWait == null ? file : await downloadWait!.future;
  }

  @override
  Future<void> removeFile(String key) async {
    removals++;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _RejectedUrlCache implements BaseCacheManager {
  _RejectedUrlCache(this.file, this.status);
  final cache_fs.File file;
  final int status;
  final calls = <String>[];
  @override
  Future<FileInfo?> getFileFromCache(
    String key, {
    bool ignoreMemCache = false,
  }) async => null;
  @override
  Future<cache_fs.File> getSingleFile(
    String url, {
    String? key,
    Map<String, String>? headers,
  }) async {
    calls.add(url);
    if (calls.length == 1) throw HttpExceptionWithStatus(status, 'rejected');
    return file;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test(
    'one completion advances each loaded narration, including after stop',
    () async {
      final player = _Player();
      final playback = PageAudioPlayback(
        player,
        onError: (error) => fail('$error'),
      );
      addTearDown(playback.dispose);

      await playback.play('page-1', () async => '/page-1.mp3');
      expect(playback.takeCompletion(), isFalse);
      player.completed = true;
      expect(playback.takeCompletion(), isTrue);
      expect(playback.takeCompletion(), isFalse);

      await playback.stop();
      expect(playback.takeCompletion(), isFalse);
      player.completed = false;
      await playback.play('page-2', () async => '/page-2.mp3');
      player.completed = true;
      expect(playback.takeCompletion(), isTrue);
      expect(playback.takeCompletion(), isFalse);
    },
  );

  test('rejected book audio refreshes once through authorized API', () async {
    final cache = _RejectedUrlCache(
      const LocalFileSystem().file('/unused.mp3'),
      403,
    );
    var refreshes = 0;
    final path = await cachedPageAudio(
      'key',
      () async => 'old',
      cache: cache,
      refreshRejectedUrl: () async {
        refreshes++;
        return 'fresh';
      },
    );
    expect(path, '/unused.mp3');
    expect(cache.calls, ['old', 'fresh']);
    expect(refreshes, 1);
  });

  test(
    'rejected audio is not retried if API denies access or page changed',
    () async {
      final cache = _RejectedUrlCache(
        const LocalFileSystem().file('/unused.mp3'),
        403,
      );
      await expectLater(
        cachedPageAudio(
          'key',
          () async => 'old',
          cache: cache,
          refreshRejectedUrl: () async => throw StateError('access denied'),
        ),
        throwsStateError,
      );
      expect(cache.calls, ['old']);
      final other = _RejectedUrlCache(
        const LocalFileSystem().file('/unused.mp3'),
        403,
      );
      var current = true;
      await expectLater(
        cachedPageAudio(
          'key',
          () async => 'old',
          cache: other,
          isCurrent: () => current,
          refreshRejectedUrl: () async {
            current = false;
            return 'fresh';
          },
        ),
        throwsStateError,
      );
      expect(other.calls, ['old']);
    },
  );

  test('server errors do not refresh or retry audio', () async {
    final cache = _RejectedUrlCache(
      const LocalFileSystem().file('/unused.mp3'),
      500,
    );
    var refreshes = 0;
    await expectLater(
      cachedPageAudio(
        'key',
        () async => 'old',
        cache: cache,
        refreshRejectedUrl: () async {
          refreshes++;
          return 'fresh';
        },
      ),
      throwsA(isA<HttpExceptionWithStatus>()),
    );
    expect(cache.calls, ['old']);
    expect(refreshes, 0);
  });
  test(
    'resume offset is scoped to provider and preserves old default audio',
    () {
      Duration read(
        String saved, {
        required String voice,
        required String style,
        required String? provider,
      }) => narrationResumePosition(
        saved,
        page: 1,
        language: 'ko',
        voice: voice,
        style: style,
        provider: provider,
      );
      expect(
        read(
          '1|ko|4300|warm|natural|google_gemini',
          voice: 'warm',
          style: 'natural',
          provider: 'google_gemini',
        ),
        const Duration(milliseconds: 4300),
      );
      expect(
        read(
          '1|ko|4300|warm|natural|openai',
          voice: 'warm',
          style: 'natural',
          provider: 'google_gemini',
        ),
        Duration.zero,
      );
      expect(
        read(
          '1|ko|4300|warm|natural',
          voice: 'warm',
          style: 'natural',
          provider: 'google_gemini',
        ),
        Duration.zero,
      );
      expect(
        read(
          '1|ko|4300',
          voice: 'default',
          style: 'legacy',
          provider: 'google_gemini',
        ),
        const Duration(milliseconds: 4300),
      );
    },
  );
  test('provider change does not reuse a different provider recording', () {
    final old = pageAudioCacheKey(
      'b',
      1,
      'ko',
      'story',
      voice: 'warm',
      style: 'natural',
      provider: 'openai',
    );
    final google = pageAudioCacheKey(
      'b',
      1,
      'ko',
      'story',
      voice: 'warm',
      style: 'natural',
      provider: 'google_gemini',
    );
    expect(google, isNot(old));
    expect(
      narrationAudioProvider({'narration_audio_provider': 'google_gemini'}),
      'google_gemini',
    );
    expect(
      narrationAudioProvider({'narration_audio_provider': 'invalid'}),
      isNull,
    );
    expect(narrationAudioProvider(null), isNull);
    expect(
      pageAudioCacheKey('b', 1, 'ko', 'story', provider: null),
      pageAudioCacheKey('b', 1, 'ko', 'story'),
    );
    // The default legacy slot is the same persisted recording even if the
    // backend's active generator changes, so retain its offline cache.
    expect(
      pageAudioCacheKey('b', 1, 'ko', 'story', provider: 'google_gemini'),
      pageAudioCacheKey('b', 1, 'ko', 'story'),
    );
  });
  test(
    'narration capability preserves old servers and fails closed on invalid new values',
    () {
      expect(narrationSupported({'audio_supported': true}), isTrue);
      expect(
        narrationSupported({
          'audio_supported': false,
          'narration_supported': true,
        }),
        isTrue,
      );
      expect(
        narrationSupported({
          'audio_supported': true,
          'narration_supported': false,
        }),
        isFalse,
      );
      expect(
        narrationSupported({
          'audio_supported': true,
          'narration_supported': null,
        }),
        isFalse,
      );
      expect(narrationSupported(null), isFalse);
    },
  );
  test('voice selection never reuses another narrator cache', () {
    final base = pageAudioCacheKey('b', 1, 'ko', 'story');
    final warm = pageAudioCacheKey('b', 1, 'ko', 'story', voice: 'warm');
    final deep = pageAudioCacheKey('b', 1, 'ko', 'story', voice: 'deep');
    expect({base, warm, deep}.length, 3);
    expect(pageAudioCacheKey('b', 1, 'ko', 'story', voice: 'default'), base);
    expect(narrationVoiceOrDefault('warm'), 'warm');
    expect(narrationVoiceOrDefault('deep'), 'deep');
    expect(narrationVoiceOrDefault('unknown'), 'default');
  });
  test('playback begins without waiting for the entire narration', () async {
    final player = _Player();
    final audio = PageAudioPlayback(player, onError: (_) => fail('unexpected'));
    await audio.play('page1', () async => '/page1.mp3');
    expect(player.plays, 1);
    expect(player.playback.isCompleted, false);
    expect(audio.loading, false);
    await audio.pause();
    expect(player.pauses, 1);
    audio.dispose();
  });

  test('pause and play resumes in place without a new fetch or seek', () async {
    final player = _Player();
    final audio = PageAudioPlayback(player, onError: (_) => fail('unexpected'));
    await audio.play('page1', () async => '/page1.mp3');
    await audio.pause();
    await audio.play('page1', () async => throw StateError('refetched'));
    expect(player.loaded, ['/page1.mp3']);
    expect(player.seeks, [Duration.zero]);
    expect(player.plays, 2);
    audio.dispose();
  });

  test(
    'completion replays from zero and reopening restores saved position',
    () async {
      final player = _Player();
      final audio = PageAudioPlayback(
        player,
        onError: (_) => fail('unexpected'),
      );
      await audio.play(
        'page1',
        () async => '/page1.mp3',
        initialPosition: const Duration(seconds: 8),
      );
      player.completed = true;
      await audio.play('page1', () async => '/page1.mp3');
      expect(player.seeks, [const Duration(seconds: 8), Duration.zero]);
      audio.dispose();
    },
  );

  test(
    'turning the page cancels a delayed old page before it can play',
    () async {
      final player = _Player();
      final audio = PageAudioPlayback(
        player,
        onError: (_) => fail('unexpected'),
      );
      final old = Completer<String>();
      final pending = audio.play('page1', () => old.future);
      await audio.stop();
      await audio.play('page2', () async => '/page2.mp3');
      old.complete('/page1.mp3');
      await pending;
      expect(player.loaded, ['/page2.mp3']);
      expect(player.plays, 1);
      audio.dispose();
    },
  );

  test('duplicate taps during generation start only one request', () async {
    final player = _Player();
    final audio = PageAudioPlayback(player, onError: (_) => fail('unexpected'));
    final pending = Completer<String>();
    final first = audio.play('page1', () => pending.future);
    await audio.play('page1', () async => throw StateError('duplicate'));
    pending.complete('/page1.mp3');
    await first;
    expect(player.plays, 1);
    audio.dispose();
  });

  test(
    'disposing during a request prevents late playback and error UI',
    () async {
      final player = _Player();
      final errors = <Object>[];
      final audio = PageAudioPlayback(player, onError: errors.add);
      final pending = Completer<String>();
      final first = audio.play('page1', () => pending.future);
      audio.dispose();
      pending.completeError(StateError('offline'));
      await first;
      expect(player.plays, 0);
      expect(errors, isEmpty);
    },
  );

  test('failure clears loading and lets the reader retry', () async {
    final player = _Player();
    final errors = <Object>[];
    final audio = PageAudioPlayback(player, onError: errors.add);
    await audio.play('page1', () async => throw StateError('offline'));
    expect(errors, hasLength(1));
    expect(audio.loading, false);
    await audio.play('page1', () async => '/page1.mp3');
    expect(player.plays, 1);
    audio.dispose();
  });

  test('already cached narration works without network resolution', () async {
    final directory = await Directory.systemTemp.createTemp(
      'story-audio-test-',
    );
    final file = await File(
      '${directory.path}/page.mp3',
    ).writeAsBytes([1, 2, 3]);
    try {
      final path = await cachedPageAudio(
        'key',
        () async => throw StateError('network is offline'),
        cache: _Cache(file),
      );
      expect(path, file.path);
      expect(
        pageAudioCacheKey('b', 1, 'ko', 'one'),
        isNot(pageAudioCacheKey('b', 1, 'ko', 'two')),
      );
      expect(
        pageAudioCacheKey('b', 1, 'ko', 'one'),
        isNot(pageAudioCacheKey('b', 1, 'en', 'one')),
      );
    } finally {
      await directory.delete(recursive: true);
    }
  });

  test('obsolete request must not return a delayed cached file', () async {
    final directory = await Directory.systemTemp.createTemp(
      'story-audio-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final file = await File(
      '${directory.path}/page.mp3',
    ).writeAsBytes([1, 2, 3]);
    final cache = _DelayedCache(const LocalFileSystem().file(file.path));
    var current = true;
    final future = cachedPageAudio(
      'key',
      () async => 'https://example.invalid/',
      cache: cache,
      isCurrent: () => current,
    );
    final result = expectLater(future, throwsStateError);
    current = false;
    cache.lookup.complete(
      FileInfo(cache.file, FileSource.Cache, DateTime.now(), 'key'),
    );
    await result;
    expect(cache.downloads, 0);
  });

  test(
    'obsolete request does not download after delayed URL resolution',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'story-audio-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final file = await File(
        '${directory.path}/page.mp3',
      ).writeAsBytes([1, 2, 3]);
      final cache = _DelayedCache(const LocalFileSystem().file(file.path));
      cache.lookup.complete(null);
      final requested = Completer<void>();
      final resolved = Completer<String>();
      var current = true;
      final future = cachedPageAudio(
        'key',
        () {
          requested.complete();
          return resolved.future;
        },
        cache: cache,
        isCurrent: () => current,
      );
      final result = expectLater(future, throwsStateError);
      await requested.future;
      current = false;
      resolved.complete('https://example.invalid/audio.mp3');
      await result;
      expect(cache.downloads, 0);
    },
  );

  test('obsolete cache miss does not start URL resolution', () async {
    final directory = await Directory.systemTemp.createTemp(
      'story-audio-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final file = const LocalFileSystem().file('${directory.path}/page.mp3');
    final cache = _DelayedCache(file);
    var current = true;
    var resolved = false;
    final future = cachedPageAudio(
      'key',
      () async {
        resolved = true;
        return 'https://example.invalid/audio.mp3';
      },
      cache: cache,
      isCurrent: () => current,
    );
    final result = expectLater(future, throwsStateError);
    current = false;
    cache.lookup.complete(null);
    await result;
    expect(resolved, false);
    expect(cache.downloads, 0);
  });

  test('returning to the same page does not revive the old download', () async {
    final directory = await Directory.systemTemp.createTemp(
      'story-audio-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final file = const LocalFileSystem().file('${directory.path}/page.mp3');
    final cache = _DelayedCache(file)..lookup.complete(null);
    final requested = Completer<void>();
    final resolved = Completer<String>();
    final player = _Player();
    final errors = <Object>[];
    final audio = PageAudioPlayback(player, onError: errors.add);
    addTearDown(audio.dispose);
    final oldRequest = audio.play('page1', () {
      final isCurrent = audio.captureRequestGuard();
      return cachedPageAudio(
        'page1',
        () {
          requested.complete();
          return resolved.future;
        },
        cache: cache,
        isCurrent: isCurrent,
      );
    });
    await requested.future;
    await audio.stop();
    await audio.play('page1', () async => '/new-page1.mp3');
    resolved.complete('https://example.invalid/audio.mp3');
    await oldRequest;
    expect(cache.downloads, 0);
    expect(player.loaded, ['/new-page1.mp3']);
    expect(player.plays, 1);
    expect(errors, isEmpty);
  });

  test(
    'a download already running at cancellation removes its late file',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'story-audio-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final file = const LocalFileSystem().file('${directory.path}/page.mp3');
      final cache = _DelayedCache(file)
        ..lookup.complete(null)
        ..downloadWait = Completer<cache_fs.File>();
      var current = true;
      final future = cachedPageAudio(
        'key',
        () async => 'https://example.invalid/audio.mp3',
        cache: cache,
        isCurrent: () => current,
      );
      final result = expectLater(future, throwsStateError);
      await cache.downloadStarted.future;
      current = false;
      cache.downloadWait!.complete(file);
      await result;
      expect(cache.removals, 1);
    },
  );

  test(
    'late old request preserves a cache file needed by the returned page',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'story-audio-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final file = const LocalFileSystem().file('${directory.path}/page.mp3');
      final cache = _DelayedCache(file)
        ..lookup.complete(null)
        ..downloadWait = Completer<cache_fs.File>();
      var current = true;
      final future = cachedPageAudio(
        'key',
        () async => 'https://example.invalid/audio.mp3',
        cache: cache,
        isCurrent: () => current,
        shouldRemoveLateFile: () => false,
      );
      final result = expectLater(future, throwsStateError);
      await cache.downloadStarted.future;
      current = false;
      cache.downloadWait!.complete(file);
      await result;
      expect(cache.removals, 0);
    },
  );
}
