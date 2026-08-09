import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../services/analytics.dart';
import '../utils/constants.dart';
import '../utils/spec_labels.dart';
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
  String _selectedLanguage =
      'ko'; // 이야기 생성 언어 (didChangeDependencies에서 로캘 기반 초기화)
  BookStyle _selectedStyle = BookStyle.watercolor;
  BookTheme? _selectedTheme;
  List<String> _selectedCharacterIds = []; // 다중 캐릭터 선택
  String? _selectedRelationship; // 다중 선택 시 캐릭터 관계 (남매/친구/가족)
  final Set<String> _forbiddenElements = {}; // 빼고 싶은 요소 (콘텐츠 안전)
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
      // 신규: characterIds 배열 / 레거시: 단일 characterId — 둘 다 수용해 병합
      final ids = args['characterIds'];
      if (ids is List) {
        final parsed =
            ids.whereType<String>().where((s) => s.isNotEmpty).toList();
        if (parsed.isNotEmpty) {
          _selectedCharacterIds = parsed;
        }
      }
      final characterId = args['characterId'];
      if (characterId is String &&
          characterId.isNotEmpty &&
          !_selectedCharacterIds.contains(characterId)) {
        _selectedCharacterIds = [..._selectedCharacterIds, characterId];
      }
      // 홈의 '내 아이로 동화 만들기' 진입 → 사진/캐릭터 시트를 바로 연다.
      if (args['startPhotoCharacter'] == true) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            _selectChildProtagonist();
          }
        });
      }
    }
    // 이야기 언어 기본값을 현재 UI 로캘에서 추론(글로벌 — 지원 언어가 아니면 영어).
    const supportedStoryLangs = {'ko', 'en', 'ja'};
    final localeCode = Localizations.localeOf(context).languageCode;
    _selectedLanguage =
        supportedStoryLangs.contains(localeCode) ? localeCode : 'en';
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
        language: _selectedLanguage,
        targetAge: _selectedAge.value,
        style: _selectedStyle.value,
        theme: _selectedTheme?.value,
        protagonistName: _protagonistController.text.trim().isEmpty
            ? null
            : _protagonistController.text.trim(),
        characterIds:
            _selectedCharacterIds.isNotEmpty ? _selectedCharacterIds : null,
        characterRelationship:
            _selectedCharacterIds.length >= 2 ? _selectedRelationship : null,
        forbiddenElements:
            _forbiddenElements.isNotEmpty ? _forbiddenElements.toList() : null,
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
          // M5: 서버가 내려주는 안정 키(error.details.reason)로 분기한다.
          // 한국어 메시지 부분 매칭은 서버 로컬라이즈/문구 변경에 조용히 깨졌다.
          final title = apiError.isPlanUpgradeRequired
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

  /// 선택된 연령대에 맞는 문체·어휘 안내 문구 (언어 중립적 발달 단계 기준).
  String _ageHelpText(AppLocalizations l) {
    switch (_selectedAge) {
      case TargetAge.age3to5:
        return l.createAgeHelp3to5;
      case TargetAge.age5to7:
        return l.createAgeHelp5to7;
      case TargetAge.age7to9:
        return l.createAgeHelp7to9;
      case TargetAge.adult:
        return l.createAgeHelpAdult;
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final charactersAsync = ref.watch(charactersProvider);

    // 추천 빠른 시작 템플릿 — 보편 테마(글로벌). 탭하면 주제·테마를 채워준다.
    final templates =
        <({String label, String topic, BookTheme theme, IconData icon})>[
      (
        label: l.createTemplateAnimalLabel,
        topic: l.createTemplateAnimalTopic,
        theme: BookTheme.animal,
        icon: Icons.pets,
      ),
      (
        label: l.createTemplateFriendshipLabel,
        topic: l.createTemplateFriendshipTopic,
        theme: BookTheme.friendship,
        icon: Icons.favorite,
      ),
      (
        label: l.createTemplateFeelingsLabel,
        topic: l.createTemplateFeelingsTopic,
        theme: BookTheme.emotionalCoaching,
        icon: Icons.sentiment_satisfied_alt,
      ),
      (
        label: l.createTemplateSpaceLabel,
        topic: l.createTemplateSpaceTopic,
        theme: BookTheme.science,
        icon: Icons.rocket_launch,
      ),
    ];

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
            // 연령대 선택 (가장 먼저 노출 — 연령별 문체·어휘가 이야기 생성에 직접 반영됨)
            Text(l.createAgeLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: TargetAge.values.map((age) {
                final isSelected = _selectedAge == age;
                return ChoiceChip(
                  label: Text(age.localizedLabel(l)),
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
            const SizedBox(height: AppSpacing.sm),
            // 연령별 문체 안내 (선택에 따라 라이브 업데이트)
            _AgeHelpBanner(text: _ageHelpText(l)),

            const SizedBox(height: AppSpacing.lg),

            // 추천 템플릿(빠른 시작) — 탭하면 주제·테마 자동 입력
            Text(l.createTemplateSectionLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            SizedBox(
              height: 40,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: templates.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(width: AppSpacing.sm),
                itemBuilder: (context, index) {
                  final t = templates[index];
                  return ActionChip(
                    avatar: Icon(t.icon, size: 18, color: AppColors.primary),
                    label: Text(t.label),
                    onPressed: () => setState(() {
                      _topicController.text = t.topic;
                      _selectedTheme = t.theme;
                    }),
                    backgroundColor: AppColors.surface,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      side: const BorderSide(color: AppColors.divider),
                    ),
                  );
                },
              ),
            ),

            const SizedBox(height: AppSpacing.lg),

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

            // 이야기 언어 (글로벌 — 네이티브 표기, 기본값은 UI 로캘)
            Text(l.createLanguageLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: {
                'ko': '한국어',
                'en': 'English',
                'ja': '日本語',
              }.entries.map((e) {
                final isSelected = _selectedLanguage == e.key;
                return ChoiceChip(
                  label: Text(e.value),
                  selected: isSelected,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  labelPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.md,
                  ),
                  onSelected: (selected) {
                    if (selected) {
                      setState(() => _selectedLanguage = e.key);
                    }
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
                  label: Text(style.localizedLabel(l)),
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
                    label: Text(theme.localizedLabel(l)),
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

            // 캐릭터 2명 이상 선택 시 관계 선택 (남매/친구 스토리 역학에 반영)
            if (_selectedCharacterIds.length >= 2) ...[
              const SizedBox(height: AppSpacing.lg),
              Text(l.createRelationshipLabel, style: AppTextStyles.heading3),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                children: [
                  l.createRelationshipFriends,
                  l.createRelationshipSiblings,
                  l.createRelationshipFamily,
                ].map((rel) {
                  final isSelected = _selectedRelationship == rel;
                  return ChoiceChip(
                    label: Text(rel),
                    selected: isSelected,
                    materialTapTargetSize: MaterialTapTargetSize.padded,
                    labelPadding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.sm,
                      vertical: AppSpacing.md,
                    ),
                    onSelected: (selected) {
                      setState(
                          () => _selectedRelationship = selected ? rel : null);
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
            ],

            // 빼고 싶은 요소 (콘텐츠 안전) — 다중 선택, forbidden_elements로 전달
            const SizedBox(height: AppSpacing.lg),
            Text(l.createForbiddenLabel, style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                l.createForbiddenViolence,
                l.createForbiddenScary,
                l.createForbiddenSad,
                l.createForbiddenRude,
              ].map((item) {
                final isSelected = _forbiddenElements.contains(item);
                return FilterChip(
                  label: Text(item),
                  selected: isSelected,
                  materialTapTargetSize: MaterialTapTargetSize.padded,
                  onSelected: (selected) {
                    setState(() {
                      if (selected) {
                        _forbiddenElements.add(item);
                      } else {
                        _forbiddenElements.remove(item);
                      }
                    });
                  },
                  selectedColor: AppColors.primaryMedium,
                  checkmarkColor: AppColors.primary,
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

/// 연령대 선택 바로 아래에 표시되는 문체·어휘 안내 배너.
/// 선택한 연령에 따라 문구가 라이브로 갱신된다.
class _AgeHelpBanner extends StatelessWidget {
  final String text;

  const _AgeHelpBanner({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.secondaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Row(
        children: [
          const Icon(Icons.auto_stories, size: 18, color: AppColors.secondary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: AppTextStyles.caption
                  .copyWith(color: AppColors.textSecondary),
            ),
          ),
        ],
      ),
    );
  }
}
