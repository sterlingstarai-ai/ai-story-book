import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

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
    } catch (_) {
      _showError('주인공을 만들지 못했어요. 잠시 후 다시 시도해주세요.');
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
      setState(() => _busy = true);
      final result = await ref.read(apiClientProvider).createCharacterFromPhoto(
            File(image.path),
            name: widget.childName,
          );
      ref.invalidate(charactersProvider);
      final id = result['character_id']?.toString();
      if (mounted && id != null) {
        Navigator.pop(context, id);
      }
    } catch (_) {
      _showError('사진으로 주인공을 만들지 못했어요. 보호자 동의/권한을 확인해주세요.');
    }
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
