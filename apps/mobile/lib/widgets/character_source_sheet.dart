import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'package:image_picker/image_picker.dart';

import '../core/api_error.dart';
import '../core/photo_consent.dart';
import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/api_client.dart';
import '../services/selected_photo_cache.dart';
import '../models/character.dart';
import 'character_avatar_preview.dart';
import '../utils/constants.dart';
import 'age_gate_dialog.dart';
import 'common_widgets.dart';

/// DioException 으로 래핑된 ApiError 까지 추출(create_screen 패턴과 동일).
ApiError? _extractApiError(Object error) {
  if (error is ApiError) {
    return error;
  }
  if (error is DioException && error.error is ApiError) {
    return error.error as ApiError;
  }
  return null;
}

/// 보호자 동의 미동의(403)는 서버가 내려준 구체 사유를 그대로 노출한다.
String _errorMessage(AppLocalizations l, Object error, String fallback) {
  final apiError = _extractApiError(error);
  if (apiError == null) {
    return fallback;
  }
  if (apiError.code == 'PHOTO_PROCESSING_UNAVAILABLE') {
    return l.characterAvatarUnavailable;
  }
  if (apiError.statusCode == 403) {
    return apiError.message;
  }
  return apiError.localizedMessage(l); // M15: en/ja 로케일 에러 로컬라이즈
}

/// '우리 아이를 주인공으로' 소스 선택 시트.
///
/// (a) 사진 촬영/갤러리 → from-photo, (b) 기본 캐릭터 프리셋 → from-preset.
/// 생성된 character_id 를 [Navigator.pop] 으로 반환(취소 시 null).
Future<String?> showCharacterSourceSheet(
  BuildContext context, {
  String? childName,
}) {
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppPalette.of(context).surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.xl)),
    ),
    builder: (_) => CharacterSourceSheet(childName: childName),
  );
}

class CharacterSourceSheet extends ConsumerStatefulWidget {
  const CharacterSourceSheet({super.key, this.childName});

  final String? childName;

  @override
  ConsumerState<CharacterSourceSheet> createState() =>
      _CharacterSourceSheetState();
}

class _CharacterSourceSheetState extends ConsumerState<CharacterSourceSheet> {
  bool _busy = false;
  bool _choosingPhoto = false;
  // H17/G19: 사진 캐릭터 생성 시도-단위 멱등키.
  String? _attemptKey;
  String? _attemptSig;
  final ImagePicker _picker = ImagePicker();

