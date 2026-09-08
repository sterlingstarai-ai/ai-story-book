import 'dart:async';
import 'dart:io';

import 'package:flutter_cache_manager/flutter_cache_manager.dart';
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

void main() {
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
}
