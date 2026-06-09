import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../core/photo_consent.dart';
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
    final charactersAsync = ref.watch(charactersProvider);

    return AppShell(
      currentIndex: 3,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        title: const Text('내 캐릭터', style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon:
                const Icon(Icons.add_circle_outline, color: AppColors.primary),
            onPressed:
                _isCreatingCharacter ? null : () => _showCharacterOptions(),
            tooltip: '캐릭터 추가',
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: AppColors.textPrimary),
            onPressed: () => ref.read(charactersProvider.notifier).refresh(),
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
                  const EmptyState(
                    icon: Icons.people_outline,
                    title: '아직 캐릭터가 없어요',
                    subtitle: '사진으로 캐릭터를 만들어보세요!',
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  PrimaryButton(
                    text: '사진으로 캐릭터 만들기',
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
          title: '캐릭터를 불러올 수 없어요',
          subtitle: error.toString(),
          buttonText: '다시 시도',
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
        label: Text(_isCreatingCharacter ? '생성 중...' : '사진으로 만들기'),
      ),
    );
  }

  void _showCharacterOptions() {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => AdaptiveModalSheet(
        title: '새 캐릭터 만들기',
        subtitle: '캐릭터 생성 방식을 선택하세요',
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.lg),
            ListTile(
              leading: const Icon(Icons.edit_note, color: AppColors.primary),
              title: const Text('직접 입력하기'),
              subtitle: const Text('이름, 나이, 특징만 입력'),
              onTap: () {
                Navigator.pop(context);
                _showTextInputForm();
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.camera_alt, color: AppColors.primary),
              title: const Text('카메라로 촬영'),
              subtitle: const Text('사진을 분석해서 캐릭터 생성'),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library, color: AppColors.primary),
              title: const Text('갤러리에서 선택'),
              subtitle: const Text('기존 사진에서 캐릭터 생성'),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.gallery);
              },
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.brush_outlined, color: AppColors.primary),
              title: const Text('아이 그림에서 변환'),
              subtitle: const Text('그림 사진을 캐릭터+시트로 변환'),
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${result['name']} 캐릭터가 생성되었어요!')),
        );
        ref.read(charactersProvider.notifier).refresh();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('캐릭터 생성에 실패했어요. 잠시 후 다시 시도해주세요.'),
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
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('이미지를 선택할 수 없어요. 다시 시도해주세요.')),
        );
      }
    }
  }

  Future<String?> _showNameDialog() async {
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('캐릭터 이름'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: '캐릭터 이름을 입력하세요 (선택)',
            border: OutlineInputBorder(),
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(
                context, controller.text.isEmpty ? null : controller.text),
            child: const Text('확인'),
          ),
        ],
      ),
    );
    controller.dispose();
    return result;
  }

  Future<void> _showDeleteCharacterDialog(Character character) async {
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('캐릭터 삭제'),
            content: Text('"${character.name}" 캐릭터를 삭제할까요?'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('삭제'),
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('캐릭터가 삭제되었어요.')),
      );
      await ref.read(charactersProvider.notifier).refresh();
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('캐릭터 삭제에 실패했어요. 다시 시도해주세요.')),
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
        final characterName = result['name']?.toString() ?? '새 캐릭터';
        final rawSheetUrls = result['character_sheet_urls'];
        final sheetCount = rawSheetUrls is List ? rawSheetUrls.length : 0;
        final message = creationMode == _CharacterCreationMode.drawing &&
                sheetCount > 0
            ? '$characterName 캐릭터와 시트 $sheetCount장을 만들었어요!'
            : '$characterName 캐릭터가 생성되었어요!';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
        ref.read(charactersProvider.notifier).refresh();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('캐릭터 생성에 실패했어요. 잠시 후 다시 시도해주세요.'),
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
                    isLoading ? '캐릭터 생성 중...' : '새 캐릭터 추가',
                    style: AppTextStyles.heading3.copyWith(
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    '사진으로 나만의 캐릭터를 만들어보세요',
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
                          _formatDate(character.createdAt),
                          style: AppTextStyles.caption,
                        ),
                      ],
                    ),
                  ),
                ],
              ),

              const SizedBox(height: AppSpacing.lg),

              // 설명
              const _SectionTitle('설명'),
              Text(character.masterDescription, style: AppTextStyles.body),

              const SizedBox(height: AppSpacing.lg),

              // 성격
              const _SectionTitle('성격'),
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
              const _SectionTitle('외형'),
              _DetailRow('나이', character.appearance.ageVisual),
              _DetailRow('얼굴', character.appearance.face),
              _DetailRow('머리', character.appearance.hair),
              _DetailRow('피부', character.appearance.skin),
              _DetailRow('체형', character.appearance.body),

              const SizedBox(height: AppSpacing.lg),

              // 의상
              const _SectionTitle('의상'),
              _DetailRow('상의', character.clothing.top),
              _DetailRow('하의', character.clothing.bottom),
              _DetailRow('신발', character.clothing.shoes),
              _DetailRow('액세서리', character.clothing.accessories),

              if (character.visualStyleNotes != null) ...[
                const SizedBox(height: AppSpacing.lg),
                const _SectionTitle('스타일 노트'),
                Text(character.visualStyleNotes!, style: AppTextStyles.body),
              ],

              const SizedBox(height: AppSpacing.xl),

              // 액션 버튼
              PrimaryButton(
                text: '이 캐릭터로 새 책 만들기',
                onPressed: () {
                  Navigator.pop(context);
                  Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {'characterId': character.id},
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

  String _formatDate(DateTime date) {
    return '${date.year}년 ${date.month}월 ${date.day}일 생성';
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
  final String label;
  final String emoji;
  final String ageHint; // AI에게 전달할 나이 힌트

  const _CharacterRole(this.label, this.emoji, this.ageHint);
}

const _characterRoles = [
  _CharacterRole('아이', '👶', '5살 어린이'),
  _CharacterRole('형/오빠', '👦', '10살 소년'),
  _CharacterRole('누나/언니', '👧', '10살 소녀'),
  _CharacterRole('엄마', '👩', '30대 여성'),
  _CharacterRole('아빠', '👨', '30대 남성'),
  _CharacterRole('할머니', '👵', '60대 할머니'),
  _CharacterRole('할아버지', '👴', '60대 할아버지'),
  _CharacterRole('친구', '🧒', '또래 친구'),
  _CharacterRole('선생님', '👩‍🏫', '선생님'),
  _CharacterRole('반려동물', '🐕', '귀여운 반려동물'),
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

  // 추천 성격 특성
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
              const Center(
                child: Text('새 캐릭터 만들기', style: AppTextStyles.heading2),
              ),
              const SizedBox(height: AppSpacing.xl),

              // 1. 역할 선택
              const Text('누구인가요?', style: AppTextStyles.heading3),
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
                              role.label,
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
                            '직접 입력',
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
                    hintText: '예: 삼촌, 이모, 마법사, 요정...',
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
              const Text('이름', style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _nameController,
                decoration: InputDecoration(
                  hintText: '캐릭터 이름을 입력하세요',
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
              const Text('성격/특징', style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.xs),
              Text(
                '여러 개 선택 가능',
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
                  hintText: '추가 특징 입력 (선택)',
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
                text: '캐릭터 만들기',
                onPressed: () {
                  // 역할 확인
                  String role;
                  if (_isCustomRole) {
                    role = _customRoleController.text.trim();
                    if (role.isEmpty) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('역할을 입력해주세요')),
                      );
                      return;
                    }
                  } else if (_selectedRoleIndex != null) {
                    role = _characterRoles[_selectedRoleIndex!].ageHint;
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('역할을 선택해주세요')),
                    );
                    return;
                  }

                  // 이름 확인
                  final name = _nameController.text.trim();
                  if (name.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('이름을 입력해주세요')),
                    );
                    return;
                  }

                  // 특징 확인
                  final traits = _buildTraitsString();
                  if (traits.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('성격/특징을 선택해주세요')),
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
