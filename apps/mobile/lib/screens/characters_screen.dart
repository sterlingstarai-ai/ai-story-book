import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../core/photo_consent.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';

enum _CharacterCreationMode {
  photo,
  drawing,
}

/// 캐릭터 목록 화면
class CharactersScreen extends ConsumerStatefulWidget {
  const CharactersScreen({super.key});

  @override
  ConsumerState<CharactersScreen> createState() => _CharactersScreenState();
}

class _CharactersScreenState extends ConsumerState<CharactersScreen> {
  final ImagePicker _picker = ImagePicker();
  bool _isCreatingCharacter = false;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final charactersAsync = ref.watch(charactersProvider);

    return AppShell(
      currentIndex: 3,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        title: Text(l.charactersTitle, style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon:
                const Icon(Icons.add_circle_outline, color: AppColors.primary),
            onPressed:
                _isCreatingCharacter ? null : () => _showCharacterOptions(),
            tooltip: l.charactersAddTooltip,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: AppColors.textPrimary),
            onPressed: () => ref.read(charactersProvider.notifier).refresh(),
            tooltip: l.charactersRefreshTooltip,
          ),
        ],
      ),
      body: charactersAsync.when(
        data: (characters) {
          if (characters.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  EmptyState(
                    icon: Icons.people_outline,
                    title: l.charactersEmptyTitle,
                    subtitle: l.charactersEmptySubtitle,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  PrimaryButton(
                    text: l.charactersEmptyCreateButton,
                    isFullWidth: false,
                    onPressed: () => _showCharacterOptions(),
                  ),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () => ref.read(charactersProvider.notifier).refresh(),
            child: ListView.separated(
              padding: const EdgeInsets.all(AppSpacing.lg),
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
                  onTap: () => _showCharacterDetail(context, ref, character),
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
          subtitle: error.toString(),
          buttonText: l.charactersRetry,
          onButtonPressed: () => ref.invalidate(charactersProvider),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _isCreatingCharacter ? null : () => _showCharacterOptions(),
        backgroundColor: AppColors.primary,
        icon: _isCreatingCharacter
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.camera_alt),
        label: Text(_isCreatingCharacter
            ? l.charactersFabCreating
            : l.charactersFabCreate),
      ),
    );
  }

  void _showCharacterOptions() {
    final l = AppLocalizations.of(context);
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
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
              leading: const Icon(Icons.edit_note, color: AppColors.primary),
              title: Text(l.charactersOptionTextTitle),
              subtitle: Text(l.charactersOptionTextSubtitle),
              onTap: () {
                Navigator.pop(context);
                _showTextInputForm();
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.camera_alt, color: AppColors.primary),
              title: Text(l.charactersOptionCameraTitle),
              subtitle: Text(l.charactersOptionCameraSubtitle),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library, color: AppColors.primary),
              title: Text(l.charactersOptionGalleryTitle),
              subtitle: Text(l.charactersOptionGallerySubtitle),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.gallery);
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.brush_outlined, color: AppColors.primary),
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
      backgroundColor: AppColors.surface,
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
      String name, String age, String traits) async {
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
              content: Text(l.charactersCreatedSnack(
                  result['name']?.toString() ?? ''))),
        );
        ref.read(charactersProvider.notifier).refresh();
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(l.charactersCreateFailed),
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
    try {
      final XFile? image = await _picker.pickImage(
        source: source,
        maxWidth: 1024,
        maxHeight: 1024,
        imageQuality: 85,
      );

      if (image == null) return;

      // 사진/그림(아동 얼굴)은 사용 직전 JIT 보호자 동의 — 미동의 시 5요소 고지 후 받는다.
      if (!mounted) return;
      final api = ref.read(apiClientProvider);
      if (!await ensurePhotoConsent(context, api)) {
        // 동의 거부/취소 시 선택된 임시 이미지를 즉시 폐기(데이터 최소수집).
        try {
          await File(image.path).delete();
        } catch (_) {}
        return;
      }

      // 이름 입력 다이얼로그
      final name = await _showNameDialog();
      if (name == null) return;

      await _createCharacterFromImage(
        File(image.path),
        name,
        creationMode: creationMode,
      );
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.charactersImagePickFailed)),
        );
      }
    }
  }

  Future<String?> _showNameDialog() async {
    final l = AppLocalizations.of(context);
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.charactersNameDialogTitle),
        content: TextField(
          controller: controller,
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
            onPressed: () => Navigator.pop(
                context, controller.text.isEmpty ? null : controller.text),
            child: Text(l.charactersConfirm),
          ),
        ],
      ),
    );
    controller.dispose();
    return result;
  }

  Future<void> _showDeleteCharacterDialog(Character character) async {
    final l = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.charactersDeletedSnack)),
      );
      await ref.read(charactersProvider.notifier).refresh();
    } catch (_) {
      if (!mounted) {
        return;
      }
      final l = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.charactersDeleteFailed)),
      );
    }
  }

  Future<void> _createCharacterFromImage(
    File photo,
    String? name, {
    _CharacterCreationMode creationMode = _CharacterCreationMode.photo,
  }) async {
    setState(() => _isCreatingCharacter = true);

    try {
      final apiClient = ref.read(apiClientProvider);
      late final Map<String, dynamic> result;
      if (creationMode == _CharacterCreationMode.drawing) {
        result = await apiClient.createCharacterFromDrawing(
          photo,
          name: name,
          style: 'storybook_crayon',
          generateSheet: true,
        );
      } else {
        result = await apiClient.createCharacterFromPhoto(
          photo,
          name: name,
          style: 'cartoon',
        );
      }

      if (mounted) {
        final l = AppLocalizations.of(context);
        final characterName =
            result['name']?.toString() ?? l.charactersDefaultName;
        final rawSheetUrls = result['character_sheet_urls'];
        final sheetCount = rawSheetUrls is List ? rawSheetUrls.length : 0;
        final message = creationMode == _CharacterCreationMode.drawing &&
                sheetCount > 0
            ? l.charactersCreatedWithSheetsSnack(characterName, sheetCount)
            : l.charactersCreatedSnack(characterName);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
        ref.read(charactersProvider.notifier).refresh();
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(l.charactersCreateFailed),
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

  void _showCharacterDetail(
      BuildContext context, WidgetRef ref, Character character) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
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

  const _AddCharacterCard({
    required this.onTap,
    this.isLoading = false,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.primaryLight,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: AppColors.primary,
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
                color: AppColors.primary,
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
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    l.charactersAddCardSubtitle,
                    style: AppTextStyles.bodySmall.copyWith(
                      color: AppColors.primary,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(
              Icons.chevron_right,
              color: AppColors.primary,
            ),
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

  const _CharacterListItem({
    required this.character,
    required this.onTap,
    required this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.surface,
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
            // 아바타
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppColors.primary, AppColors.secondary],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Center(
                child: Text(
                  character.name.isNotEmpty ? character.name[0] : '?',
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            // 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    character.name,
                    style: AppTextStyles.heading3,
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    character.masterDescription,
                    style: AppTextStyles.bodySmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Wrap(
                    spacing: AppSpacing.xs,
                    children: character.personalityTraits.take(3).map((trait) {
                      return Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.sm,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight,
                          borderRadius: BorderRadius.circular(AppRadius.sm),
                        ),
                        child: Text(
                          trait,
                          style: AppTextStyles.caption.copyWith(
                            color: AppColors.primary,
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textHint),
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
            color: AppColors.divider,
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
                  Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [AppColors.primary, AppColors.secondary],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(AppRadius.lg),
                    ),
                    child: Center(
                      child: Text(
                        character.name.isNotEmpty ? character.name[0] : '?',
                        style: const TextStyle(
                          fontSize: 36,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
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
              Text(character.masterDescription, style: AppTextStyles.body),

              const SizedBox(height: AppSpacing.lg),

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
                      color: AppColors.primaryLight,
                      borderRadius: BorderRadius.circular(AppRadius.md),
                    ),
                    child: Text(
                      trait,
                      style: AppTextStyles.body.copyWith(
                        color: AppColors.primary,
                      ),
                    ),
                  );
                }).toList(),
              ),

              const SizedBox(height: AppSpacing.lg),

              // 외형
              _SectionTitle(l.charactersDetailAppearance),
              _DetailRow(l.charactersDetailAge, character.appearance.ageVisual),
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
                  l.charactersDetailAccessories, character.clothing.accessories),

              if (character.visualStyleNotes != null) ...[
                const SizedBox(height: AppSpacing.lg),
                _SectionTitle(l.charactersDetailStyleNotes),
                Text(character.visualStyleNotes!, style: AppTextStyles.body),
              ],

              const SizedBox(height: AppSpacing.xl),

              // 액션 버튼
              PrimaryButton(
                text: l.charactersDetailCreateBookButton,
                onPressed: () {
                  Navigator.pop(context);
                  Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {
                      'characterIds': [character.id],
                    },
                  );
                },
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
          Expanded(
            child: Text(value, style: AppTextStyles.body),
          ),
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

  // 추천 성격 특성 (선택 시 그대로 AI 페이로드(traits)로 전달되는 값이라 현지화하지 않음)
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
      allTraits.addAll(customTraits
          .split(',')
          .map((t) => t.trim())
          .where((t) => t.isNotEmpty));
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
                    color: AppColors.divider,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Center(
                child: Text(l.charactersFormTitle,
                    style: AppTextStyles.heading2),
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
                    return GestureDetector(
                      onTap: () => setState(() {
                        _selectedRoleIndex = index;
                        _isCustomRole = false;
                      }),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.md,
                          vertical: AppSpacing.sm,
                        ),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? AppColors.primaryLight
                              : AppColors.surface,
                          borderRadius: BorderRadius.circular(AppRadius.md),
                          border: Border.all(
                            color: isSelected
                                ? AppColors.primary
                                : AppColors.divider,
                            width: isSelected ? 2 : 1,
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(role.emoji,
                                style: const TextStyle(fontSize: 20)),
                            const SizedBox(width: AppSpacing.xs),
                            Text(
                              roleLabels[index],
                              style: TextStyle(
                                color: isSelected
                                    ? AppColors.primary
                                    : AppColors.textPrimary,
                                fontWeight: isSelected
                                    ? FontWeight.w600
                                    : FontWeight.normal,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  }),
                  // 직접 입력 옵션
                  GestureDetector(
                    onTap: () => setState(() {
                      _isCustomRole = true;
                      _selectedRoleIndex = null;
                    }),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.md,
                        vertical: AppSpacing.sm,
                      ),
                      decoration: BoxDecoration(
                        color: _isCustomRole
                            ? AppColors.primaryLight
                            : AppColors.surface,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        border: Border.all(
                          color: _isCustomRole
                              ? AppColors.primary
                              : AppColors.divider,
                          width: _isCustomRole ? 2 : 1,
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Text('✏️', style: TextStyle(fontSize: 20)),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            l.charactersFormCustomRole,
                            style: TextStyle(
                              color: _isCustomRole
                                  ? AppColors.primary
                                  : AppColors.textPrimary,
                              fontWeight: _isCustomRole
                                  ? FontWeight.w600
                                  : FontWeight.normal,
                            ),
                          ),
                        ],
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
                    fillColor: AppColors.background,
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
                decoration: InputDecoration(
                  hintText: l.charactersFormNameHint,
                  filled: true,
                  fillColor: AppColors.background,
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
                style:
                    AppTextStyles.caption.copyWith(color: AppColors.textHint),
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                children: _suggestedTraits.map((trait) {
                  final isSelected = _selectedTraits.contains(trait);
                  return GestureDetector(
                    onTap: () => setState(() {
                      if (isSelected) {
                        _selectedTraits.remove(trait);
                      } else {
                        _selectedTraits.add(trait);
                      }
                    }),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.sm,
                        vertical: AppSpacing.xs,
                      ),
                      decoration: BoxDecoration(
                        color:
                            isSelected ? AppColors.primary : AppColors.surface,
                        borderRadius: BorderRadius.circular(AppRadius.sm),
                        border: Border.all(
                          color: isSelected
                              ? AppColors.primary
                              : AppColors.divider,
                        ),
                      ),
                      child: Text(
                        trait,
                        style: TextStyle(
                          fontSize: 13,
                          color: isSelected
                              ? Colors.white
                              : AppColors.textSecondary,
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
                  fillColor: AppColors.background,
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