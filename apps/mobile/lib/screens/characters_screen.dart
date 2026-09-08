import 'dart:io';
import 'dart:convert';
import 'package:dio/dio.dart';
import '../core/api_error.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:uuid/uuid.dart';
import '../core/photo_consent.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../providers/active_child_profile.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';
import '../widgets/character_avatar_preview.dart';
import '../services/selected_photo_cache.dart';
import '../services/photo_upload_fingerprint.dart';

enum _CharacterCreationMode { photo, drawing }

/// 캐릭터 목록 화면
class CharactersScreen extends ConsumerStatefulWidget {
  const CharactersScreen({super.key, this.selectionMode = false});
  final bool selectionMode;

  @override
  ConsumerState<CharactersScreen> createState() => _CharactersScreenState();
}

class _CharactersScreenState extends ConsumerState<CharactersScreen> {
  final ImagePicker _picker = ImagePicker();
  bool _isCreatingCharacter = false;
  bool _isChoosingImage = false;
  // H17/G19: 사진·그림 캐릭터 생성의 시도-단위 멱등키(재시도 재사용, 성공 시 리셋).
  String? _characterAttemptKey;
  String? _characterAttemptSig;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final charactersAsync = ref.watch(charactersProvider);

    return AppShell(
      currentIndex: 3,
      showNavigation: !widget.selectionMode,
      appBar: AppBar(
        backgroundColor: AppPalette.of(context).background,
        elevation: 0,
        title: Text(l.charactersTitle, style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon: Icon(
              Icons.add_circle_outline,
              color: AppPalette.of(context).primary,
            ),
            onPressed: _isCreatingCharacter
                ? null
                : () => _showCharacterOptions(),
            tooltip: l.charactersAddTooltip,
          ),
          IconButton(
            icon: Icon(
              Icons.refresh,
              color: AppPalette.of(context).textPrimary,
            ),
            onPressed: () => ref.read(charactersProvider.notifier).refresh(),
            tooltip: l.charactersRefreshTooltip,
          ),
        ],
      ),
      body: charactersAsync.when(
        data: (characters) {
          if (characters.isEmpty) {
            return EmptyState(
              icon: Icons.people_outline,
              title: l.charactersEmptyTitle,
              subtitle: l.charactersEmptySubtitle,
              buttonText: l.charactersEmptyCreateButton,
              onButtonPressed: _isCreatingCharacter
                  ? null
                  : _showCharacterOptions,
            );
          }

          return RefreshIndicator(
            onRefresh: () => ref.read(charactersProvider.notifier).refresh(),
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.lg,
                112,
              ),
              itemCount: characters.length + 1, // +1 for add button
              separatorBuilder: (_, __) =>
                  const SizedBox(height: AppSpacing.md),
              itemBuilder: (context, index) {
                // 첫 번째 아이템: 캐릭터 추가 카드
                if (index == 0) {
                  return _AddCharacterCard(
                    onTap: _isCreatingCharacter
                        ? null
                        : () => _showCharacterOptions(),
                    isLoading: _isCreatingCharacter,
                  );
                }
                final character = characters[index - 1];
                return _CharacterListItem(
                  character: character,
                  onTap: () => widget.selectionMode && character.canUseInBook
                      ? Navigator.pop(context, character)
                      : _showCharacterDetail(context, ref, character),
                  onRename: () => _renameCharacter(character),
                  onLongPress: () => _showDeleteCharacterDialog(character),
                );
              },
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => EmptyState(
          icon: Icons.error_outline,
          title: l.charactersLoadErrorTitle,
          subtitle: l.errorConnection,
          buttonText: l.charactersRetry,
          onButtonPressed: () => ref.invalidate(charactersProvider),
        ),
      ),
      floatingActionButton: charactersAsync.valueOrNull?.isNotEmpty != true
          ? null
          : SizedBox(
              height: AppSizing.minTouchTarget,
              child: FloatingActionButton.extended(
                onPressed: _isCreatingCharacter
                    ? null
                    : () => _showCharacterOptions(),
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.white,
                icon: _isCreatingCharacter
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.person_add_alt_1),
                label: Text(
                  _isCreatingCharacter
                      ? l.charactersFabCreating
                      : l.charactersFabCreate,
                ),
              ),
            ),
    );
  }

  void _showCharacterOptions() {
    if (_isChoosingImage || _isCreatingCharacter) return;
    final l = AppLocalizations.of(context);
    showModalBottomSheet(
      context: context,
      backgroundColor: AppPalette.of(context).surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => AdaptiveModalSheet(
        title: l.charactersOptionsTitle,
        subtitle: l.charactersOptionsSubtitle,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.lg),
            ListTile(
              leading: Icon(
                Icons.edit_note,
                color: AppPalette.of(context).primary,
              ),
              title: Text(l.charactersOptionTextTitle),
              subtitle: Text(l.charactersOptionTextSubtitle),
              onTap: () {
                Navigator.pop(context);
                _showTextInputForm();
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: Icon(
                Icons.camera_alt,
                color: AppPalette.of(context).primary,
              ),
              title: Text(l.charactersOptionCameraTitle),
              subtitle: Text(l.charactersOptionCameraSubtitle),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.camera);
              },
            ),
            ListTile(
              leading: Icon(
                Icons.photo_library,
                color: AppPalette.of(context).primary,
              ),
              title: Text(l.charactersOptionGalleryTitle),
              subtitle: Text(l.charactersOptionGallerySubtitle),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.gallery);
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: Icon(
                Icons.brush_outlined,
                color: AppPalette.of(context).primary,
              ),
              title: Text(l.charactersOptionDrawingTitle),
              subtitle: Text(l.charactersOptionDrawingSubtitle),
              onTap: () {
                Navigator.pop(context);
                _pickImage(
                  ImageSource.gallery,
                  creationMode: _CharacterCreationMode.drawing,
                );
              },
            ),
            const SizedBox(height: AppSpacing.md),
          ],
        ),
      ),
    );
  }

  void _showTextInputForm() {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppPalette.of(context).surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => _TextCharacterForm(
        onSubmit: (name, role, traits) {
          Navigator.pop(context);
          _createCharacterFromText(name, role, traits);
        },
      ),
    );
  }

  Future<void> _createCharacterFromText(
    String name,
    String age,
    String traits,
  ) async {
    setState(() => _isCreatingCharacter = true);

    try {
      final apiClient = ref.read(apiClientProvider);
      final result = await apiClient.createCharacterFromText(
        name: name,
        age: age,
        traits: traits,
        style: 'cartoon',
      );

      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              l.charactersCreatedSnack(result['name']?.toString() ?? ''),
            ),
          ),
        );
        ref.read(charactersProvider.notifier).refresh();
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e is DioException &&
                      e.error is ApiError &&
                      (e.error as ApiError).code ==
                          'PHOTO_PROCESSING_UNAVAILABLE'
                  ? l.characterAvatarUnavailable
                  : l.charactersCreateFailed,
            ),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isCreatingCharacter = false);
      }
    }
  }

  Future<void> _pickImage(
    ImageSource source, {
    _CharacterCreationMode creationMode = _CharacterCreationMode.photo,
  }) async {
    if (_isChoosingImage || _isCreatingCharacter) return;
    final cleanSelectedPhoto = ref.read(selectedPhotoCacheCleanerProvider);
    setState(() => _isChoosingImage = true);
    try {
      var currentSource = source;
      String? previousName;
      while (mounted) {
        XFile? image;
        CharacterAvatarPreviewResult? preview;
        try {
          if (!await ensureAgeGate(context, ref) || !mounted) return;
          image = await _picker.pickImage(
            source: currentSource,
            maxWidth: 1024,
            maxHeight: 1024,
            imageQuality: 85,
          );
          if (image == null || !mounted) return;
          final api = ref.read(apiClientProvider);
          if (!await ensurePhotoConsent(context, api) || !mounted) return;
          final name = previousName ?? await _showNameDialog();
          if (name == null || !mounted) return;
          previousName = name;
          preview = await _createCharacterFromImage(
            File(image.path),
            name.isEmpty ? null : name,
            creationMode: creationMode,
            onUploadFinished: () => cleanSelectedPhoto(image),
          );
        } finally {
          await cleanSelectedPhoto(image);
        }
        if (!mounted || preview?.chooseAnotherPhoto != true) return;
        currentSource = ImageSource.gallery;
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context).charactersImagePickFailed,
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isChoosingImage = false);
    }
  }

  Future<String?> _showNameDialog() async {
    var name = '';
    try {
      name = (await ref.refresh(activeChildProfileProvider.future))?.name ?? '';
    } catch (_) {
      // The name remains editable when optional profile defaults are offline.
    }
    if (!mounted) return null;
    final l = AppLocalizations.of(context);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.charactersNameDialogTitle),
        content: TextFormField(
          initialValue: name,
          onChanged: (value) => name = value,
          maxLength: 40,
          decoration: InputDecoration(
            hintText: l.charactersNameDialogHint,
            border: const OutlineInputBorder(),
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.charactersCancel),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, name.trim()),
            child: Text(l.charactersConfirm),
          ),
        ],
      ),
    );
    return result;
  }

  Future<void> _renameCharacter(Character character) async {
    if (!await ensureAgeGate(context, ref) || !mounted) return;
    final l = AppLocalizations.of(context);
    var name = character.name;
    final renameForm = GlobalKey<FormState>();
    final next = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        scrollable: true,
        title: Text(l.charactersRename),
        content: Form(
          key: renameForm,
          child: TextFormField(
            validator: (value) =>
                (value?.trim().isEmpty ?? true) ? l.profilesNameRequired : null,
            initialValue: name,
            maxLength: 40,
            autofocus: true,
            onChanged: (value) => name = value,
            decoration: InputDecoration(labelText: l.charactersRename),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.settingsCancel),
          ),
          TextButton(
            onPressed: () {
              if (renameForm.currentState!.validate()) {
                Navigator.pop(context, name.trim());
              }
            },
            child: Text(l.settingsSave),
          ),
        ],
      ),
    );
    if (next == null || !mounted || next == character.name) return;
    final api = ref.read(apiClientProvider);
    try {
      await api.renameCharacter(character.id, next);
      if (!mounted || !identical(api, ref.read(apiClientProvider))) return;
      ref.invalidate(charactersProvider);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.charactersNameSaved)));
    } catch (error) {
      if (!mounted) return;
      final apiError = error is DioException && error.error is ApiError
          ? error.error as ApiError
          : null;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            apiError?.localizedMessage(l) ?? l.charactersCreateFailed,
          ),
        ),
      );
    }
  }

  Future<void> _showDeleteCharacterDialog(Character character) async {
    final l = AppLocalizations.of(context);
    final confirmed =
        await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.charactersDeleteDialogTitle),
            content: Text(l.charactersDeleteDialogContent(character.name)),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.charactersCancel),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(l.charactersDelete),
              ),
            ],
          ),
        ) ??
        false;

    if (!confirmed) {
      return;
    }

    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.deleteCharacter(character.id);
      if (!mounted) {
        return;
      }
      final l = AppLocalizations.of(context);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.charactersDeletedSnack)));
      await ref.read(charactersProvider.notifier).refresh();
    } catch (_) {
      if (!mounted) {
        return;
      }
      final l = AppLocalizations.of(context);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.charactersDeleteFailed)));
    }
  }

  Future<CharacterAvatarPreviewResult?> _createCharacterFromImage(
    File photo,
    String? name, {
    _CharacterCreationMode creationMode = _CharacterCreationMode.photo,
    required Future<void> Function() onUploadFinished,
  }) async {
    setState(() => _isCreatingCharacter = true);

    try {
      final apiClient = ref.read(apiClientProvider);
      // The picker changes cache paths on re-selection. Match the actual bytes
      // and request fields so an uncertain upload can reuse its existing job.
      final digest = await ref.read(photoUploadFingerprintProvider)(photo);
      if (!mounted) return null;
      final attemptSig = jsonEncode([digest, creationMode.name, name ?? '']);
      if (_characterAttemptKey == null || _characterAttemptSig != attemptSig) {
        _characterAttemptKey = const Uuid().v4();
        _characterAttemptSig = attemptSig;
      }
      late final Map<String, dynamic> result;
      if (creationMode == _CharacterCreationMode.drawing) {
        result = await apiClient.createCharacterFromDrawing(
          photo,
          name: name,
          style: 'storybook_crayon',
          generateSheet: true,
          idempotencyKey: _characterAttemptKey,
        );
      } else {
        result = await apiClient.createCharacterFromPhoto(
          photo,
          name: name,
          style: 'cartoon',
          idempotencyKey: _characterAttemptKey,
        );
      }
      // 성공 → 다음 생성은 새 키.
      _characterAttemptKey = null;
      _characterAttemptSig = null;

      await onUploadFinished();
      if (!mounted) return null;
      ref.invalidate(charactersProvider);
      final id = result['character_id']?.toString();
      if (id == null || id.isEmpty) {
        throw const FormatException('Missing character id');
      }
      Character? initial;
      try {
        initial = Character.fromJson(result);
      } on FormatException {
        /* Reload full response in preview. */
      }
      final preview = await showCharacterAvatarPreview(
        context,
        characterId: id,
        initialCharacter: initial,
      );
      if (mounted) {
        ref.invalidate(charactersProvider);
        if (preview?.character?.canUseInBook == true) {
          if (widget.selectionMode) {
            Navigator.pop(context, preview!.character);
          } else {
            Navigator.pushNamed(
              context,
              '/create',
              arguments: {
                'characterIds': [preview!.character!.id],
              },
            );
          }
        }
      }
      return preview;
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              e is DioException &&
                      e.error is ApiError &&
                      (e.error as ApiError).code ==
                          'PHOTO_PROCESSING_UNAVAILABLE'
                  ? l.characterAvatarUnavailable
                  : l.charactersCreateFailed,
            ),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isCreatingCharacter = false);
      }
    }
    return null;
  }

  Future<void> _showCharacterDetail(
    BuildContext context,
    WidgetRef ref,
    Character character,
  ) async {
    if (character.needsAvatarApproval && !character.canUseInBook) {
      final result = await showCharacterAvatarPreview(
        context,
        characterId: character.id,
        initialCharacter: character,
      );
      if (!mounted || !context.mounted) return;
      ref.invalidate(charactersProvider);
      if (result?.chooseAnotherPhoto == true) {
        await _pickImage(ImageSource.gallery);
      } else if (result?.character?.canUseInBook == true) {
        if (widget.selectionMode) {
          Navigator.pop(context, result!.character);
        } else {
          Navigator.pushNamed(
            context,
            '/create',
            arguments: {
              'characterIds': [result!.character!.id],
            },
          );
        }
      }
      return;
    }
    showModalBottomSheet(
      context: context,
      backgroundColor: AppPalette.of(context).surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) => _CharacterDetailSheet(
          character: character,
          scrollController: scrollController,
        ),
      ),
    );
  }
}

