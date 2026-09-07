import 'dart:async';

import 'package:dio/dio.dart';
import '../core/api_error.dart';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../models/character.dart';
import '../providers/providers.dart';
import '../services/api_client.dart';
import '../utils/constants.dart';
import 'age_gate_dialog.dart';

class CharacterAvatarPollPolicy {
  const CharacterAvatarPollPolicy({
    this.interval = const Duration(seconds: 2),
    this.timeout = const Duration(minutes: 6),
    this.maxAttempts = 180,
  });
  final Duration interval;
  final Duration timeout;
  final int maxAttempts;
}

final characterAvatarPollPolicyProvider = Provider<CharacterAvatarPollPolicy>(
  (ref) => const CharacterAvatarPollPolicy(),
);

class CharacterAvatarPreviewResult {
  const CharacterAvatarPreviewResult.approved(this.character)
    : chooseAnotherPhoto = false;
  const CharacterAvatarPreviewResult.anotherPhoto()
    : character = null,
      chooseAnotherPhoto = true;
  final Character? character;
  final bool chooseAnotherPhoto;
}

Future<CharacterAvatarPreviewResult?> showCharacterAvatarPreview(
  BuildContext context, {
  required String characterId,
  Character? initialCharacter,
}) {
  if (initialCharacter?.canUseInBook == true) {
    return Future.value(
      CharacterAvatarPreviewResult.approved(initialCharacter),
    );
  }
  return Navigator.of(context).push<CharacterAvatarPreviewResult>(
    MaterialPageRoute(
      builder: (_) => CharacterAvatarPreviewScreen(
        characterId: characterId,
        initialCharacter: initialCharacter,
      ),
    ),
  );
}

String characterAvatarStatusLabel(AppLocalizations l, Character character) =>
    switch (character.avatarStatus) {
      CharacterAvatarStatus.generating => l.characterAvatarGeneratingLabel,
      CharacterAvatarStatus.preview => l.characterAvatarPreviewLabel,
      CharacterAvatarStatus.approved => l.characterAvatarApprovedLabel,
      CharacterAvatarStatus.failed => l.characterAvatarFailedLabel,
      CharacterAvatarStatus.notRequired =>
        character.fromPhoto ? l.characterAvatarFailedLabel : '',
    };

String characterDisplayDescription(AppLocalizations l, Character character) {
  if (!character.needsAvatarApproval) return character.masterDescription;
  if (character.canUseInBook) return l.characterAvatarApprovedDescription;
  return switch (character.avatarStatus) {
    CharacterAvatarStatus.generating => l.characterAvatarPreparingDescription,
    CharacterAvatarStatus.preview => l.characterAvatarNeedsApproval,
    _ => l.characterAvatarFailedDescription,
  };
}

class CharacterAvatarThumbnail extends StatelessWidget {
  const CharacterAvatarThumbnail({
    super.key,
    required this.character,
    this.size = 60,
  });
  final Character character;
  final double size;
  @override
  Widget build(BuildContext context) {
    final url = character.avatarUrl;
    Widget placeholder() => Center(
      child: Icon(
        character.needsAvatarApproval
            ? Icons.face_retouching_natural
            : Icons.person_outline,
        color: AppPalette.of(context).primary,
        size: size * .48,
      ),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Container(
        width: size,
        height: size,
        color: AppPalette.of(context).primaryLight,
        child: url?.isNotEmpty == true
            ? Image.network(
                url!,
                fit: BoxFit.cover,
                excludeFromSemantics: true,
                errorBuilder: (_, __, ___) => placeholder(),
                loadingBuilder: (_, child, progress) =>
                    progress == null ? child : placeholder(),
              )
            : placeholder(),
      ),
    );
  }
}

class CharacterAvatarPreviewScreen extends ConsumerStatefulWidget {
  const CharacterAvatarPreviewScreen({
    super.key,
    required this.characterId,
    this.initialCharacter,
    this.imageProviderBuilder,
  });
  final String characterId;
  final Character? initialCharacter;
  final ImageProvider Function(String)? imageProviderBuilder;
  @override
  ConsumerState<CharacterAvatarPreviewScreen> createState() =>
      _CharacterAvatarPreviewScreenState();
}

