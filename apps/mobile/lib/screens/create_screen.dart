import '../widgets/active_child_button.dart';
import 'characters_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../models/generation_options.dart';
import '../providers/providers.dart';
import '../providers/active_child_profile.dart';
import '../services/analytics.dart';
import '../services/page_audio_playback.dart';
import '../utils/constants.dart';
import '../utils/spec_labels.dart';
import '../widgets/character_source_sheet.dart';
import '../widgets/character_avatar_preview.dart';
import '../widgets/credit_shortage_modal.dart';
import '../widgets/common_widgets.dart';
import '../widgets/narration_style_previews.dart';

String createFailureMessage(AppLocalizations l, ApiError? error) {
  switch (error?.code) {
    case 'PHOTO_PROCESSING_UNAVAILABLE':
      return l.characterAvatarUnavailable;
    case 'CHARACTER_APPROVAL_REQUIRED':
      return l.characterAvatarNeedsApproval;
    case 'CHARACTER_REFERENCE_UNAVAILABLE':
      return l.characterAvatarReferenceUnavailable;
    case 'AVATAR_MULTIPLE_REFERENCES_UNSUPPORTED':
    case 'PHOTO_CHARACTER_SELECTION_INVALID':
      return l.characterSelectionInvalid;
    case 'SAFETY_INPUT':
      return l.createSafetyInputHint;
    case 'SAFETY_OUTPUT':
      return l.createSafetyOutputHint;
    case 'DAILY_LIMIT_EXCEEDED':
      return l.createDailyLimitHint;
    case 'TIMEOUT':
    case 'CONNECTION_ERROR':
    case 'NETWORK_ERROR':
    case 'VALIDATION_ERROR':
    case 'UNAUTHORIZED':
    case 'FORBIDDEN':
    case 'RATE_LIMIT_EXCEEDED':
    case 'INTERNAL_ERROR':
    case 'PARENTAL_CONSENT_REQUIRED':
    case 'AI_SERVICE_UNAVAILABLE':
    case 'SERVICE_UNAVAILABLE':
    case 'BAD_GATEWAY':
    case 'GATEWAY_TIMEOUT':
    case 'CANCELLED':
      return error!.localizedMessage(l);
    default:
      return l.createFailedSnack;
  }
}

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
  final _topicFieldKey = GlobalKey<FormFieldState<String>>();
  late final Future<void> _profileDefaultsReady;
  bool _editedName = false;
  bool _editedAge = false;
  bool _showAgePreview = false;

  TargetAge? _ageChoice;
  TargetAge get _selectedAge =>
      _ageChoice ??
      (ref.read(capabilitiesProvider).valueOrNull?['free_first_book_trial'] ==
              true
          ? TargetAge.age3to5
          : TargetAge.age5to7);
  String _selectedLanguage =
      'ko'; // 이야기 생성 언어 (didChangeDependencies에서 로캘 기반 초기화)
  BookStyle _selectedStyle = BookStyle.watercolor;
  int _selectedPageCount = 12;
  BookTheme? _selectedTheme;
  List<String> _selectedCharacterIds = []; // 다중 캐릭터 선택
  String? _selectedRelationship; // 다중 선택 시 캐릭터 관계 (남매/친구/가족)
  final Set<String> _forbiddenElements = {}; // 빼고 싶은 요소 (콘텐츠 안전)
  bool _isLoading = false;
  bool _isSelectingCharacter = false;
  bool _didHandleRouteArgs = false;

  @override
  void initState() {
    super.initState();
    _profileDefaultsReady = _loadProfileDefaults();
  }

  Future<void> _loadProfileDefaults() async {
    try {
      final profile = await ref.refresh(activeChildProfileProvider.future);
      if (!mounted || profile == null) return;
      setState(() {
        if (!_editedName) _protagonistController.text = profile.name;
        if (!_editedAge) _ageChoice = profile.targetAge;
      });
    } catch (_) {
      // Optional defaults must not prevent a parent from entering details.
    }
  }

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
        final parsed = ids
            .whereType<String>()
            .where((s) => s.isNotEmpty)
            .toList();
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
        WidgetsBinding.instance.addPostFrameCallback((_) async {
          await _profileDefaultsReady;
          if (mounted) await _selectChildProtagonist();
        });
      }
    }
    // 이야기 언어 기본값을 현재 UI 로캘에서 추론(글로벌 — 지원 언어가 아니면 영어).
    const supportedStoryLangs = {'ko', 'en', 'ja'};
    final localeCode = Localizations.localeOf(context).languageCode;
    _selectedLanguage = supportedStoryLangs.contains(localeCode)
        ? localeCode
        : 'en';
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
    if (_isLoading) return;
    if (!_formKey.currentState!.validate()) {
      final fieldContext = _topicFieldKey.currentContext;
      if (fieldContext != null) {
        await Scrollable.ensureVisible(
          fieldContext,
          duration: const Duration(milliseconds: 250),
          alignment: 0.2,
        );
      }
      return;
    }
    final optionsState = ref.read(generationOptionsProvider);
    final options = optionsState.isLoading || optionsState.hasError
        ? null
        : optionsState.asData?.value;
    final selectedStyle = _styleFor(options);
    if (selectedStyle == null) return;
    final api = ref.read(apiClientProvider);
    // Reserve the attempt before the first async call so repeated taps cannot
    // race the credit lookup and create more than one book.
    setState(() => _isLoading = true);

    try {
      // Recheck route arguments and cached choices in the active profile before spending.
      final verifiedCharacters = <Character>[];
      for (final id in List<String>.of(_selectedCharacterIds)) {
        final character = await api.getCharacter(id);
        if (!mounted || !identical(api, ref.read(apiClientProvider))) return;
        if (!character.canUseInBook) {
          final preview = await showCharacterAvatarPreview(
            context,
            characterId: id,
            initialCharacter: character,
          );
          if (!mounted || preview?.character?.canUseInBook != true) return;
          ref.invalidate(charactersProvider);
        }
        verifiedCharacters.add(character);
      }
      final photoHeroes = verifiedCharacters
          .where((c) => c.needsAvatarApproval)
          .toList();
      if (photoHeroes.length > 1) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                AppLocalizations.of(context).characterSelectionInvalid,
              ),
            ),
          );
        }
        return;
      }
      if (photoHeroes.isNotEmpty) {
        final heroId = photoHeroes.single.id;
        setState(
          () => _selectedCharacterIds = [
            heroId,
            ..._selectedCharacterIds.where((id) => id != heroId),
          ],
        );
      }
      try {
        final credits = await api.getCreditsBalance();
        if (!mounted) return;
        if (credits <= 0) {
          ref
              .read(analyticsProvider)
              .logEvent(
                AnalyticsEvents.paywallShown,
                params: const {'reason': 'no_credits'},
              );
          await showCreditShortageModal(context, preferCreditPack: true);
          return;
        }
      } catch (_) {
        // The server still validates credits if the preliminary lookup fails.
      }
      if (!mounted) return;
      final latestOptions = ref.read(generationOptionsProvider);
      if (!identical(api, ref.read(apiClientProvider)) ||
          latestOptions.isLoading ||
          latestOptions.hasError ||
          !identical(options, latestOptions.asData?.value)) {
        return;
      }

      // Keep retries stable if the capabilities request finishes after submit.
      _ageChoice ??= _selectedAge;
      final spec = BookSpec(
        topic: _topicController.text.trim(),
        language: _selectedLanguage,
        targetAge: _selectedAge.value,
        style: selectedStyle.value,
        pageCount: _selectedPageCount,
        theme: _selectedTheme?.value,
        protagonistName: _protagonistController.text.trim().isEmpty
            ? null
            : _protagonistController.text.trim(),
        characterIds: _selectedCharacterIds.isNotEmpty
            ? _selectedCharacterIds
            : null,
        characterRelationship: _selectedCharacterIds.length >= 2
            ? _selectedRelationship
            : null,
        forbiddenElements: _forbiddenElements.isNotEmpty
            ? _forbiddenElements.toList()
            : null,
      );

      final jobId = await ref
          .read(bookCreationProvider.notifier)
          .createBook(spec);

      ref
          .read(analyticsProvider)
          .logEvent(
            AnalyticsEvents.bookCreateRequested,
            params: {
              'target_age': spec.targetAge,
              'style': selectedStyle.value,
              'has_protagonist': _protagonistController.text.trim().isNotEmpty,
            },
          );

      if (mounted) {
        Navigator.pushReplacementNamed(context, '/loading', arguments: jobId);
      }
    } catch (e) {
      if (mounted) {
        final l = AppLocalizations.of(context);
        final apiError = _extractApiError(e);
        if (apiError != null && apiError.code == 'PAYMENT_REQUIRED') {
          final message = apiError.localizedMessage(l);
          ref
              .read(analyticsProvider)
              .logEvent(
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
            preferCreditPack: !apiError.isPlanUpgradeRequired,
          );
          return;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(createFailureMessage(l, apiError)),
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

  /// Prefer the selected style only while the server still authorizes it.
  BookStyle? _styleFor(GenerationOptions? options) {
    final allowed = options?.allowedStyles ?? const <BookStyle>[];
    if (allowed.contains(_selectedStyle)) return _selectedStyle;
    return allowed.isEmpty ? null : allowed.first;
  }

  /// '우리 아이를 주인공으로' — 사진/기본 캐릭터 시트를 열어 주인공 캐릭터를 만든다.
  Future<void> _selectChildProtagonist() async {
    final childName = _protagonistController.text.trim();
    final characterId = await showCharacterSourceSheet(
      context,
      childName: childName,
    );
    if (characterId != null && characterId.isNotEmpty && mounted) {
      setState(() => _selectedCharacterIds = [characterId]);
    }
  }

  void _selectReadyCharacter(Character character) {
    final known = ref.read(charactersProvider).asData?.value ?? <Character>[];
    final manualIds = known
        .where((c) => !c.needsAvatarApproval)
        .map((c) => c.id)
        .toSet();
    setState(() {
      if (character.needsAvatarApproval) {
        _selectedCharacterIds = [
          character.id,
          ..._selectedCharacterIds.where(
            (id) => manualIds.contains(id) && id != character.id,
          ),
        ];
      } else if (!_selectedCharacterIds.contains(character.id)) {
        _selectedCharacterIds.add(character.id);
      }
    });
  }

  Future<void> _toggleCharacter(Character character) async {
    if (_isSelectingCharacter || _isLoading) return;
    if (_selectedCharacterIds.contains(character.id)) {
      setState(() => _selectedCharacterIds.remove(character.id));
      return;
    }
    if (character.canUseInBook) {
      _selectReadyCharacter(character);
      return;
    }
    setState(() => _isSelectingCharacter = true);
    try {
      final result = await showCharacterAvatarPreview(
        context,
        characterId: character.id,
        initialCharacter: character,
      );
      if (!mounted) return;
      ref.invalidate(charactersProvider);
      if (result?.character?.canUseInBook == true) {
        _selectReadyCharacter(result!.character!);
      } else if (result?.chooseAnotherPhoto == true) {
        await _selectChildProtagonist();
      }
    } finally {
      if (mounted) setState(() => _isSelectingCharacter = false);
    }
  }

  void _openNarrationPreviews() {
    final l = AppLocalizations.of(context);
    final isKorean = Localizations.localeOf(context).languageCode == 'ko';
    FocusManager.instance.primaryFocus?.unfocus();
    final prefs = ref.read(sharedPreferencesProvider);
    final voice = narrationVoiceOrDefault(
      prefs.getString(narrationVoicePreferenceKey),
    );
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (context) => SafeArea(
        top: false,
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            0,
            AppSpacing.lg,
            AppSpacing.md,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Semantics(
                      header: true,
                      child: Text(
                        l.settingsNarrationStyle,
                        style: AppTextStyles.heading3,
                      ),
                    ),
                  ),
                  IconButton(
                    style: IconButton.styleFrom(
                      minimumSize: const Size.square(AppSizing.minTouchTarget),
                    ),
                    tooltip: l.createCloseTooltip,
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              if (!isKorean) Text(l.createNarrationPreviewSampleLanguage),
              NarrationStylePreviews(voice: voice),
            ],
          ),
        ),
      ),
    );
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
    final showNarrationPreviews = ref.watch(
      capabilitiesProvider.select((caps) {
        final capabilities = caps.valueOrNull;
        return narrationSupported(capabilities) &&
            capabilities?['narration_style_selection_supported'] == true;
      }),
    );
    ref.watch(
      capabilitiesProvider.select(
        (caps) => caps.valueOrNull?['free_first_book_trial'] == true,
      ),
    );
    final optionsAsync = ref.watch(generationOptionsProvider);
    final options = optionsAsync.isLoading || optionsAsync.hasError
        ? null
        : optionsAsync.asData?.value;
    final allowedStyles = options?.allowedStyles ?? const <BookStyle>[];
    final selectedStyle = _styleFor(options);
    final agePreview = switch (_selectedAge) {
      TargetAge.age3to5 => l.createAgePreview3to5,
      TargetAge.age5to7 => l.createAgePreview5to7,
      TargetAge.age7to9 => l.createAgePreview7to9,
      TargetAge.adult => null,
    };

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
      backgroundColor: AppPalette.of(context).background,
      appBar: AppBar(
        backgroundColor: AppPalette.of(context).background,
        elevation: 0,
        leading: IconButton(
          icon: Icon(Icons.close, color: AppPalette.of(context).textPrimary),
          tooltip: l.createCloseTooltip,
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(l.createTitle, style: AppTextStyles.heading3),
        centerTitle: true,
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            // Keep the short form mounted so off-screen fields still validate.
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const ActiveChildButton(),
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
                        if (selected) {
                          setState(() {
                            _editedAge = true;
                            _ageChoice = age;
                          });
                        }
                      },
                      selectedColor: AppPalette.of(context).primaryLight,
                      labelStyle: TextStyle(
                        color: isSelected
                            ? AppPalette.of(context).primary
                            : AppPalette.of(context).textSecondary,
                        fontWeight: isSelected
                            ? FontWeight.w600
                            : FontWeight.normal,
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppSpacing.sm),
                // 연령별 문체 안내 (선택에 따라 라이브 업데이트)
                _AgeHelpBanner(text: _ageHelpText(l)),
                if (agePreview != null) ...[
                  TextButton.icon(
                    style: TextButton.styleFrom(
                      minimumSize: const Size(0, AppSizing.minTouchTarget),
                    ),
                    onPressed: () => setState(() {
                      _showAgePreview = !_showAgePreview;
                    }),
                    icon: Icon(
                      _showAgePreview ? Icons.expand_less : Icons.expand_more,
                    ),
                    label: Text(
                      _showAgePreview
                          ? l.createAgePreviewHide
                          : l.createAgePreviewTitle,
                    ),
                  ),
                  if (_showAgePreview)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(AppSpacing.md),
                      decoration: BoxDecoration(
                        color: AppPalette.of(context).surface,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        border: Border.all(
                          color: AppPalette.of(context).divider,
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            l.createAgePreviewCaption,
                            style: AppTextStyles.caption.copyWith(
                              color: AppPalette.of(context).textSecondary,
                            ),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          Text(
                            agePreview,
                            style: AppTextStyles.body.copyWith(height: 1.55),
                          ),
                        ],
                      ),
                    ),
                ],

                if (showNarrationPreviews)
                  TextButton.icon(
                    style: TextButton.styleFrom(
                      minimumSize: const Size(0, AppSizing.minTouchTarget),
                    ),
                    onPressed: _openNarrationPreviews,
                    icon: const Icon(Icons.headphones_outlined),
                    label: Text(l.createNarrationPreviewTitle),
                  ),

                const SizedBox(height: AppSpacing.lg),

                // 추천 템플릿(빠른 시작) — 탭하면 주제·테마 자동 입력
                Text(
                  l.createTemplateSectionLabel,
                  style: AppTextStyles.heading3,
                ),
                const SizedBox(height: AppSpacing.sm),
                SizedBox(
                  height: AppSizing.minTouchTarget,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: templates.length,
                    separatorBuilder: (_, __) =>
                        const SizedBox(width: AppSpacing.sm),
                    itemBuilder: (context, index) {
                      final t = templates[index];
                      return ActionChip(
                        materialTapTargetSize: MaterialTapTargetSize.padded,
                        padding: const EdgeInsets.symmetric(
                          vertical: AppSpacing.md,
                        ),
                        avatar: Icon(
                          t.icon,
                          size: 18,
                          color: AppPalette.of(context).primary,
                        ),
                        label: Text(t.label),
                        onPressed: () => setState(() {
                          _topicController.text = t.topic;
                          _topicFieldKey.currentState?.didChange(t.topic);
                          _topicFieldKey.currentState?.validate();
                          _selectedTheme = t.theme;
                        }),
                        backgroundColor: AppPalette.of(context).surface,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(AppRadius.md),
                          side: BorderSide(
                            color: AppPalette.of(context).divider,
                          ),
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
                  key: _topicFieldKey,
                  controller: _topicController,
                  decoration: InputDecoration(
                    hintText: l.createTopicHint,
                    hintStyle: AppTextStyles.bodySmall,
                    filled: true,
                    fillColor: AppPalette.of(context).surface,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      borderSide: BorderSide(
                        color: AppPalette.of(context).divider,
                      ),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      borderSide: BorderSide(
                        color: AppPalette.of(context).divider,
                      ),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      borderSide: BorderSide(
                        color: AppPalette.of(context).primary,
                        width: 2,
                      ),
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
                  onChanged: (_) => _editedName = true,
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
                  children: {'ko': '한국어', 'en': 'English', 'ja': '日本語'}.entries
                      .map((e) {
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
                          selectedColor: AppPalette.of(context).primaryLight,
                          labelStyle: TextStyle(
                            color: isSelected
                                ? AppPalette.of(context).primary
                                : AppPalette.of(context).textSecondary,
                            fontWeight: isSelected
                                ? FontWeight.w600
                                : FontWeight.normal,
                          ),
                        );
                      })
                      .toList(),
                ),

                const SizedBox(height: AppSpacing.lg),

                Text(l.createLengthLabel, style: AppTextStyles.heading3),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [12, 8].map((count) {
                    final isSelected = _selectedPageCount == count;
                    return ConstrainedBox(
                      constraints: const BoxConstraints(
                        minHeight: AppSizing.minTouchTarget,
                      ),
                      child: ChoiceChip(
                        key: ValueKey('story-length-$count'),
                        label: Text(
                          count == 12
                              ? l.createLengthStandard
                              : l.createLengthShort,
                        ),
                        selected: isSelected,
                        materialTapTargetSize: MaterialTapTargetSize.padded,
                        labelPadding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.sm,
                          vertical: AppSpacing.md,
                        ),
                        onSelected: (selected) {
                          if (selected) {
                            setState(() => _selectedPageCount = count);
                          }
                        },
                        selectedColor: AppPalette.of(context).primaryLight,
                        labelStyle: TextStyle(
                          color: isSelected
                              ? AppPalette.of(context).primary
                              : AppPalette.of(context).textSecondary,
                          fontWeight: isSelected
                              ? FontWeight.w600
                              : FontWeight.normal,
                        ),
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(l.createLengthHint, style: AppTextStyles.bodySmall),

                const SizedBox(height: AppSpacing.lg),

                // 그림 스타일 선택
                Text(l.createStyleLabel, style: AppTextStyles.heading3),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: allowedStyles.map((style) {
                    final isSelected = selectedStyle == style;
                    return ChoiceChip(
                      label: Text(style.localizedLabel(l)),
                      selected: isSelected,
                      materialTapTargetSize: MaterialTapTargetSize.padded,
                      labelPadding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.sm,
                        vertical: AppSpacing.md,
                      ),
                      onSelected: _isLoading
                          ? null
                          : (selected) {
                              if (selected) {
                                setState(() => _selectedStyle = style);
                              }
                            },
                      selectedColor: AppPalette.of(context).primaryLight,
                      labelStyle: TextStyle(
                        color: isSelected
                            ? AppPalette.of(context).primary
                            : AppPalette.of(context).textSecondary,
                        fontWeight: isSelected
                            ? FontWeight.w600
                            : FontWeight.normal,
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  l.createAvailableStylesHint,
                  style: AppTextStyles.bodySmall,
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
                      selectedColor: AppPalette.of(context).primaryLight,
                      labelStyle: TextStyle(
                        color: _selectedTheme == null
                            ? AppPalette.of(context).primary
                            : AppPalette.of(context).textSecondary,
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
                        selectedColor: AppPalette.of(context).primaryLight,
                        labelStyle: TextStyle(
                          color: isSelected
                              ? AppPalette.of(context).primary
                              : AppPalette.of(context).textSecondary,
                          fontWeight: isSelected
                              ? FontWeight.w600
                              : FontWeight.normal,
                        ),
                      );
                    }),
                  ],
                ),

                const SizedBox(height: AppSpacing.lg),

                // 캐릭터 선택 (선택사항 - 다중 선택 가능)
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.xs,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(l.createCharacterLabel, style: AppTextStyles.heading3),
                    TextButton.icon(
                      onPressed: () async {
                        final character = await Navigator.push<Character>(
                          context,
                          MaterialPageRoute(
                            builder: (_) =>
                                const CharactersScreen(selectionMode: true),
                          ),
                        );
                        if (!mounted || character == null) return;
                        setState(() {
                          if (!_selectedCharacterIds.contains(character.id)) {
                            _selectedCharacterIds = [
                              ..._selectedCharacterIds,
                              character.id,
                            ];
                          }
                        });
                        ref.invalidate(charactersProvider);
                      },
                      icon: const Icon(Icons.add, size: 18),
                      label: Text(l.createAddCharacter),
                      style: TextButton.styleFrom(
                        foregroundColor: AppPalette.of(context).primary,
                        minimumSize: const Size(64, 64),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(l.createCharacterHint, style: AppTextStyles.bodySmall),
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
                          onTap: () =>
                              setState(() => _selectedCharacterIds = []),
                        ),
                        const SizedBox(height: AppSpacing.sm),
                        _CharacterOption(
                          icon: Icons.face_retouching_natural,
                          iconColor: AppPalette.of(context).primary,
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
                              Flexible(
                                flex: 4,
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: AppSpacing.sm,
                                  ),
                                  child: Text(
                                    l.createOrSelectExisting,
                                    textAlign: TextAlign.center,
                                    style: AppTextStyles.caption.copyWith(
                                      color: AppPalette.of(context).textHint,
                                    ),
                                  ),
                                ),
                              ),
                              const Expanded(child: Divider()),
                            ],
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          if (_selectedCharacterIds.isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.only(
                                bottom: AppSpacing.sm,
                              ),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: AppSpacing.sm,
                                  vertical: AppSpacing.xs,
                                ),
                                decoration: BoxDecoration(
                                  color: AppPalette.of(context).primaryLight,
                                  borderRadius: BorderRadius.circular(
                                    AppRadius.sm,
                                  ),
                                ),
                                child: Text(
                                  l.createSelectedCount(
                                    _selectedCharacterIds.length,
                                  ),
                                  style: AppTextStyles.caption.copyWith(
                                    color: AppPalette.of(context).primary,
                                  ),
                                ),
                              ),
                            ),
                          // 기존 캐릭터 목록 (체크박스로 다중 선택)
                          ...characters.map(
                            (character) => Padding(
                              padding: const EdgeInsets.only(
                                bottom: AppSpacing.sm,
                              ),
                              child: CharacterCard(
                                name: character.name,
                                avatar: character.needsAvatarApproval
                                    ? CharacterAvatarThumbnail(
                                        character: character,
                                        size: 48,
                                      )
                                    : null,
                                statusLabel: character.needsAvatarApproval
                                    ? (_selectedCharacterIds.isNotEmpty &&
                                              _selectedCharacterIds.first ==
                                                  character.id
                                          ? l.characterAvatarHeroLabel
                                          : characterAvatarStatusLabel(
                                              l,
                                              character,
                                            ))
                                    : null,
                                description: characterDisplayDescription(
                                  l,
                                  character,
                                ),
                                isSelected: _selectedCharacterIds.contains(
                                  character.id,
                                ),
                                showCheckbox: true,
                                onTap: _isSelectingCharacter
                                    ? null
                                    : () => _toggleCharacter(character),
                              ),
                            ),
                          ),
                        ] else ...[
                          const SizedBox(height: AppSpacing.sm),
                          Container(
                            padding: const EdgeInsets.all(AppSpacing.md),
                            decoration: BoxDecoration(
                              color: AppPalette.of(context).surface,
                              borderRadius: BorderRadius.circular(AppRadius.md),
                              border: Border.all(
                                color: AppPalette.of(context).divider,
                              ),
                            ),
                            child: Row(
                              children: [
                                Icon(
                                  Icons.info_outline,
                                  color: AppPalette.of(context).textHint,
                                  size: 20,
                                ),
                                const SizedBox(width: AppSpacing.sm),
                                Expanded(
                                  child: Text(
                                    l.createAddCharacterTip,
                                    style: AppTextStyles.caption.copyWith(
                                      color: AppPalette.of(
                                        context,
                                      ).textSecondary,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    );
                  },
                  loading: () =>
                      const Center(child: CircularProgressIndicator()),
                  error: (_, __) => Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        l.createCharacterLoadError,
                        style: AppTextStyles.bodySmall,
                      ),
                      TextButton.icon(
                        onPressed: () => ref.invalidate(charactersProvider),
                        icon: const Icon(Icons.refresh),
                        label: Text(l.retry),
                        style: TextButton.styleFrom(
                          minimumSize: const Size(64, 64),
                        ),
                      ),
                    ],
                  ),
                ),

                // 캐릭터 2명 이상 선택 시 관계 선택 (남매/친구 스토리 역학에 반영)
                if (_selectedCharacterIds.length >= 2) ...[
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    l.createRelationshipLabel,
                    style: AppTextStyles.heading3,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Wrap(
                    spacing: AppSpacing.sm,
                    children:
                        [
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
                                () => _selectedRelationship = selected
                                    ? rel
                                    : null,
                              );
                            },
                            selectedColor: AppPalette.of(context).primaryLight,
                            labelStyle: TextStyle(
                              color: isSelected
                                  ? AppPalette.of(context).primary
                                  : AppPalette.of(context).textSecondary,
                              fontWeight: isSelected
                                  ? FontWeight.w600
                                  : FontWeight.normal,
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
                  children:
                      [
                        l.createForbiddenViolence,
                        l.createForbiddenScary,
                        l.createForbiddenSad,
                        l.createForbiddenRude,
                      ].map((item) {
                        final isSelected = _forbiddenElements.contains(item);
                        return FilterChip(
                          label: Text(item),
                          labelPadding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.sm,
                            vertical: AppSpacing.md,
                          ),
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
                          selectedColor: AppPalette.of(context).primaryLight,
                          checkmarkColor: AppPalette.of(context).primary,
                          labelStyle: TextStyle(
                            color: isSelected
                                ? AppPalette.of(context).primary
                                : AppPalette.of(context).textSecondary,
                            fontWeight: isSelected
                                ? FontWeight.w600
                                : FontWeight.normal,
                          ),
                        );
                      }).toList(),
                ),

                const SizedBox(height: AppSpacing.xxl),
              ],
            ),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppPalette.of(context).surface,
          boxShadow: const [
            BoxShadow(
              color: AppColors.blackOverlayLight,
              blurRadius: 10,
              offset: Offset(0, -4),
            ),
          ],
        ),
        child: SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (selectedStyle == null) ...[
                Text(
                  optionsAsync.isLoading
                      ? l.createOptionsLoading
                      : l.createOptionsFailed,
                  style: AppTextStyles.bodySmall,
                ),
                if (!optionsAsync.isLoading)
                  TextButton(
                    style: TextButton.styleFrom(
                      minimumSize: const Size(64, 64),
                    ),
                    onPressed: () => ref.invalidate(generationOptionsProvider),
                    child: Text(l.retry),
                  ),
                const SizedBox(height: AppSpacing.sm),
              ],
              if (_isLoading)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.md),
                  child: Semantics(
                    liveRegion: true,
                    child: Text(l.createRequestPending),
                  ),
                ),
              PrimaryButton(
                text: l.createMakeButton,
                isLoading: _isLoading,
                onPressed: selectedStyle == null ? null : _createBook,
              ),
            ],
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
          color: isSelected
              ? AppPalette.of(context).primaryLight
              : AppPalette.of(context).surface,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: isSelected
                ? AppColors.secondary
                : AppPalette.of(context).divider,
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
                          ? AppPalette.of(context).primary
                          : AppPalette.of(context).textPrimary,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    description,
                    style: AppTextStyles.caption.copyWith(
                      color: AppPalette.of(context).textSecondary,
                    ),
                  ),
                ],
              ),
            ),
            if (isSelected)
              const Icon(
                Icons.check_circle,
                color: AppColors.secondary,
                size: 24,
              ),
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
        color: AppPalette.of(context).primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Row(
        children: [
          const Icon(Icons.auto_stories, size: 18, color: AppColors.secondary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: AppTextStyles.caption.copyWith(
                color: AppPalette.of(context).textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