/// 캐릭터 추가 카드
class _AddCharacterCard extends StatelessWidget {
  final VoidCallback? onTap;
  final bool isLoading;

  const _AddCharacterCard({required this.onTap, this.isLoading = false});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppPalette.of(context).primaryLight,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: AppPalette.of(context).primary,
            width: 2,
            style: BorderStyle.solid,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                color: AppPalette.of(context).primary,
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: isLoading
                  ? const Center(
                      child: SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      ),
                    )
                  : const Icon(
                      Icons.add_a_photo,
                      color: Colors.white,
                      size: 28,
                    ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    isLoading
                        ? l.charactersAddCardLoading
                        : l.charactersAddCardTitle,
                    style: AppTextStyles.heading3.copyWith(
                      color: AppPalette.of(context).primary,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    l.charactersAddCardSubtitle,
                    style: AppTextStyles.bodySmall.copyWith(
                      color: AppPalette.of(context).primary,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: AppPalette.of(context).primary),
          ],
        ),
      ),
    );
  }
}

/// 캐릭터 목록 아이템
class _CharacterListItem extends StatelessWidget {
  final Character character;
  final VoidCallback onTap;
  final VoidCallback onLongPress;
  final VoidCallback onRename;

  const _CharacterListItem({
    required this.character,
    required this.onTap,
    required this.onLongPress,
    required this.onRename,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.md),
          boxShadow: const [
            BoxShadow(
              color: AppColors.blackOverlayLight,
              blurRadius: 10,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            CharacterAvatarThumbnail(character: character),
            const SizedBox(width: AppSpacing.md),
            // 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(character.name, style: AppTextStyles.heading3),
                  if (character.needsAvatarApproval) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      characterAvatarStatusLabel(l, character),
                      style: AppTextStyles.caption.copyWith(
                        color: AppPalette.of(context).primary,
                      ),
                    ),
                  ],
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    characterDisplayDescription(l, character),
                    style: AppTextStyles.bodySmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (!character.needsAvatarApproval) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Wrap(
                      spacing: AppSpacing.xs,
                      children: character.personalityTraits.take(3).map((
                        trait,
                      ) {
                        return Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.sm,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: AppPalette.of(context).primaryLight,
                            borderRadius: BorderRadius.circular(AppRadius.sm),
                          ),
                          child: Text(
                            trait,
                            style: AppTextStyles.caption.copyWith(
                              color: AppPalette.of(context).primary,
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  ],
                ],
              ),
            ),
            PopupMenuButton<String>(
              tooltip: l.charactersManage,
              constraints: const BoxConstraints(minWidth: 180),
              style: IconButton.styleFrom(minimumSize: const Size(64, 64)),
              onSelected: (value) =>
                  value == 'rename' ? onRename() : onLongPress(),
              itemBuilder: (_) => [
                PopupMenuItem(
                  value: 'rename',
                  height: 64,
                  child: Text(l.charactersRename),
                ),
                PopupMenuItem(
                  value: 'delete',
                  height: 64,
                  child: Text(l.charactersDeleteDialogTitle),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 캐릭터 상세 시트
class _CharacterDetailSheet extends StatelessWidget {
  final Character character;
  final ScrollController scrollController;

  const _CharacterDetailSheet({
    required this.character,
    required this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Column(
      children: [
        const SizedBox(height: AppSpacing.md),
        Container(
          width: 40,
          height: 4,
          decoration: BoxDecoration(
            color: AppPalette.of(context).divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        Expanded(
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              // 헤더
              Row(
                children: [
                  CharacterAvatarThumbnail(character: character, size: 80),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(character.name, style: AppTextStyles.heading2),
                        const SizedBox(height: AppSpacing.xs),
                        Text(
                          _formatDate(l, character.createdAt),
                          style: AppTextStyles.caption,
                        ),
                      ],
                    ),
                  ),
                ],
              ),

              const SizedBox(height: AppSpacing.lg),

              // 설명
              _SectionTitle(l.charactersDetailDescription),
              Text(
                characterDisplayDescription(l, character),
                style: AppTextStyles.body,
              ),

              const SizedBox(height: AppSpacing.lg),

              if (!character.needsAvatarApproval) ...[
                // 성격
                _SectionTitle(l.charactersDetailPersonality),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: character.personalityTraits.map((trait) {
                    return Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.md,
                        vertical: AppSpacing.sm,
                      ),
                      decoration: BoxDecoration(
                        color: AppPalette.of(context).primaryLight,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                      ),
                      child: Text(
                        trait,
                        style: AppTextStyles.body.copyWith(
                          color: AppPalette.of(context).primary,
                        ),
                      ),
                    );
                  }).toList(),
                ),

                const SizedBox(height: AppSpacing.lg),

                // 외형
                _SectionTitle(l.charactersDetailAppearance),
                _DetailRow(
                  l.charactersDetailAge,
                  character.appearance.ageVisual,
                ),
                _DetailRow(l.charactersDetailFace, character.appearance.face),
                _DetailRow(l.charactersDetailHair, character.appearance.hair),
                _DetailRow(l.charactersDetailSkin, character.appearance.skin),
                _DetailRow(l.charactersDetailBody, character.appearance.body),

                const SizedBox(height: AppSpacing.lg),

                // 의상
                _SectionTitle(l.charactersDetailClothing),
                _DetailRow(l.charactersDetailTop, character.clothing.top),
                _DetailRow(l.charactersDetailBottom, character.clothing.bottom),
                _DetailRow(l.charactersDetailShoes, character.clothing.shoes),
                _DetailRow(
                  l.charactersDetailAccessories,
                  character.clothing.accessories,
                ),

                if (character.visualStyleNotes != null) ...[
                  const SizedBox(height: AppSpacing.lg),
                  _SectionTitle(l.charactersDetailStyleNotes),
                  Text(character.visualStyleNotes!, style: AppTextStyles.body),
                ],

                // 고유 특징(일관성 고정) — 모든 책·페이지에서 동일하게 유지되는 식별 표식
                if (character.distinctiveFeatures != null &&
                    character.distinctiveFeatures!.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.lg),
                  _SectionTitle(l.charactersDetailIdentityLock),
                  const SizedBox(height: AppSpacing.xs),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.sm,
                    children: character.distinctiveFeatures!.map((f) {
                      return Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: AppPalette.of(context).primaryLight,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          f,
                          style: AppTextStyles.caption.copyWith(
                            color: AppPalette.of(context).primary,
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ],
              ],

              const SizedBox(height: AppSpacing.xl),

              // 액션 버튼
              PrimaryButton(
                text: l.charactersDetailCreateBookButton,
                onPressed: character.canUseInBook
                    ? () {
                        Navigator.pop(context);
                        Navigator.pushNamed(
                          context,
                          '/create',
                          arguments: {
                            'characterIds': [character.id],
                          },
                        );
                      }
                    : null,
              ),

              const SizedBox(height: AppSpacing.md),
            ],
          ),
        ),
      ],
    );
  }

  String _formatDate(AppLocalizations l, DateTime date) {
    return l.charactersCreatedDate(date.year, date.month, date.day);
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;

  const _SectionTitle(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Text(title, style: AppTextStyles.heading3),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(label, style: AppTextStyles.bodySmall),
          ),
          Expanded(child: Text(value, style: AppTextStyles.body)),
        ],
      ),
    );
  }
}

