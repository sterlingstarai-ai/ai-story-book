import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/api_error.dart';
import '../core/photo_consent.dart';
import '../providers/providers.dart';
import '../services/api_client.dart';
import '../utils/constants.dart';

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
String _errorMessage(Object error, String fallback) {
  final apiError = _extractApiError(error);
  if (apiError == null) {
    return fallback;
  }
  if (apiError.statusCode == 403) {
    return apiError.message;
  }
  return apiError.userMessage;
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
    backgroundColor: AppColors.surface,
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
    setState(() => _busy = true);
    try {
      final id = await ref.read(apiClientProvider).createCharacterFromPreset(
            presetId: preset['preset_id'].toString(),
            name: widget.childName,
          );
      ref.invalidate(charactersProvider);
      if (mounted) {
        Navigator.pop(context, id);
      }
    } catch (error) {
      _showError(_errorMessage(error, '주인공을 만들지 못했어요. 잠시 후 다시 시도해주세요.'));
    }
  }

  Future<void> _usePhoto(ImageSource source) async {
    if (_busy) {
      return;
    }
    try {
      final XFile? image = await _picker.pickImage(
        source: source,
        maxWidth: 1024,
        imageQuality: 85,
      );
      if (image == null) {
        return;
      }
      final api = ref.read(apiClientProvider);
      // 사진(아동 얼굴)은 선택 동의 — 실제 사용 시점에 받는다(JIT, 데이터 최소수집).
      if (!await _ensurePhotoConsent(api)) {
        // 동의 거부/취소 시 선택된 임시 이미지(아동 얼굴)를 즉시 폐기.
        try {
          await File(image.path).delete();
        } catch (_) {}
        return;
      }
      setState(() => _busy = true);
      final result = await api.createCharacterFromPhoto(
        File(image.path),
        name: widget.childName,
      );
      ref.invalidate(charactersProvider);
      if (!mounted) {
        return;
      }
      final id = result['character_id']?.toString();
      if (id != null) {
        Navigator.pop(context, id);
      } else {
        // 2xx인데 character_id 누락 — _busy를 풀어 시트 잠금을 방지
        _showError('사진으로 주인공을 만들지 못했어요. 잠시 후 다시 시도해주세요.');
      }
    } catch (error) {
      _showError(_errorMessage(
        error,
        '사진으로 주인공을 만들지 못했어요. 보호자 동의/권한을 확인해주세요.',
      ));
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
    final presetsAsync = ref.watch(characterPresetsProvider);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('우리 아이를 주인공으로', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.xs),
            Text(
              '사진으로 만들거나 기본 캐릭터를 골라보세요',
              style: AppTextStyles.caption.copyWith(color: AppColors.textHint),
            ),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed:
                        _busy ? null : () => _usePhoto(ImageSource.camera),
                    icon: const Icon(Icons.camera_alt_outlined),
                    label: const Text('사진 촬영'),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed:
                        _busy ? null : () => _usePhoto(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library_outlined),
                    label: const Text('갤러리'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              '기본 캐릭터',
              style: AppTextStyles.caption.copyWith(color: AppColors.textHint),
            ),
            const SizedBox(height: AppSpacing.sm),
            presetsAsync.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(AppSpacing.lg),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (_, __) => const Text('기본 캐릭터를 불러오지 못했어요.'),
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
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.md),
      child: Container(
        width: 88,
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        decoration: BoxDecoration(
          color: AppColors.primaryLight,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(color: AppColors.divider),
        ),
        child: Column(
          children: [
            const CircleAvatar(
              radius: 20,
              backgroundColor: AppColors.primaryMedium,
              child: Icon(Icons.face, color: AppColors.primary),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              name,
              style: AppTextStyles.caption,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}
