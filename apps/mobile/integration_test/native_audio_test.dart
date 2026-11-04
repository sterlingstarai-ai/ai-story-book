// Real native audio plugin lifecycle, independent of provider billing/voices.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:ai_story_book/services/page_audio_playback.dart';
import 'package:audio_session/audio_session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';

Uint8List _silentWave() {
  const sampleRate = 16000;
  const dataLength = sampleRate * 2 * 4;
  final bytes = Uint8List(44 + dataLength);
  final data = ByteData.sublistView(bytes);
  void label(int offset, String value) => bytes.setAll(offset, value.codeUnits);
  label(0, 'RIFF');
  data.setUint32(4, 36 + dataLength, Endian.little);
  label(8, 'WAVE');
  label(12, 'fmt ');
  data.setUint32(16, 16, Endian.little);
  data.setUint16(20, 1, Endian.little);
  data.setUint16(22, 1, Endian.little);
  data.setUint32(24, sampleRate, Endian.little);
  data.setUint32(28, sampleRate * 2, Endian.little);
  data.setUint16(32, 2, Endian.little);
  data.setUint16(34, 16, Endian.little);
  label(36, 'data');
  data.setUint32(40, dataLength, Endian.little);
  return bytes;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native narration loads, pauses, resumes and stops on page change',
    (tester) async {
      final directory = await getTemporaryDirectory();
      // Optional generic provider sample for credentialed release checks.
      // Ordinary tests retain the offline WAV fixture and never call a provider.
      const sample = String.fromEnvironment('NATIVE_AUDIO_SAMPLE_BASE64');
      final extension = sample.isEmpty ? 'wav' : 'mp3';
      final file = File(
        '${directory.path}/native_audio_${DateTime.now().microsecondsSinceEpoch}.$extension',
      );
      await file.writeAsBytes(
        sample.isEmpty ? _silentWave() : base64Decode(sample),
      );
      final native = AudioPlayer();
      final errors = <Object>[];
      final playback = PageAudioPlayback(
        JustAudioPagePlayer(native),
        onError: errors.add,
      );
      try {
        final session = await AudioSession.instance;
        await session.configure(const AudioSessionConfiguration.speech());
        await playback.play(
          'first',
          () async => file.path,
          initialPosition: const Duration(seconds: 1),
        );
        await Future<void>.delayed(const Duration(milliseconds: 700));
        expect(playback.loading, false);
        expect(native.playing, true);
        expect(native.position.inMilliseconds, greaterThanOrEqualTo(1000));
        await playback.pause();
        final paused = native.position;
        expect(native.playing, false);
        await Future<void>.delayed(const Duration(milliseconds: 200));
        expect((native.position - paused).inMilliseconds.abs(), lessThan(100));
        await playback.play(
          'first',
          () async => throw StateError('unexpected reload'),
        );
        await Future<void>.delayed(const Duration(milliseconds: 300));
        expect(native.playing, true);
        expect(native.position, greaterThanOrEqualTo(paused));
        await playback.stop();
        expect(native.playing, false);
        expect(errors, isEmpty);
      } finally {
        playback.dispose();
        await native.dispose();
        await file.delete();
      }
    },
    skip: !Platform.isIOS && !Platform.isAndroid,
  );

  testWidgets(
    'native player decodes and advances all bundled narrator previews',
    (tester) async {
      final player = AudioPlayer();
      final errors = <Object>[];
      try {
        for (final prefix in [
          'narration_preview',
          'narration_preview_google',
          'narration_preview_google_male',
        ]) {
          for (final style in ['natural', 'animated', 'bedtime']) {
            final asset = 'assets/audio/${prefix}_$style.mp3';
            final duration = await player.setAsset(asset);
            expect(
              duration,
              greaterThan(const Duration(seconds: 1)),
              reason: asset,
            );
            final progress = player.positionStream.firstWhere(
              (position) => position >= const Duration(milliseconds: 250),
            );
            unawaited(player.play().catchError(errors.add));
            await progress.timeout(const Duration(seconds: 8));
            expect(player.playing, isTrue, reason: asset);
            await player.stop();
            expect(player.playing, isFalse, reason: asset);
          }
        }
        expect(errors, isEmpty);
      } finally {
        await player.dispose();
      }
    },
    skip: !Platform.isIOS && !Platform.isAndroid,
  );
}