/// 캐릭터 역할 정의
class _CharacterRole {
  final String emoji;
  final String ageHint; // AI에게 전달할 나이 힌트

  const _CharacterRole(this.emoji, this.ageHint);
}

// label은 런타임에 AppLocalizations로 해석한다(아래 _characterRoleLabels).
// emoji/ageHint는 UI 라벨이 아닌 데이터(ageHint는 AI에 전달되는 페이로드)라 그대로 둔다.
const _characterRoles = [
  _CharacterRole('👶', '5살 어린이'),
  _CharacterRole('👦', '10살 소년'),
  _CharacterRole('👧', '10살 소녀'),
  _CharacterRole('👩', '30대 여성'),
  _CharacterRole('👨', '30대 남성'),
  _CharacterRole('👵', '60대 할머니'),
  _CharacterRole('👴', '60대 할아버지'),
  _CharacterRole('🧒', '또래 친구'),
  _CharacterRole('👩‍🏫', '선생님'),
  _CharacterRole('🐕', '귀여운 반려동물'),
];

// _characterRoles와 동일 순서로 인덱스가 1:1 대응되는 표시용 라벨.
List<String> _characterRoleLabels(AppLocalizations l) => [
  l.charactersRoleChild,
  l.charactersRoleBrother,
  l.charactersRoleSister,
  l.charactersRoleMom,
  l.charactersRoleDad,
  l.charactersRoleGrandma,
  l.charactersRoleGrandpa,
  l.charactersRoleFriend,
  l.charactersRoleTeacher,
  l.charactersRolePet,
];