  void _showError(String message) {
    if (!mounted) {
      return;
    }
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _useFromPreset(Map<String, dynamic> preset) async {
    if (_busy) {
      return;
    }
    final l = AppLocalizations.of(context);
    final language = Localizations.localeOf(context).languageCode;
    setState(() => _busy = true);
    try {
      final id = await ref.read(apiClientProvider).createCharacterFromPreset(
            presetId: preset['preset_id'].toString(),
            name: widget.childName,
            language: language,
          );
      if (!mounted) return;
      ref.invalidate(charactersProvider);
      Navigator.pop(context, id);
    } catch (error) {
      _showError(_errorMessage(l, error, l.characterSourceCreateFailed));
    }
  }

  Future<void> _usePhoto(ImageSource source) async {
    if (_busy || _choosingPhoto) return;
    final l = AppLocalizations.of(context);
    final cleanSelectedPhoto = ref.read(selectedPhotoCacheCleanerProvider);
    setState(() => _choosingPhoto = true);
    try {
      var currentSource = source;
      while (mounted) {
        XFile? image;
        Character? character;
        String? id;
        try {
          if (!await ensureAgeGate(context, ref) || !mounted) return;
          image = await _picker.pickImage(
              source: currentSource, maxWidth: 1024, imageQuality: 85);
          if (image == null || !mounted) return;
          final api = ref.read(apiClientProvider);
          if (!await _ensurePhotoConsent(api) || !mounted) return;
          setState(() => _busy = true);
          final attemptSig = '${image.path}|${widget.childName ?? ''}';
          if (_attemptKey == null || _attemptSig != attemptSig) {
            _attemptKey = const Uuid().v4();
            _attemptSig = attemptSig;
          }
          final result = await api.createCharacterFromPhoto(File(image.path),
              name: widget.childName, idempotencyKey: _attemptKey);
          _attemptKey = null;
          _attemptSig = null;
          id = result['character_id']?.toString();
          if (id == null || id.isEmpty) {
            throw const FormatException('Missing character id');
          }
          try {
            character = Character.fromJson(result);
          } on FormatException {/* GET resolves legacy upload envelopes. */}
        } finally {
          await cleanSelectedPhoto(image);
          if (mounted) setState(() => _busy = false);
        }
        if (!mounted) return;
        ref.invalidate(charactersProvider);
        final preview = await showCharacterAvatarPreview(context,
            characterId: id, initialCharacter: character);
        if (!mounted) return;
        ref.invalidate(charactersProvider);
        if (preview?.character?.canUseInBook == true) {
          Navigator.pop(context, preview!.character!.id);
          return;
        }
        if (preview?.chooseAnotherPhoto != true) return;
        currentSource = ImageSource.gallery;
      }
    } catch (error) {
      _showError(_errorMessage(l, error, l.characterSourcePhotoFailed));
    } finally {
      if (mounted) {
        setState(() {
          _choosingPhoto = false;
          _busy = false;
        });
      }
    }
  }

  /// 사진 사용 직전 JIT 동의 — 공용 헬퍼(core/photo_consent.dart)로 단일화해
  /// 모든 사진 진입점이 동일한 PIPA 5요소 고지를 쓰도록 한다.
  Future<bool> _ensurePhotoConsent(ApiClient api) async {
    if (!mounted) {
      return false;
    }
    return ensurePhotoConsent(context, api);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final language = Localizations.localeOf(context).languageCode;
    final presetsAsync = ref.watch(characterPresetsProvider(language));
    return AdaptiveModalSheet(
      title: l.characterSourceTitle,
      subtitle: l.characterSourceSubtitle,
      contentPadding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: _busy || _choosingPhoto
                  ? null
                  : () => _usePhoto(ImageSource.camera),
              icon: const Icon(Icons.camera_alt_outlined),
              label: Text(l.characterSourcePhotoCamera),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: _busy || _choosingPhoto
                  ? null
                  : () => _usePhoto(ImageSource.gallery),
              icon: const Icon(Icons.photo_library_outlined),
              label: Text(l.characterSourceGallery),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            l.characterSourcePresetSectionLabel,
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          presetsAsync.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(AppSpacing.lg),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (_, __) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l.characterSourcePresetLoadError),
                TextButton.icon(
                  style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
                  onPressed: () =>
                      ref.invalidate(characterPresetsProvider(language)),
                  icon: const Icon(Icons.refresh),
                  label: Text(l.retry),
                ),
              ],
            ),
            data: (presets) => Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: presets
                  .map(
                    (preset) => _PresetChip(
                      key: Key('preset_${preset['preset_id']}'),
                      name: preset['name']?.toString() ?? '',
                      onTap: _busy ? null : () => _useFromPreset(preset),
                    ),
                  )
                  .toList(),
            ),
          ),
          if (_busy)
            const Padding(
              padding: EdgeInsets.only(top: AppSpacing.md),
              child: LinearProgressIndicator(),
            ),
        ],
      ),
    );
  }
}

class _PresetChip extends StatelessWidget {
  const _PresetChip({super.key, required this.name, required this.onTap});

  final String name;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: onTap != null,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadius.md),
        child: Container(
          width: 100,
          constraints:
              const BoxConstraints(minHeight: AppSizing.minTouchTarget),
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          decoration: BoxDecoration(
            color: AppPalette.of(context).primaryLight,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppPalette.of(context).divider),
          ),
          child: Column(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: AppPalette.of(context).primaryLight,
                child: Icon(Icons.face, color: AppPalette.of(context).primary),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                name,
                style: AppTextStyles.bodySmall,
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
