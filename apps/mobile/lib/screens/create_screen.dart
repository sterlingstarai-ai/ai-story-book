import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

/// 책 생성 화면
class CreateScreen extends ConsumerStatefulWidget {
  const CreateScreen({super.key});

  @override
  ConsumerState<CreateScreen> createState() => _CreateScreenState();
}

class _CreateScreenState extends ConsumerState<CreateScreen> {
  final _topicController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  TargetAge _selectedAge = TargetAge.age5to7;
  BookStyle _selectedStyle = BookStyle.watercolor;
  BookTheme? _selectedTheme;
  String? _selectedCharacterId;
  bool _isLoading = false;

  @override
  void dispose() {
    _topicController.dispose();
    super.dispose();
  }

  Future<void> _createBook() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      final spec = BookSpec(
        topic: _topicController.text.trim(),
        targetAge: _selectedAge.value,
        style: _selectedStyle.value,
        theme: _selectedTheme?.value,
        characterId: _selectedCharacterId,
      );

      final jobId = await ref.read(bookCreationProvider.notifier).createBook(spec);

      if (mounted) {
        Navigator.pushReplacementNamed(
          context,
          '/loading',
          arguments: jobId,
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('책 생성 실패: $e'),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final charactersAsync = ref.watch(charactersProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close, color: AppColors.textPrimary),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text(
          '새 동화책 만들기',
          style: AppTextStyles.heading3,
        ),
        centerTitle: true,
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            // 주제 입력
            const Text('어떤 이야기를 만들까요?', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            TextFormField(
              controller: _topicController,
              decoration: InputDecoration(
                hintText: '예: 토끼가 하늘을 나는 이야기',
                hintStyle: AppTextStyles.bodySmall,
                filled: true,
                fillColor: AppColors.surface,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: const BorderSide(color: AppColors.divider),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: const BorderSide(color: AppColors.divider),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  borderSide: const BorderSide(color: AppColors.primary, width: 2),
                ),
              ),
              maxLines: 3,
              maxLength: 200,
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return '이야기 주제를 입력해주세요';
                }
                if (value.trim().length < 5) {
                  return '조금 더 자세히 입력해주세요';
                }
                return null;
              },
            ),

            const SizedBox(height: AppSpacing.lg),

            // 연령대 선택
            const Text('아이 연령대', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: TargetAge.values.map((age) {
                final isSelected = _selectedAge == age;
                return ChoiceChip(
                  label: Text(age.label),
                  selected: isSelected,
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedAge = age);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: isSelected ? AppColors.primary : AppColors.textSecondary,
                    fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                  ),
                );
              }).toList(),
            ),

            const SizedBox(height: AppSpacing.lg),

            // 그림 스타일 선택
            const Text('그림 스타일', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: BookStyle.values.map((style) {
                final isSelected = _selectedStyle == style;
                return ChoiceChip(
                  label: Text(style.label),
                  selected: isSelected,
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedStyle = style);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: isSelected ? AppColors.primary : AppColors.textSecondary,
                    fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                  ),
                );
              }).toList(),
            ),

            const SizedBox(height: AppSpacing.lg),

            // 테마 선택 (선택사항)
            const Text('테마 (선택)', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: const Text('없음'),
                  selected: _selectedTheme == null,
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedTheme = null);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: _selectedTheme == null ? AppColors.primary : AppColors.textSecondary,
                  ),
                ),
                ...BookTheme.values.map((theme) {
                  final isSelected = _selectedTheme == theme;
                  return ChoiceChip(
                    label: Text(theme.label),
                    selected: isSelected,
                    onSelected: (selected) {
                      if (selected) setState(() => _selectedTheme = theme);
                    },
                    selectedColor: AppColors.primaryMedium,
                    labelStyle: TextStyle(
                      color: isSelected ? AppColors.primary : AppColors.textSecondary,
                      fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                    ),
                  );
                }),
              ],
            ),

            const SizedBox(height: AppSpacing.lg),

            // 캐릭터 선택 (선택사항)
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('캐릭터 (선택)', style: AppTextStyles.heading3),
                TextButton(
                  onPressed: () => Navigator.pushNamed(context, '/characters'),
                  child: Text(
                    '캐릭터 관리',
                    style: AppTextStyles.bodySmall.copyWith(color: AppColors.primary),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            charactersAsync.when(
              data: (characters) {
                if (characters.isEmpty) {
                  return Container(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      border: Border.all(color: AppColors.divider),
                    ),
                    child: Text(
                      '저장된 캐릭터가 없어요.\n새 캐릭터는 책 생성 후 자동으로 저장됩니다.',
                      style: AppTextStyles.bodySmall,
                      textAlign: TextAlign.center,
                    ),
                  );
                }

                return Column(
                  children: [
                    // 새 캐릭터 옵션
                    CharacterCard(
                      name: '새 캐릭터',
                      description: 'AI가 이야기에 맞는 새 캐릭터를 만들어요',
                      isSelected: _selectedCharacterId == null,
                      onTap: () => setState(() => _selectedCharacterId = null),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    // 기존 캐릭터 목록
                    ...characters.map((character) => Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                      child: CharacterCard(
                        name: character.name,
                        description: character.masterDescription,
                        isSelected: _selectedCharacterId == character.id,
                        onTap: () => setState(() => _selectedCharacterId = character.id),
                      ),
                    )),
                  ],
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (_, __) => const Text('캐릭터를 불러올 수 없어요'),
            ),

            const SizedBox(height: AppSpacing.xxl),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.surface,
          boxShadow: [
            BoxShadow(
              color: AppColors.blackOverlayLight,
              blurRadius: 10,
              offset: const Offset(0, -4),
            ),
          ],
        ),
        child: SafeArea(
          child: PrimaryButton(
            text: '동화책 만들기',
            isLoading: _isLoading,
            onPressed: _createBook,
          ),
        ),
      ),
    );
  }
}
