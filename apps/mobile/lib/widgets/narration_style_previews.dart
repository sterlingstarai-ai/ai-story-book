import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

/// Injectable boundary for bundled, offline narration previews.
abstract class NarrationPreviewPlayer {
  Future<void> stop();
  Future<void> setAsset(String asset);
  Future<void> play();
  Future<void> dispose();
}

class _JustAudioNarrationPreviewPlayer implements NarrationPreviewPlayer {
  final AudioPlayer _player = AudioPlayer();
  @override
  Future<void> stop() => _player.stop();
  @override
  Future<void> setAsset(String asset) async {
    await _player.setAsset(asset);
  }

  @override
  Future<void> play() => _player.play();
  @override
  Future<void> dispose() => _player.dispose();
}

final narrationPreviewPlayerFactoryProvider =
    Provider<NarrationPreviewPlayer Function()>(
      (ref) => _JustAudioNarrationPreviewPlayer.new,
    );

class NarrationStylePreviews extends ConsumerStatefulWidget {
  const NarrationStylePreviews({super.key, required this.voice});

  final String voice;

  @override
  ConsumerState<NarrationStylePreviews> createState() =>
      _NarrationStylePreviewsState();
}

class _NarrationStylePreviewsState extends ConsumerState<NarrationStylePreviews>
    with AutomaticKeepAliveClientMixin {
  NarrationPreviewPlayer? _previewPlayer;
  int _previewEpoch = 0;
  Future<void> _previewQueue = Future<void>.value();
  bool _previewFailed = false;

  @override
  bool get wantKeepAlive => true;

  bool get _usesGoogleSamples =>
      ref
          .read(capabilitiesProvider)
          .valueOrNull?['narration_preview_provider'] ==
      'google_gemini';

  @override
  void dispose() {
    _previewEpoch++;
    final player = _previewPlayer;
    if (player != null) unawaited(_previewQueue.then((_) => player.dispose()));
    super.dispose();
  }

  Future<void> _playStylePreview(String style) {
    final epoch = ++_previewEpoch;
    if (_previewFailed) setState(() => _previewFailed = false);
    // Samples must match the configured provider; old OpenAI previews are
    // retained for existing deployments while Google uses its own recordings.
    final isGoogle = _usesGoogleSamples;
    final prefix = isGoogle
        ? (widget.voice == 'deep'
              ? 'narration_preview_google_male'
              : 'narration_preview_google')
        : 'narration_preview';
    final operation = _previewQueue.then((_) async {
      if (!mounted || epoch != _previewEpoch) return;
      try {
        final player = _previewPlayer ??= ref.read(
          narrationPreviewPlayerFactoryProvider,
        )();
        await player.stop();
        if (!mounted || epoch != _previewEpoch) return;
        await player.setAsset('assets/audio/${prefix}_$style.mp3');
        if (!mounted || epoch != _previewEpoch) return;
        unawaited(
          player.play().catchError((Object error) {
            if (mounted && epoch == _previewEpoch) {
              setState(() => _previewFailed = true);
            }
          }),
        );
      } catch (_) {
        if (mounted && epoch == _previewEpoch) {
          setState(() => _previewFailed = true);
        }
      }
    });
    _previewQueue = operation;
    return operation;
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final l = AppLocalizations.of(context);
    final usesGoogle = ref.watch(
      capabilitiesProvider.select(
        (caps) =>
            caps.valueOrNull?['narration_preview_provider'] == 'google_gemini',
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          usesGoogle
              ? l.settingsNarrationPreviewGoogleHelp
              : l.settingsNarrationPreviewHelp,
        ),
        if (_previewFailed)
          Semantics(
            liveRegion: true,
            child: Text(
              l.settingsNarrationPreviewError,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        for (final (style, label) in [
          ('natural', l.settingsNarrationStyleNatural),
          ('animated', l.settingsNarrationStyleAnimated),
          ('bedtime', l.settingsNarrationStyleBedtime),
        ])
          TextButton.icon(
            key: ValueKey('narration-preview-$style'),
            onPressed: () => unawaited(_playStylePreview(style)),
            icon: const Icon(Icons.play_arrow),
            label: Text(l.settingsNarrationPreview(label)),
            style: TextButton.styleFrom(
              minimumSize: const Size(64, AppSizing.minTouchTarget),
              alignment: Alignment.centerLeft,
            ),
          ),
      ],
    );
  }
}
