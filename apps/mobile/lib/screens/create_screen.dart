import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';
import '../widgets/character_source_sheet.dart';
import '../widgets/credit_shortage_modal.dart';
import '../widgets/common_widgets.dart';

/// 책 생성 화면
class CreateScreen extends ConsumerStatefulWidget {
  const CreateScreen({super.key});

  @override
  ConsumerState<CreateScreen> createState() => _CreateScreenState();
}

class _CreateScreenState extends ConsumerState<CreateScreen> {
  final _topicController = TextEditingController();
  final _protagonistController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  TargetAge _selectedAge = TargetAge.age5to7;
  BookStyle _selectedStyle = BookStyle.watercolor;
  BookTheme? _selectedTheme;
  List<String> _selectedCharacterIds = []; // 다중 캐릭터 선택
  bool _isLoading = false;
  bool _didHandleRouteArgs = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_didHandleRouteArgs) {
      return;
    }
    _didHandleRouteArgs = true;
    final args = ModalRoute.of(context)?.settings.arguments;
    if (args is Map) {
      final characterId = args['characterId'];
      if (characterId is String && characterId.isNotEmpty) {
        _selectedCharacterIds = [characterId];
      }
    }
  }

  @override
  void dispose() {
    _topicController.dispose();
    _protagonistController.dispose();
    super.dispose();
  }

  ApiError? _extractApiError(Object error) {
    if (error is ApiError) {
      return error;
    }
    if (error is DioException && error.error is ApiError) {
      return error.error as ApiError;
    }
    return null;
  }

  Future<void> _createBook() async {
    if (!_formKey.currentState!.validate()) return;

    try {
      final credits = await ref.read(apiClientProvider).getCreditsBalance();
      if (credits <= 0) {
        ref.read(analyticsProvider).logEvent(
          AnalyticsEvents.paywallShown,
          params: const {'reason': 'no_credits'},
        );
        if (mounted) {
          await showCreditShortageModal(context);
        }
        return;
      }
    } catch (_) {
      // 잔액 조회 실패 시 생성은 계속 진행 (서버에서 최종 검증)
    }

    setState(() => _isLoading = true);

    try {
      final spec = BookSpec(
        topic: _topicController.text.trim(),
        targetAge: _selectedAge.value,
        style: _selectedStyle.value,
        theme: _selectedTheme?.value,
        protagonistName: _protagonistController.text.trim().isEmpty
            ? null
            : _protagonistController.text.trim(),
        characterIds:
            _selectedCharacterIds.isNotEmpty ? _selectedCharacterIds : null,
      );

      final jobId =
          await ref.read(bookCreationProvider.notifier).createBook(spec);

      ref.read(analyticsProvider).logEvent(
        AnalyticsEvents.bookCreateRequested,
        params: {
          'target_age': _selectedAge.value,
          'style': _selectedStyle.value,
          'has_protagonist': _protagonistController.text.trim().isNotEmpty,
        },
      );

      if (mounted) {
        Navigator.pushReplacementNamed(
          context,
          '/loading',
          arguments: jobId,
        );
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        final apiError = _extractApiError(e);
        if (apiError != null && apiError.code == 'PAYMENT_REQUIRED') {
          final message = apiError.message.trim();
          ref.read(analyticsProvider).logEvent(
            AnalyticsEvents.paywallShown,
            params: const {'reason': 'payment_required'},
          );
          final title = message.contains('스타일') || message.contains('월 ')
              ? l.createPlanUpgradeTitle
              : l.createCreditShortageTitle;
          await showCreditShortageModal(
            context,
            title: title,
            message: message,
          );
          return;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(l.createFailedSnack),
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

  /// '우리 아이를 주인공으로' — 사진/기본 캐릭터 시트를 열어 주인공 캐릭터를 만든다.
  Future<void> _selectChildProtagonist() async {
    final childName = _protagonistController.text.trim();
    final characterId = await showCharacterSourceSheet(
      context,
      childName: childName.isEmpty ? null : childName,
    );
    if (characterId != null && characterId.isNotEmpty && mounted) {
      setState(() => _selectedCharacterIds = [characterId]);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final charactersAsync = ref.watch(charactersProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close, color: AppColors.textPrimary),
          tooltip: l.createCloseTooltip,
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          l.createTitle,
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
            Text(l.createTopicLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            TextFormField(
              controller: _topicController,
              decoration: InputDecoration(
                hintText: l.createTopicHint,
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
                  borderSide:
                      const BorderSide(color: AppColors.primary, width: 2),
                ),
              ),
              maxLines: 3,
              maxLength: 200,
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return l.createTopicRequired;
                }
                if (value.trim().length < 5) {
                  return l.createTopicTooShort;
                }
                return null;
              },
            ),

            const SizedBox(height: AppSpacing.md),

            Text(l.createChildNameLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _protagonistController,
              maxLength: 40,
              decoration: InputDecoration(
                hintText: l.createChildNameHint,
                hintStyle: AppTextStyles.bodySmall,
              ),
            ),

            const SizedBox(height: AppSpacing.lg),

            // 연령대 선택
            Text(l.createAgeLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: TargetAge.values.map((age) {
                final isSelected = _selectedAge == age;
                return ChoiceChip(
                  label: Text(age.label),
                  selected: isSelected,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  labelPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.md,
                  ),
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedAge = age);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: isSelected
                        ? AppColors.primary
                        : AppColors.textSecondary,
                    fontWeight:
                        isSelected ? FontWeight.w600 : FontWeight.normal,
                  ),
                );
              }).toList(),
            ),

            const SizedBox(height: AppSpacing.lg),

            // 그림 스타일 선택
            Text(l.createStyleLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: BookStyle.values.map((style) {
                final isSelected = _selectedStyle == style;
                return ChoiceChip(
                  label: Text(style.label),
                  selected: isSelected,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  labelPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.md,
                  ),
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedStyle = style);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: isSelected
                        ? AppColors.primary
                        : AppColors.textSecondary,
                    fontWeight:
                        isSelected ? FontWeight.w600 : FontWeight.normal,
                  ),
                );
              }).toList(),
            ),

            const SizedBox(height: AppSpacing.lg),

            // 테마 선택 (선택사항)
            Text(l.createThemeLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: Text(l.createThemeNone),
                  selected: _selectedTheme == null,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  labelPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.md,
                  ),
                  onSelected: (selected) {
                    if (selected) setState(() => _selectedTheme = null);
                  },
                  selectedColor: AppColors.primaryMedium,
                  labelStyle: TextStyle(
                    color: _selectedTheme == null
                        ? AppColors.primary
                        : AppColors.textSecondary,
                  ),
                ),
                ...BookTheme.values.map((theme) {
                  final isSelected = _selectedTheme == theme;
                  return ChoiceChip(
                    label: Text(theme.label),
                    selected: isSelected,
                    materialTapTargetSize: MaterialTapTargetSize.padded,
                    labelPadding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.sm,
                      vertical: AppSpacing.md,
                    ),
                    onSelected: (selected) {
                      if (selected) setState(() => _selectedTheme = theme);
                    },
                    selectedColor: AppColors.primaryMedium,
                    labelStyle: TextStyle(
                      color: isSelected
                          ? AppColors.primary
                          : AppColors.textSecondary,
                      fontWeight:
                          isSelected ? FontWeight.w600 : FontWeight.normal,
                    ),
                  );
                }),
              ],
            ),

            const SizedBox(height: AppSpacing.lg),

            // 캐릭터 선택 (선택사항 - 다중 선택 가능)
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(l.createCharacterLabel, style: AppTextStyles.heading3),
                TextButton.icon(
                  onPressed: () => Navigator.pushNamed(context, '/characters'),
                  icon: const Icon(Icons.add, size: 18),
                  label: Text(l.createAddCharacter),
                  style: TextButton.styleFrom(
                    foregroundColor: AppColors.primary,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              l.createCharacterHint,
              style: AppTextStyles.caption.copyWith(color: AppColors.textHint),
            ),
            const SizedBox(height: AppSpacing.sm),
            charactersAsync.when(
              data: (characters) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // AI 자동 생성 옵션 (항상 표시)
                    _CharacterOption(
                      icon: Icons.auto_awesome,
                      iconColor: AppColors.secondary,
                      title: l.createAiCharacterTitle,
                      description: l.createAiCharacterDesc,
                      isSelected: _selectedCharacterIds.isEmpty,
                      onTap: () => setState(() => _selectedCharacterIds = []),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    _CharacterOption(
                      icon: Icons.face_retouching_natural,
                      iconColor: AppColors.primary,
                      title: l.createChildProtagonistTitle,
                      description: l.createChildProtagonistDesc,
                      isSelected: false,
                      onTap: _selectChildProtagonist,
                    ),

                    if (characters.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.md),
                      Row(
                        children: [
                          const Expanded(child: Divider()),
                          Padding(
                            padding: const EdgeInsets.symmetric(
                                horizontal: AppSpacing.sm),
                            child: Text(
                              l.createOrSelectExisting,
                              style: AppTextStyles.caption
                                  .copyWith(color: AppColors.textHint),
                            ),
                          ),
                          const Expanded(child: Divider()),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      if (_selectedCharacterIds.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: AppSpacing.sm,
                                vertical: AppSpacing.xs),
                            decoration: BoxDecoration(
                              color: AppColors.primaryMedium,
                              borderRadius: BorderRadius.circular(AppRadius.sm),
                            ),
                            child: Text(
                              l.createSelectedCount(
                                  _selectedCharacterIds.length),
                              style: AppTextStyles.caption
                                  .copyWith(color: AppColors.primary),
                            ),
                          ),
                        ),
                      // 기존 캐릭터 목록 (체크박스로 다중 선택)
                      ...characters.map((character) => Padding(
                            padding:
                                const EdgeInsets.only(bottom: AppSpacing.sm),
                            child: CharacterCard(
                              name: character.name,
                              description: character.masterDescription,
                              isSelected:
                                  _selectedCharacterIds.contains(character.id),
                              showCheckbox: true,
                              onTap: () {
                                setState(() {
                                  if (_selectedCharacterIds
                                      .contains(character.id)) {
                                    _selectedCharacterIds.remove(character.id);
                                  } else {
                                    _selectedCharacterIds.add(character.id);
                                  }
                                });
                              },
                            ),
                          )),
                    ] else ...[
                      const SizedBox(height: AppSpacing.sm),
                      Container(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        decoration: BoxDecoration(
                          color: AppColors.surface,
                          borderRadius: BorderRadius.circular(AppRadius.md),
                          border: Border.all(color: AppColors.divider),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.info_outline,
                                color: AppColors.textHint, size: 20),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Text(
                                l.createAddCharacterTip,
                                style: AppTextStyles.caption
                                    .copyWith(color: AppColors.textSecondary),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ],
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (_, __) => Text(l.createCharacterLoadError),
            ),

            const SizedBox(height: AppSpacing.xxl),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: const BoxDecoration(
          color: AppColors.surface,
          boxShadow: [
            BoxShadow(
              color: AppColors.blackOverlayLight,
              blurRadius: 10,
              offset: Offset(0, -4),
            ),
          ],
        ),
        child: SafeArea(
          child: PrimaryButton(
            text: l.createMakeButton,
            isLoading: _isLoading,
            onPressed: _createBook,
          ),
        ),
      ),
    );
  }
}

/// AI 캐릭터 생성 옵션 위젯
class _CharacterOption extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String title;
  final String description;
  final bool isSelected;
  final VoidCallback onTap;

  const _CharacterOption({
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.description,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: isSelected ? AppColors.secondaryLight : AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: isSelected ? AppColors.secondary : AppColors.divider,
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: AppSizing.minTouchTarget,
              height: AppSizing.minTouchTarget,
              decoration: BoxDecoration(
                color: iconColor.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Icon(icon, color: iconColor, size: 24),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: AppTextStyles.body.copyWith(
                      fontWeight: FontWeight.w600,
                      color: isSelected
                          ? AppColors.secondary
                          : AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    description,
                    style: AppTextStyles.caption.copyWith(
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
            if (isSelected)
              const Icon(Icons.check_circle,
                  color: AppColors.secondary, size: 24),
          ],
        ),
      ),
    );
  }
}