/// 텍스트 기반 캐릭터 생성 폼
class _TextCharacterForm extends StatefulWidget {
  final void Function(String name, String role, String traits) onSubmit;

  const _TextCharacterForm({required this.onSubmit});

  @override
  State<_TextCharacterForm> createState() => _TextCharacterFormState();
}

class _TextCharacterFormState extends State<_TextCharacterForm> {
  final _nameController = TextEditingController();
  final _customRoleController = TextEditingController();
  final _traitsController = TextEditingController();

  int? _selectedRoleIndex;
  bool _isCustomRole = false;

  // M6: 표시 ↔ 전송 분리. 이 값들은 **AI 페이로드(traits)** 로 그대로 전달되는 캐논값이라
  // 로케일과 무관하게 고정한다(생성 동작을 바꾸지 않기 위함). 화면에 그려지는 라벨은
  // `_traitLabel()` 이 로케일에 맞춰 돌려준다 — 이전에는 이 캐논값이 그대로 칩에 렌더돼
  // en/ja 사용자가 한국어 칩 10개를 봤다.
  final _suggestedTraits = [
    '호기심 많은',
    '활발한',
    '다정한',
    '용감한',
    '재미있는',
    '똑똑한',
    '친절한',
    '장난꾸러기',
    '차분한',
    '씩씩한',
  ];