class _CharacterAvatarPreviewScreenState
    extends ConsumerState<CharacterAvatarPreviewScreen> {
  late final ApiClient _api;
  late final CharacterAvatarPollPolicy _policy;
  Character? _character;
  Timer? _pollTimer;
  Timer? _deadline;
  int _requestSerial = 0;
  int _pollAttempts = 0;
  int _imageReload = 0;
  bool _fetching = false;
  bool _mutating = false;
  bool _imageLoaded = false;
  bool _imageFailed = false;
  String? _error;

  bool get _sameScope =>
      mounted && identical(_api, ref.read(apiClientProvider));

  @override
  void initState() {
    super.initState();
    _api = ref.read(apiClientProvider);
    _policy = ref.read(characterAvatarPollPolicyProvider);
    _character = widget.initialCharacter;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _restartPolling();
    });
  }

  @override
  void dispose() {
    _stopPolling();
    _requestSerial++;
    super.dispose();
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _deadline?.cancel();
  }

  void _restartPolling() {
    if (!_sameScope || _mutating || _fetching) return;
    _stopPolling();
    _pollAttempts = 0;
    setState(() {
      _error = null;
      if (_imageFailed) {
        final url = _character?.avatarUrl;
        if (url != null) {
          unawaited(
            (widget.imageProviderBuilder?.call(url) ?? NetworkImage(url))
                .evict(),
          );
        }
        _imageLoaded = false;
        _imageReload++;
      }
      _imageFailed = false;
    });
    _deadline = Timer(_policy.timeout, _pausePolling);
    unawaited(_refresh());
  }

  void _pausePolling() {
    if (!mounted) return;
    _stopPolling();
    _requestSerial++;
    setState(() {
      _fetching = false;
      _error = AppLocalizations.of(context).characterAvatarTakingLong;
    });
  }

  void _setCharacter(Character character) {
    if (character.id != widget.characterId) {
      throw const FormatException('Character scope mismatch');
    }
    final changed =
        character.avatarVersion != _character?.avatarVersion ||
        character.avatarUrl != _character?.avatarUrl;
    setState(() {
      _character = character;
      if (changed) {
        _imageLoaded = false;
        _imageFailed = false;
      }
    });
  }

  Future<void> _refresh() async {
    if (!_sameScope || _fetching || _mutating) return;
    if (_pollAttempts >= _policy.maxAttempts) {
      _pausePolling();
      return;
    }
    final serial = ++_requestSerial;
    _pollAttempts++;
    setState(() => _fetching = true);
    try {
      final next = await _api.getCharacter(widget.characterId);
      if (!mounted || !_sameScope || serial != _requestSerial) return;
      _setCharacter(next);
      if (next.canUseInBook) {
        _stopPolling();
        Navigator.pop(context, CharacterAvatarPreviewResult.approved(next));
      } else if (next.avatarStatus == CharacterAvatarStatus.generating) {
        _pollTimer = Timer(_policy.interval, () => unawaited(_refresh()));
      } else {
        _stopPolling();
      }
    } catch (_) {
      if (_sameScope && serial == _requestSerial) {
        _stopPolling();
        setState(
          () => _error = AppLocalizations.of(context).characterAvatarLoadError,
        );
      }
    } finally {
      if (mounted && serial == _requestSerial) {
        setState(() => _fetching = false);
      }
    }
  }

  Future<void> _updateAvatar({required bool approve}) async {
    final character = _character;
    if (!_sameScope ||
        _mutating ||
        _fetching ||
        character == null ||
        character.avatarVersion < 1) {
      return;
    }
    if (approve &&
        (character.avatarStatus != CharacterAvatarStatus.preview ||
            !_imageLoaded ||
            _imageFailed)) {
      return;
    }
    if (!approve &&
        (!character.avatarRetryAllowed ||
            character.avatarStatus == CharacterAvatarStatus.generating)) {
      return;
    }
    setState(() {
      _mutating = true;
      _error = null;
    });
    _stopPolling();
    try {
      if (!await ensureAgeGate(context, ref) || !_sameScope) return;
      final updated = approve
          ? await _api.approveCharacterAvatar(
              character.id,
              version: character.avatarVersion,
            )
          : await _api.regenerateCharacterAvatar(
              character.id,
              version: character.avatarVersion,
            );
      if (!mounted || !_sameScope) return;
      _setCharacter(updated);
      ref.invalidate(charactersProvider);
      if (approve &&
          updated.canUseInBook &&
          updated.avatarVersion == character.avatarVersion) {
        Navigator.pop(context, CharacterAvatarPreviewResult.approved(updated));
      } else if (approve) {
        setState(
          () => _error = AppLocalizations.of(context).characterAvatarChanged,
        );
      }
    } catch (error) {
      if (_sameScope) {
        // A version conflict or lost mutation response must reload server state;
        // never automatically repeat an approval or a paid regeneration.
        try {
          final latest = await _api.getCharacter(widget.characterId);
          if (!mounted || !_sameScope) return;
          _setCharacter(latest);
          if (approve &&
              latest.canUseInBook &&
              latest.avatarVersion == character.avatarVersion) {
            ref.invalidate(charactersProvider);
            Navigator.pop(
              context,
              CharacterAvatarPreviewResult.approved(latest),
            );
            return;
          }
        } catch (_) {}
        if (_sameScope) {
          final l = AppLocalizations.of(context);
          final apiError = error is ApiError
              ? error
              : error is DioException
              ? error.error is ApiError
                    ? error.error as ApiError
                    : ApiError.fromDioException(error)
              : null;
          setState(
            () => _error = apiError?.statusCode == 409
                ? l.characterAvatarChanged
                : apiError?.localizedMessage(l) ?? l.characterAvatarUpdateError,
          );
        }
      }
    } finally {
      if (mounted) {
        setState(() => _mutating = false);
        if (_character?.avatarStatus == CharacterAvatarStatus.generating) {
          _restartPolling();
        }
      }
    }
  }

  void _imageState(String url, int version, {required bool loaded}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          _character?.avatarUrl != url ||
          _character?.avatarVersion != version) {
        return;
      }
      if (_imageLoaded == loaded && _imageFailed == !loaded) return;
      setState(() {
        _imageLoaded = loaded;
        _imageFailed = !loaded;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final sameScope = identical(ref.watch(apiClientProvider), _api);
    final character = _character;
    final isGenerating =
        character == null ||
        character.avatarStatus == CharacterAvatarStatus.generating;
    final url = character?.avatarUrl;
    final preview = character?.avatarStatus == CharacterAvatarStatus.preview;
    return PopScope(
      canPop: !_mutating,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.characterAvatarTitle),
          leading: IconButton(
            tooltip: l.libraryClose,
            onPressed: _mutating ? null : () => Navigator.pop(context),
            icon: const Icon(Icons.close),
          ),
        ),
        body: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!sameScope)
                  Text(l.characterAvatarLoadError)
                else ...[
                  Text(
                    character?.name ?? l.characterAvatarGeneratingLabel,
                    style: AppTextStyles.heading2,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    isGenerating
                        ? l.characterAvatarGeneratingBody
                        : l.characterAvatarPreviewBody,
                    style: AppTextStyles.bodySmall,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(l.consentScrollHint, style: AppTextStyles.caption),
                  const SizedBox(height: AppSpacing.lg),
                  if (url?.isNotEmpty == true && !isGenerating) ...[
                    ClipRRect(
                      borderRadius: BorderRadius.circular(AppRadius.lg),
                      child: AspectRatio(
                        aspectRatio: 1,
                        child: Image(
                          image:
                              widget.imageProviderBuilder?.call(url!) ??
                              NetworkImage(url!),
                          key: ValueKey(
                            '${character.avatarVersion}:$url:$_imageReload',
                          ),
                          fit: BoxFit.contain,
                          semanticLabel: l.characterAvatarImageLabel,
                          frameBuilder: (context, child, frame, synchronous) {
                            if (frame != null || synchronous) {
                              _imageState(
                                url!,
                                character.avatarVersion,
                                loaded: true,
                              );
                            }
                            return child;
                          },
                          errorBuilder: (_, __, ___) {
                            _imageState(
                              url!,
                              character.avatarVersion,
                              loaded: false,
                            );
                            return Center(
                              child: Text(
                                l.characterAvatarImageError,
                                textAlign: TextAlign.center,
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                  ] else if (isGenerating && _error == null) ...[
                    const SizedBox(height: 32),
                    const Center(child: CircularProgressIndicator()),
                    const SizedBox(height: 32),
                  ] else if (!isGenerating) ...[
                    const Icon(Icons.image_not_supported_outlined, size: 64),
                    const SizedBox(height: AppSpacing.md),
                    Text(
                      l.characterAvatarFailedBody,
                      style: AppTextStyles.body,
                    ),
                  ],
                  if (_error != null || _imageFailed) ...[
                    Semantics(
                      liveRegion: true,
                      child: Text(
                        _error ?? l.characterAvatarImageError,
                        style: AppTextStyles.bodySmall,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),
                    OutlinedButton(
                      onPressed: _fetching || _mutating
                          ? null
                          : _restartPolling,
                      child: Text(l.retry),
                    ),
                  ],
                  if (preview)
                    FilledButton(
                      key: const ValueKey('character-avatar-approve'),
                      onPressed:
                          !_mutating &&
                              !_fetching &&
                              _imageLoaded &&
                              !_imageFailed
                          ? () => _updateAvatar(approve: true)
                          : null,
                      child: Text(l.characterAvatarApprove),
                    ),
                  if (!isGenerating &&
                      character.avatarRetryAllowed == true) ...[
                    const SizedBox(height: AppSpacing.sm),
                    OutlinedButton(
                      key: const ValueKey('character-avatar-regenerate'),
                      onPressed: _mutating || _fetching
                          ? null
                          : () => _updateAvatar(approve: false),
                      child: Text(l.characterAvatarRegenerate),
                    ),
                  ],
                  if (!isGenerating &&
                      character.avatarRetryAllowed == false &&
                      !character.canUseInBook) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      l.characterAvatarRetryLimit,
                      style: AppTextStyles.bodySmall,
                    ),
                  ],
                  const SizedBox(height: AppSpacing.sm),
                  TextButton(
                    key: const ValueKey('character-avatar-other-photo'),
                    onPressed: _mutating
                        ? null
                        : () => Navigator.pop(
                            context,
                            const CharacterAvatarPreviewResult.anotherPhoto(),
                          ),
                    child: Text(l.characterAvatarOtherPhoto),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  TextButton(
                    onPressed: _mutating ? null : () => Navigator.pop(context),
                    child: Text(l.characterAvatarLater),
                  ),
                  if (_mutating)
                    const Padding(
                      padding: EdgeInsets.all(AppSpacing.md),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