  /// 캐논 특성값 → 현지화 표시 라벨. 매핑에 없으면(사용자 자유 입력) 원문을 그대로 쓴다.
  String _traitLabel(AppLocalizations l, String canonical) {
    switch (canonical) {
      case '호기심 많은':
        return l.characterTraitCurious;
      case '활발한':
        return l.characterTraitLively;
      case '다정한':
        return l.characterTraitWarm;
      case '용감한':
        return l.characterTraitBrave;
      case '재미있는':
        return l.characterTraitFunny;
      case '똑똑한':
        return l.characterTraitSmart;
      case '친절한':
        return l.characterTraitKind;
      case '장난꾸러기':
        return l.characterTraitPlayful;
      case '차분한':
        return l.characterTraitCalm;
      case '씩씩한':
        return l.characterTraitSpirited;
      default:
        return canonical;
    }
  }

  final Set<String> _selectedTraits = {};

  @override
  void dispose() {
    _nameController.dispose();
    _customRoleController.dispose();
    _traitsController.dispose();
    super.dispose();
  }

  String _buildTraitsString() {
    final customTraits = _traitsController.text.trim();
    final allTraits = [..._selectedTraits];
    if (customTraits.isNotEmpty) {
      allTraits.addAll(
        customTraits.split(',').map((t) => t.trim()).where((t) => t.isNotEmpty),
      );
    }
    return allTraits.join(', ');
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final roleLabels = _characterRoleLabels(l);
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 핸들바
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppPalette.of(context).divider,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Center(
                child: Text(
                  l.charactersFormTitle,
                  style: AppTextStyles.heading2,
                  textAlign: TextAlign.center,
                ),
              ),
              const SizedBox(height: AppSpacing.xl),

              // 1. 역할 선택
              Text(l.charactersFormRoleLabel, style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  ..._characterRoles.asMap().entries.map((entry) {
                    final index = entry.key;
                    final role = entry.value;
                    final isSelected =
                        _selectedRoleIndex == index && !_isCustomRole;
                    return Semantics(
                      button: true,
                      selected: isSelected,
                      child: GestureDetector(
                        onTap: () => setState(() {
                          _selectedRoleIndex = index;
                          _isCustomRole = false;
                        }),
                        child: Container(
                          constraints: const BoxConstraints(
                            minHeight: AppSizing.minTouchTarget,
                          ),
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.md,
                            vertical: AppSpacing.sm,
                          ),
                          decoration: BoxDecoration(
                            color: isSelected
                                ? AppPalette.of(context).primaryLight
                                : AppPalette.of(context).surface,
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(
                              color: isSelected
                                  ? AppPalette.of(context).primary
                                  : AppPalette.of(context).divider,
                              width: isSelected ? 2 : 1,
                            ),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                role.emoji,
                                style: const TextStyle(fontSize: 20),
                              ),
                              const SizedBox(width: AppSpacing.xs),
                              Flexible(
                                child: Text(
                                  roleLabels[index],
                                  style: TextStyle(
                                    color: isSelected
                                        ? AppPalette.of(context).primary
                                        : AppPalette.of(context).textPrimary,
                                    fontWeight: isSelected
                                        ? FontWeight.w600
                                        : FontWeight.normal,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  }),
                  // 직접 입력 옵션
                  Semantics(
                    button: true,
                    selected: _isCustomRole,
                    child: GestureDetector(
                      onTap: () => setState(() {
                        _isCustomRole = true;
                        _selectedRoleIndex = null;
                      }),
                      child: Container(
                        constraints: const BoxConstraints(
                          minHeight: AppSizing.minTouchTarget,
                        ),
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.md,
                          vertical: AppSpacing.sm,
                        ),
                        decoration: BoxDecoration(
                          color: _isCustomRole
                              ? AppPalette.of(context).primaryLight
                              : AppPalette.of(context).surface,
                          borderRadius: BorderRadius.circular(AppRadius.md),
                          border: Border.all(
                            color: _isCustomRole
                                ? AppPalette.of(context).primary
                                : AppPalette.of(context).divider,
                            width: _isCustomRole ? 2 : 1,
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Text('✏️', style: TextStyle(fontSize: 20)),
                            const SizedBox(width: AppSpacing.xs),
                            Flexible(
                              child: Text(
                                l.charactersFormCustomRole,
                                style: TextStyle(
                                  color: _isCustomRole
                                      ? AppPalette.of(context).primary
                                      : AppPalette.of(context).textPrimary,
                                  fontWeight: _isCustomRole
                                      ? FontWeight.w600
                                      : FontWeight.normal,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),

              // 직접 입력 필드 (선택시)
              if (_isCustomRole) ...[
                const SizedBox(height: AppSpacing.sm),
                TextField(
                  controller: _customRoleController,
                  decoration: InputDecoration(
                    hintText: l.charactersFormCustomRoleHint,
                    filled: true,
                    fillColor: AppPalette.of(context).background,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
              ],

              const SizedBox(height: AppSpacing.lg),

              // 2. 이름 입력
              Text(l.charactersFormNameLabel, style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _nameController,
                maxLength: 40,
                decoration: InputDecoration(
                  hintText: l.charactersFormNameHint,
                  filled: true,
                  fillColor: AppPalette.of(context).background,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),

              const SizedBox(height: AppSpacing.lg),

              // 3. 성격/특징 선택
              Text(l.charactersFormTraitsLabel, style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.xs),
              Text(
                l.charactersFormTraitsHelper,
                style: AppTextStyles.caption.copyWith(
                  color: AppPalette.of(context).textHint,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                children: _suggestedTraits.map((trait) {
                  final isSelected = _selectedTraits.contains(trait);
                  return Semantics(
                    button: true,
                    selected: isSelected,
                    child: GestureDetector(
                      onTap: () => setState(() {
                        if (isSelected) {
                          _selectedTraits.remove(trait);
                        } else {
                          _selectedTraits.add(trait);
                        }
                      }),
                      child: Container(
                        constraints: const BoxConstraints(
                          minHeight: AppSizing.minTouchTarget,
                        ),
                        alignment: Alignment.center,
                        width: 112,
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.sm,
                          vertical: AppSpacing.sm,
                        ),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? AppColors.primary
                              : AppPalette.of(context).surface,
                          borderRadius: BorderRadius.circular(AppRadius.sm),
                          border: Border.all(
                            color: isSelected
                                ? AppPalette.of(context).primary
                                : AppPalette.of(context).divider,
                          ),
                        ),
                        child: Text(
                          _traitLabel(l, trait),
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 14,
                            color: isSelected
                                ? Colors.white
                                : AppPalette.of(context).textSecondary,
                          ),
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _traitsController,
                decoration: InputDecoration(
                  hintText: l.charactersFormTraitsExtraHint,
                  hintStyle: AppTextStyles.caption,
                  filled: true,
                  fillColor: AppPalette.of(context).background,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.md,
                    vertical: AppSpacing.sm,
                  ),
                ),
              ),

              const SizedBox(height: AppSpacing.xl),

              // 생성 버튼
              PrimaryButton(
                key: const Key('character-form-submit'),
                text: l.charactersFormSubmit,
                onPressed: () {
                  // 역할 확인
                  String role;
                  if (_isCustomRole) {
                    role = _customRoleController.text.trim();
                    if (role.isEmpty) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text(l.charactersFormRoleRequired)),
                      );
                      return;
                    }
                  } else if (_selectedRoleIndex != null) {
                    role = _characterRoles[_selectedRoleIndex!].ageHint;
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(l.charactersFormRoleSelect)),
                    );
                    return;
                  }

                  // 이름 확인
                  final name = _nameController.text.trim();
                  if (name.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(l.charactersFormNameRequired)),
                    );
                    return;
                  }

                  // 특징 확인
                  final traits = _buildTraitsString();
                  if (traits.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(l.charactersFormTraitsRequired)),
                    );
                    return;
                  }

                  widget.onSubmit(name, role, traits);
                },
              ),
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        ),
      ),
    );
  }
}
