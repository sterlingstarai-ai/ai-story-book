// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Korean (`ko`).
class AppLocalizationsKo extends AppLocalizations {
  AppLocalizationsKo([String locale = 'ko']) : super(locale);

  @override
  String get appTitle => 'AI 동화책';

  @override
  String get readingGrowthTitle => '읽기 성장';

  @override
  String get readingGrowthEntryTitle => '읽기 성장 보기';

  @override
  String get readingGrowthEntrySubtitle => '우리 아이의 읽기 실력이 쌓이는 과정';

  @override
  String get estimatedReadingLevel => '우리 아이 추정 읽기레벨';

  @override
  String get booksReadLabel => '읽은 책';

  @override
  String get currentStreakLabel => '연속 읽기';

  @override
  String get vocabLearnedLabel => '학습 어휘';

  @override
  String get quizAccuracyLabel => '퀴즈 정확도';

  @override
  String get retry => '다시 시도';

  @override
  String get onboardingSkip => '건너뛰기';

  @override
  String get onboardingNext => '다음';

  @override
  String get onboardingStart => '시작하기';

  @override
  String get onboardingSlide1Title => 'AI 맞춤 동화';

  @override
  String get onboardingSlide1Subtitle => '아이에게 맞는 이야기를 AI가 만들어줘요.';

  @override
  String get onboardingSlide2Title => '사진으로 캐릭터 만들기';

  @override
  String get onboardingSlide2Subtitle => '아이 사진을 동화 속 주인공으로 변환할 수 있어요.';

  @override
  String get onboardingSlide3Title => '매일 읽기 습관';

  @override
  String get onboardingSlide3Subtitle => '스트릭으로 매일 독서 습관을 만들어요.';

  @override
  String get onboardingSlide4Title => '첫 책 무료 시작';

  @override
  String get onboardingSlide4Subtitle => '초기 3크레딧으로 바로 동화책을 만들어보세요.';

  @override
  String onboardingPageIndicator(int current, int total) {
    return '총 $total장 중 $current장';
  }

  @override
  String get homeTitle => 'AI 동화책';

  @override
  String get homeSettingsTooltip => '설정';

  @override
  String get homeHeaderSubtitle => '아이를 위한 맞춤 동화를 만들어보세요';

  @override
  String get homeSectionTodayReading => '오늘의 읽기';

  @override
  String get homeSectionForParents => '부모님께';

  @override
  String get homeRecentBooksTitle => '최근 만든 책';

  @override
  String get homeViewAll => '전체 보기';

  @override
  String get homeEmptyTitle => '아직 만든 책이 없어요';

  @override
  String get homeEmptySubtitle => '첫 번째 동화책을 만들어보세요!';

  @override
  String get homeLibraryErrorTitle => '책을 불러올 수 없어요';

  @override
  String get homeCreateCardTitle => '새 동화책 만들기';

  @override
  String get homeCreateCardSubtitle => '우리 아이가 주인공인\n맞춤 동화를 만들어요';

  @override
  String get homeQuickStartTitle => '내 캐릭터로 바로 만들기';

  @override
  String get homePhotoCharacterTitle => '내 아이로 동화 만들기';

  @override
  String get homePhotoCharacterSubtitle => '사진 속 모습을 닮은 주인공으로 — 사진은 안전하게 처리돼요';

  @override
  String homeStreakDaysLabel(Object days) {
    return '$days일 연속 읽기';
  }

  @override
  String get homeReadTodayBadge => '오늘 읽음';

  @override
  String get homeNotReadTodayBadge => '오늘 미완료';

  @override
  String homeStreakSummary(Object total, Object longest) {
    return '총 $total일 읽었어요 · 최고 $longest일';
  }

  @override
  String get homeRecent7Days => '최근 7일';

  @override
  String homeTodayStoryLabel(Object theme) {
    return '오늘의 동화 · $theme';
  }

  @override
  String get homeContinueReading => '이어 읽기';

  @override
  String get homeMakeTodayStory => '오늘 동화 만들기';

  @override
  String get homeStreakLoading => '스트릭 정보를 불러오는 중...';

  @override
  String get homeStreakErrorTitle => '스트릭 카드 오류';

  @override
  String get homeStreakLoadError => '스트릭 정보를 불러오지 못했어요.';

  @override
  String get homeGrowthEntryTitle => '읽기 성장 보기';

  @override
  String homeGrowthSubtitleStats(Object vocab, Object accuracy) {
    return '학습 어휘 $vocab개 · 정확도 $accuracy%';
  }

  @override
  String get homeWeekdayMon => '월';

  @override
  String get homeWeekdayTue => '화';

  @override
  String get homeWeekdayWed => '수';

  @override
  String get homeWeekdayThu => '목';

  @override
  String get homeWeekdayFri => '금';

  @override
  String get homeWeekdaySat => '토';

  @override
  String get homeWeekdaySun => '일';

  @override
  String get homeWeekdayUnknown => '-';

  @override
  String get createTitle => '새 동화책 만들기';

  @override
  String get createCloseTooltip => '닫기';

  @override
  String get createTopicLabel => '어떤 이야기를 만들까요?';

  @override
  String get createTopicHint => '예: 토끼가 하늘을 나는 이야기';

  @override
  String get createTopicRequired => '이야기 주제를 입력해주세요';

  @override
  String get createTopicTooShort => '조금 더 자세히 입력해주세요';

  @override
  String get createChildNameLabel => '우리 아이 이름 (선택)';

  @override
  String get createChildNameHint => '예: 민지';

  @override
  String get createAgeLabel => '아이 연령대';

  @override
  String get createAgeHelp3to5 => '쉬운 단어, 1~2개의 짧은 문장, 반복과 의성어';

  @override
  String get createAgeHelp5to7 => '익숙한 단어, 2~3문장, 감정과 간단한 대화';

  @override
  String get createAgeHelp7to9 => '풍부한 단어, 2~4문장, 원인과 결과';

  @override
  String get createAgeHelpAdult => '길이 제한 없음, 밀도 있는 서사';

  @override
  String get createLanguageLabel => '이야기 언어';

  @override
  String get createTemplateSectionLabel => '추천으로 시작하기';

  @override
  String get createTemplateAnimalLabel => '동물 친구';

  @override
  String get createTemplateAnimalTopic => '용감한 아기 동물이 숲에서 새 친구를 사귀는 이야기';

  @override
  String get createTemplateFriendshipLabel => '우정';

  @override
  String get createTemplateFriendshipTopic => '친구를 도와주며 함께 문제를 해결하는 이야기';

  @override
  String get createTemplateFeelingsLabel => '마음 다독이기';

  @override
  String get createTemplateFeelingsTopic => '무서운 밤, 용기를 내어 두려움을 이겨내는 이야기';

  @override
  String get createTemplateSpaceLabel => '우주 모험';

  @override
  String get createTemplateSpaceTopic => '별과 행성을 탐험하며 멋진 것을 발견하는 이야기';

  @override
  String get createStyleLabel => '그림 스타일';

  @override
  String get createThemeLabel => '테마 (선택)';

  @override
  String get createThemeNone => '없음';

  @override
  String get createCharacterLabel => '주인공 캐릭터';

  @override
  String get createAddCharacter => '캐릭터 추가';

  @override
  String get createCharacterHint => '기존 캐릭터를 선택하거나, AI가 새 캐릭터를 만들어요';

  @override
  String get createAiCharacterTitle => 'AI가 새 캐릭터 생성';

  @override
  String get createAiCharacterDesc => '이야기에 맞는 캐릭터를 자동으로 만들어요';

  @override
  String get createChildProtagonistTitle => '우리 아이를 주인공으로';

  @override
  String get createChildProtagonistDesc => '사진 또는 기본 캐릭터로 주인공을 만들어요';

  @override
  String get createOrSelectExisting => '또는 기존 캐릭터 선택';

  @override
  String createSelectedCount(Object count) {
    return '$count명 선택됨 (가족/친구 이야기 가능)';
  }

  @override
  String get createAddCharacterTip => '캐릭터를 추가하면 같은 캐릭터로 시리즈를 만들 수 있어요!';

  @override
  String get createCharacterLoadError => '캐릭터를 불러올 수 없어요';

  @override
  String get createRelationshipLabel => '관계 (선택)';

  @override
  String get createRelationshipFriends => '친구';

  @override
  String get createRelationshipSiblings => '남매';

  @override
  String get createRelationshipFamily => '가족';

  @override
  String get createForbiddenLabel => '빼고 싶은 요소 (선택)';

  @override
  String get createForbiddenViolence => '폭력';

  @override
  String get createForbiddenScary => '무서운 내용';

  @override
  String get createForbiddenSad => '슬픈 결말';

  @override
  String get createForbiddenRude => '거친 말';

  @override
  String get createMakeButton => '동화책 만들기';

  @override
  String get createPlanUpgradeTitle => '플랜 업그레이드가 필요해요';

  @override
  String get createCreditShortageTitle => '크레딧이 부족해요';

  @override
  String get createFailedSnack => '책 생성에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get libraryTitle => '내 서재';

  @override
  String get librarySeriesBadge => '시리즈';

  @override
  String get librarySeriesAddVolume => '다음 권 만들기';

  @override
  String get libraryRefresh => '새로고침';

  @override
  String get librarySortNewest => '최신순';

  @override
  String get librarySortOldest => '오래된순';

  @override
  String get librarySortTitle => '제목순';

  @override
  String get libraryStyleWatercolor => '수채화';

  @override
  String get libraryStyleCartoon => '카툰';

  @override
  String get libraryStyle3d => '3D';

  @override
  String get libraryStylePixel => '픽셀';

  @override
  String get libraryStyleOilPainting => '유화';

  @override
  String get libraryStyleClaymation => '클레이';

  @override
  String get libraryStyleRealistic => '실사';

  @override
  String get libraryAge3to5 => '3-5세';

  @override
  String get libraryAge5to7 => '5-7세';

  @override
  String get libraryAge7to9 => '7-9세';

  @override
  String get libraryAgeAdult => '성인';

  @override
  String get libraryRenameDialogTitle => '책 이름 바꾸기';

  @override
  String get libraryRenameFieldLabel => '제목';

  @override
  String get libraryRenameFieldHint => '책 제목을 입력해주세요';

  @override
  String get libraryCancel => '취소';

  @override
  String get librarySave => '저장';

  @override
  String get libraryRenameSuccess => '책 이름을 수정했어요.';

  @override
  String get libraryDeleteDialogTitle => '책 삭제';

  @override
  String libraryDeleteDialogContent(Object title) {
    return '\"$title\"을(를) 삭제할까요?\n삭제한 책은 복구할 수 없어요.';
  }

  @override
  String get libraryDelete => '삭제';

  @override
  String get libraryDeleteSuccess => '책을 삭제했어요.';

  @override
  String get libraryErrorNetwork => '인터넷 연결을 확인한 뒤 다시 시도해주세요.';

  @override
  String get libraryErrorGeneric => '요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.';

  @override
  String libraryShareMessage(Object title) {
    return '📚 $title\n\nAI Story Book으로 만든 동화책이에요.\n아이에게 특별한 이야기를 들려주세요!';
  }

  @override
  String get libraryShareFailed => '공유에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get librarySortLabel => '정렬';

  @override
  String get libraryStyleLabel => '스타일';

  @override
  String get libraryAgeLabel => '연령';

  @override
  String get libraryFilterAll => '전체';

  @override
  String get libraryResetFilters => '필터 초기화';

  @override
  String get libraryEmptyFilterTitle => '조건에 맞는 책이 없어요';

  @override
  String get libraryEmptyTitle => '아직 만든 책이 없어요';

  @override
  String get libraryEmptyFilterSubtitle => '필터를 해제하고 전체 서재를 확인해보세요.';

  @override
  String get libraryEmptySubtitle => '첫 번째 동화책을 만들어보세요!';

  @override
  String get libraryCreateNew => '새 책 만들기';

  @override
  String get libraryLoadError => '서재를 불러올 수 없어요';

  @override
  String get libraryRetry => '다시 시도';

  @override
  String get libraryDateToday => '오늘';

  @override
  String get libraryDateYesterday => '어제';

  @override
  String libraryDateDaysAgo(Object days) {
    return '$days일 전';
  }

  @override
  String libraryDateMonthDay(Object month, Object day) {
    return '$month월 $day일';
  }

  @override
  String get libraryClose => '닫기';

  @override
  String get libraryOfflineBanner => '오프라인 상태예요. 최근 불러온 책을 보여주고 있어요.';

  @override
  String get libraryBookOptions => '책 옵션';

  @override
  String get libraryMenuRename => '이름 바꾸기';

  @override
  String get libraryMenuShare => '공유하기';

  @override
  String get libraryMenuDelete => '삭제';

  @override
  String get loadingTitle => '동화책을 만들고 있어요';

  @override
  String get loadingCompleted => '완성되었어요!';

  @override
  String get loadingErrorTitle => '문제가 발생했어요';

  @override
  String get loadingUnknownError => '알 수 없는 오류';

  @override
  String get loadingSafetyBlockedPrefix => '입력이 안전하지 않습니다:';

  @override
  String get loadingRetryButton => '다시 시도';

  @override
  String get loadingCheckStatusButton => '상태 다시 확인';

  @override
  String get loadingBackToHomeButton => '홈으로 돌아가기';

  @override
  String get loadingStepWaiting => '대기 중...';

  @override
  String get loadingStepPreparing => '준비 중...';

  @override
  String get loadingStepNormalize => '입력을 분석하고 있어요';

  @override
  String get loadingStepModerateInput => '안전성을 검사하고 있어요';

  @override
  String get loadingStepGenerateStory => '이야기를 만들고 있어요';

  @override
  String get loadingStepGenerateCharacterSheet => '캐릭터를 디자인하고 있어요';

  @override
  String get loadingStepGenerateImagePrompts => '그림을 준비하고 있어요';

  @override
  String get loadingStepGenerateImages => '그림을 그리고 있어요';

  @override
  String get loadingStepModerateOutput => '최종 검사 중이에요';

  @override
  String get loadingStepPackage => '마무리하고 있어요';

  @override
  String get loadingTip1 => '아이에게 맞는 단어와 문장으로 이야기가 만들어져요';

  @override
  String get loadingTip2 => '캐릭터가 일관되게 그려지도록 AI가 신경 쓰고 있어요';

  @override
  String get loadingTip3 => '완성된 책은 서재에서 언제든지 다시 볼 수 있어요';

  @override
  String get loadingTip4 => '마음에 들지 않는 페이지는 나중에 다시 생성할 수 있어요';

  @override
  String get loadingTip5 => '같은 캐릭터로 시리즈 동화를 만들 수도 있어요';

  @override
  String get profilesTitle => '아이 프로필';

  @override
  String get profilesAddTooltip => '프로필 추가';

  @override
  String get profilesLoadError => '프로필 정보를 불러오지 못했어요.';

  @override
  String get profilesDialogAddTitle => '프로필 추가';

  @override
  String get profilesDialogEditTitle => '프로필 수정';

  @override
  String get profilesNameLabel => '이름';

  @override
  String get profilesNameHint => '예: 민지';

  @override
  String get profilesNameRequired => '이름을 입력해주세요.';

  @override
  String get profilesBirthYearLabel => '출생연도(선택)';

  @override
  String get profilesBirthMonthLabel => '월';

  @override
  String profilesYearOption(Object year) {
    return '$year년';
  }

  @override
  String profilesMonthOption(Object month) {
    return '$month월';
  }

  @override
  String profilesAgeBandAuto(Object band) {
    return '연령대 자동: $band세';
  }

  @override
  String get profilesBirthHint => '출생연월을 입력하면 연령대가 자동 설정돼요(선택).';

  @override
  String get profilesAgeBandLabel => '연령대';

  @override
  String get profilesAgeBand35 => '3-5세';

  @override
  String get profilesAgeBand57 => '5-7세';

  @override
  String get profilesAgeBand79 => '7-9세';

  @override
  String get profilesAgeBandAdult => '성인';

  @override
  String profilesAgeBandValue(Object label) {
    return '연령대: $label';
  }

  @override
  String get profilesSetAsDefaultSwitch => '기본 프로필로 설정';

  @override
  String get profilesCancel => '취소';

  @override
  String get profilesAddAction => '추가';

  @override
  String get profilesSaveAction => '저장';

  @override
  String get profilesCreateFailed => '프로필 생성에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get profilesEditFailed => '프로필 수정에 실패했어요.';

  @override
  String get profilesSetDefaultFailed => '기본 프로필 설정에 실패했어요.';

  @override
  String get profilesDeleteTitle => '프로필 삭제';

  @override
  String get profilesDeleteConfirm => '이 프로필을 삭제할까요?';

  @override
  String get profilesDeleteAction => '삭제';

  @override
  String get profilesDeleteFailed => '프로필 삭제에 실패했어요.';

  @override
  String get profilesEmpty => '등록된 프로필이 없어요';

  @override
  String get profilesCreateFirst => '첫 프로필 만들기';

  @override
  String get profilesDefaultBadge => '기본';

  @override
  String get profilesActiveBadge => '현재';

  @override
  String get profilesMenuActivate => '현재 프로필로 사용';

  @override
  String get profilesMenuSetDefault => '기본 프로필로 설정';

  @override
  String get profilesMenuEdit => '수정';

  @override
  String get voiceProfilesTitle => '가족 목소리';

  @override
  String get voiceProfilesAddTooltip => '음성 프로필 추가';

  @override
  String get voiceProfilesMenuTooltip => '메뉴 열기';

  @override
  String get voiceProfilesLoadError => '가족 목소리 정보를 불러오지 못했어요.';

  @override
  String get voiceProfilesAddTitle => '음성 프로필 추가';

  @override
  String get voiceProfilesEditTitle => '음성 프로필 수정';

  @override
  String get voiceProfilesLabelFieldLabel => '이름/라벨';

  @override
  String get voiceProfilesLabelFieldHint => '예: 엄마 목소리';

  @override
  String get voiceProfilesLabelRequired => '라벨을 입력해주세요.';

  @override
  String get voiceProfilesRelationshipFieldLabel => '관계';

  @override
  String get voiceProfilesRelationshipFieldHint => '예: mother, grandmother';

  @override
  String get voiceProfilesSampleUrlFieldLabel => '샘플 오디오 URL';

  @override
  String get voiceProfilesSampleUrlRequired => '샘플 오디오 URL을 입력해주세요.';

  @override
  String get voiceProfilesSampleUrlInvalid => '유효한 URL을 입력해주세요.';

  @override
  String get voiceProfilesSampleUploadSuccess => '음성 샘플 업로드가 완료되었어요.';

  @override
  String get voiceProfilesSampleUploadError => '샘플 업로드에 실패했어요. 다시 시도해주세요.';

  @override
  String get voiceProfilesUploading => '업로드 중...';

  @override
  String get voiceProfilesUploadAudioButton => '오디오 파일 업로드';

  @override
  String get voiceProfilesConsentToggle => '보호자 동의 완료';

  @override
  String get voiceProfilesActiveToggle => '활성 상태';

  @override
  String get voiceProfilesCancel => '취소';

  @override
  String get voiceProfilesAdd => '추가';

  @override
  String get voiceProfilesSave => '저장';

  @override
  String get voiceProfilesCreateError => '음성 프로필 생성에 실패했어요.';

  @override
  String get voiceProfilesEditError => '음성 프로필 수정에 실패했어요.';

  @override
  String get voiceProfilesRevokeError => '동의 철회 처리에 실패했어요.';

  @override
  String get voiceProfilesDeleteTitle => '음성 프로필 삭제';

  @override
  String get voiceProfilesDeleteConfirm => '이 음성 프로필을 삭제할까요?';

  @override
  String get voiceProfilesDelete => '삭제';

  @override
  String get voiceProfilesDeleteError => '음성 프로필 삭제에 실패했어요.';

  @override
  String get voiceProfilesEmpty => '등록된 가족 목소리가 없어요.\n우측 상단 + 버튼으로 추가해보세요.';

  @override
  String get voiceProfilesUnnamed => '이름 없음';

  @override
  String get voiceProfilesMenuEdit => '수정';

  @override
  String get voiceProfilesMenuRevoke => '동의 철회';

  @override
  String get voiceProfilesMenuDelete => '삭제';

  @override
  String voiceProfilesRelationshipPrefix(Object relationship) {
    return '관계: $relationship';
  }

  @override
  String get voiceProfilesConsentDone => '동의 완료';

  @override
  String get voiceProfilesConsentNeeded => '동의 필요';

  @override
  String get voiceProfilesActive => '활성';

  @override
  String get voiceProfilesInactive => '비활성';

  @override
  String get podOrderTitle => '실물책 주문';

  @override
  String get podOrderBookLabel => '주문 도서';

  @override
  String get podOrderRecipientNameLabel => '수령인 이름';

  @override
  String get podOrderRecipientNameError => '수령인 이름을 입력해주세요.';

  @override
  String get podOrderAddressLabel => '주소';

  @override
  String get podOrderAddressError => '주소를 입력해주세요.';

  @override
  String get podOrderPostalLabel => '우편번호';

  @override
  String get podOrderPostalError => '우편번호를 입력해주세요.';

  @override
  String get podOrderCountryLabel => '국가코드';

  @override
  String get podOrderCountryError => '국가코드를 입력해주세요.';

  @override
  String get podOrderPhoneLabel => '연락처';

  @override
  String get podOrderPhoneError => '연락처를 입력해주세요.';

  @override
  String get podOrderQuantityLabel => '수량';

  @override
  String podOrderQuantityValue(Object count) {
    return '$count권';
  }

  @override
  String podOrderEstimatedTotal(Object amount, Object currency) {
    return '예상 $amount $currency';
  }

  @override
  String get podOrderCityLabel => '도시';

  @override
  String get podOrderCityError => '도시를 입력해주세요.';

  @override
  String get podOrderStateLabel => '주/State';

  @override
  String get podOrderStateError => 'US/CA는 주/State를 입력해주세요.';

  @override
  String get podOrderAddressLine2Label => '상세주소(선택)';

  @override
  String get podOrderSubmitting => '주문 처리 중...';

  @override
  String get podOrderSubmitButton => '주문하기';

  @override
  String get podOrderSubmitSuccess => '주문이 접수되었습니다.';

  @override
  String get podOrderSubmitError => '주문 접수에 실패했어요. 정보를 확인해주세요.';

  @override
  String get podOrderStatusError => '주문 상태 조회에 실패했어요.';

  @override
  String get podOrderStatusTitle => '주문 상태';

  @override
  String podOrderOrderNumber(Object orderId) {
    return '주문번호: $orderId';
  }

  @override
  String podOrderProviderOrderNumber(Object providerOrderId) {
    return '공급사 주문번호: $providerOrderId';
  }

  @override
  String get podOrderCopyTooltip => '복사';

  @override
  String get podOrderProviderOrderCopied => '공급사 주문번호를 복사했어요.';

  @override
  String podOrderStatusValue(Object status) {
    return '상태: $status';
  }

  @override
  String podOrderPaymentAmount(Object amount, Object currency) {
    return '결제금액: $amount $currency';
  }

  @override
  String podOrderSyncValue(Object source) {
    return '동기화: $source';
  }

  @override
  String podOrderTrackingNumber(Object trackingNumber) {
    return '운송장: $trackingNumber';
  }

  @override
  String get podOrderRefreshStatus => '상태 새로고침';

  @override
  String get podOrderDecreaseQuantityTooltip => '수량 줄이기';

  @override
  String get podOrderIncreaseQuantityTooltip => '수량 늘리기';

  @override
  String get branchStoryTitle => '분기형 스토리';

  @override
  String get branchStoryRefreshTooltip => '새로고침';

  @override
  String get branchStoryLoadError => '분기형 스토리 정보를 불러오지 못했어요.';

  @override
  String get branchStoryResumeStatus => '이전 진행 지점에서 이어서 읽고 있어요.';

  @override
  String get branchStoryEndingReached => '이 분기의 엔딩에 도착했어요.';

  @override
  String get branchStoryChoiceApplied => '선택을 적용했어요.';

  @override
  String branchStoryEndingArrived(Object selected) {
    return '엔딩 도착: $selected';
  }

  @override
  String branchStorySelected(Object selected) {
    return '선택: $selected';
  }

  @override
  String get branchStoryChoiceFailed => '선택 적용에 실패했어요. 다시 시도해주세요.';

  @override
  String get branchStorySampleText1 => '토끼는 갈림길에 섰어요.';

  @override
  String get branchStorySampleText2 => '왼쪽 길에서 새로운 친구를 만났어요.';

  @override
  String get branchStorySampleText3 => '오른쪽 길에서 보물을 발견했어요.';

  @override
  String get branchStorySampleOptionLeft => '왼쪽 길로 간다';

  @override
  String get branchStorySampleOptionRight => '오른쪽 길로 간다';

  @override
  String get branchStorySampleCreated => '샘플 분기 스토리를 생성했어요.';

  @override
  String get branchStorySampleCreateFailed => '샘플 분기 생성에 실패했어요.';

  @override
  String branchStoryNodeLabel(Object nodeKey) {
    return '노드: $nodeKey';
  }

  @override
  String branchStoryPageLabel(Object pageNumber) {
    return '페이지 $pageNumber';
  }

  @override
  String get branchStoryImageSemantics => '분기형 스토리 삽화';

  @override
  String get branchStoryOptionsHeading => '선택지';

  @override
  String get branchStoryNoOptions => '더 이상 선택지가 없어요. 이 분기의 엔딩입니다.';

  @override
  String get branchStoryPreviousChoice => '이전 선택';

  @override
  String get branchStoryRestart => '처음부터';

  @override
  String get branchStoryRetry => '다시 시도';

  @override
  String get branchStoryEmptyTitle => '아직 분기형 스토리가 없어요.';

  @override
  String get branchStoryEmptySubtitle => '샘플 분기를 생성해서 인터랙티브 스토리를 바로 체험할 수 있어요.';

  @override
  String get branchStorySampleCreating => '생성 중...';

  @override
  String get branchStoryCreateSample => '샘플 분기 생성';

  @override
  String get pronunciationTitle => '발음 연습';

  @override
  String pronunciationIntro(Object pageNumber) {
    return '책 페이지 $pageNumber 문장을 기준으로 발음을 평가합니다.';
  }

  @override
  String get pronunciationExpectedLabel => '기준 문장';

  @override
  String get pronunciationTranscriptLabel => '읽은 문장(텍스트 입력)';

  @override
  String get pronunciationTranscriptHint => '아이가 읽은 문장을 입력해주세요.';

  @override
  String get pronunciationEvaluating => '평가 중...';

  @override
  String get pronunciationEvaluateButton => '발음 평가하기';

  @override
  String get pronunciationEvaluateAudioButton => '오디오 파일로 평가';

  @override
  String pronunciationScore(Object score) {
    return '발음 점수: $score점';
  }

  @override
  String get pronunciationNoFeedback => '피드백이 없습니다.';

  @override
  String get pronunciationErrorBothRequired => '기준 문장과 읽은 문장을 모두 입력해주세요.';

  @override
  String get pronunciationErrorEvaluateFailed =>
      '발음 평가에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get pronunciationErrorExpectedRequired => '기준 문장을 먼저 입력해주세요.';

  @override
  String get pronunciationErrorAudioEvaluateFailed =>
      '오디오 발음 평가에 실패했어요. 다시 시도해주세요.';

  @override
  String get parentDashboardLoadError => '대시보드 데이터를 불러오지 못했어요.';

  @override
  String get parentDashboardReportMonthly => '월간 리포트';

  @override
  String get parentDashboardReportWeekly => '주간 리포트';

  @override
  String get parentDashboardTitle => '부모 대시보드';

  @override
  String get parentDashboardRefreshTooltip => '새로고침';

  @override
  String get parentDashboardSegmentWeekly => '주간';

  @override
  String get parentDashboardSegmentMonthly => '월간';

  @override
  String get parentDashboardThemeUnspecified => '미지정';

  @override
  String get parentDashboardMetricTotalBooksTitle => '총 읽은 책';

  @override
  String parentDashboardMetricTotalBooksValue(Object count) {
    return '$count권';
  }

  @override
  String get parentDashboardMetricTotalMinutesTitle => '총 읽기 시간';

  @override
  String parentDashboardMetricTotalMinutesValue(Object minutes) {
    return '$minutes분';
  }

  @override
  String get parentDashboardMetricAvgMinutesTitle => '평균 읽기 시간';

  @override
  String parentDashboardMetricAvgMinutesValue(Object minutes) {
    return '$minutes분';
  }

  @override
  String get parentDashboardMetricPreferredThemeTitle => '선호 테마';

  @override
  String get parentDashboardLearningTitle => '학습 현황';

  @override
  String parentDashboardLearningStreakLine(Object current, Object longest) {
    return '현재 스트릭 $current일 · 최고 $longest일';
  }

  @override
  String parentDashboardLearningSessionLine(Object completed, Object total) {
    return '완독 세션 $completed / 전체 세션 $total';
  }

  @override
  String parentDashboardLearningCompletionLine(Object rate) {
    return '완료율 $rate%';
  }

  @override
  String get parentDashboardDailyChartTitle => '일별 읽기 시간';

  @override
  String get settingsLoadError => '설정을 불러오지 못했어요.';

  @override
  String get settingsSaved => '설정이 저장되었습니다.';

  @override
  String get settingsSaveError => '설정 저장에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get settingsBedtimeNotificationTitle => '오늘의 동화 읽을 시간이에요';

  @override
  String get settingsBedtimeNotificationBody => '잠들기 전 오늘의 동화를 함께 읽어요';

  @override
  String get settingsRevokeConsentTitle => '동의 철회';

  @override
  String get settingsRevokeConsentContent =>
      '동의를 철회하면 앱 이용이 제한되며, 데이터 삭제를 진행할 수 있습니다.';

  @override
  String get settingsCancel => '취소';

  @override
  String get settingsRevoke => '철회';

  @override
  String get settingsRevokeConsentError => '철회 처리에 실패했어요. 네트워크 확인 후 다시 시도해주세요.';

  @override
  String get settingsConsentRevoked => '동의가 철회되었습니다.';

  @override
  String get settingsDeleteAllTitle => '내 데이터 모두 삭제';

  @override
  String get settingsDeleteAllContent => '이 작업은 되돌릴 수 없습니다. 계속할까요?';

  @override
  String get settingsContinue => '계속';

  @override
  String get settingsFinalConfirmTitle => '최종 확인';

  @override
  String settingsFinalConfirmPrompt(Object keyword) {
    return '삭제를 진행하려면 아래에 \"$keyword\"를 입력하세요.';
  }

  @override
  String get settingsDeleteKeyword => '삭제';

  @override
  String get settingsDeleteKeywordMismatch => '확인 텍스트가 일치하지 않습니다.';

  @override
  String get settingsDeleteError => '데이터 삭제에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get settingsLinkCopied => '링크를 복사했어요.';

  @override
  String get settingsTitle => '설정';

  @override
  String get settingsSave => '저장';

  @override
  String get settingsSectionAccount => '계정';

  @override
  String get settingsChildProfile => '아이 프로필';

  @override
  String get settingsParentDashboard => '부모 대시보드';

  @override
  String get settingsParentDashboardSubtitle => '주간/월간 읽기 리포트';

  @override
  String get settingsFamilyVoice => '가족 목소리';

  @override
  String get settingsFamilyVoiceSubtitle => '녹음 샘플과 동의 상태 관리';

  @override
  String get settingsCreditsSubscription => '크레딧/구독';

  @override
  String get settingsPoliciesTitle => '정책 안내';

  @override
  String get settingsPoliciesSubtitle => '크레딧 이월·해지 후 보관·인쇄 환불';

  @override
  String get policyCreditRolloverTitle => '크레딧 이월';

  @override
  String get policyCreditRolloverBody =>
      '사용하지 않은 크레딧은 구독이 유지되는 동안 다음 달로 이월됩니다.';

  @override
  String get policyBookAccessTitle => '해지 후 책 보관';

  @override
  String get policyBookAccessBody => '구독을 해지해도 이미 만든 책은 계속 열람하고 내려받을 수 있습니다.';

  @override
  String get policyRefundTitle => '인쇄 환불·재인쇄';

  @override
  String get policyRefundBody => '인쇄본이 불량이거나 배송 중 손상된 경우 무료로 재인쇄하거나 환불해 드립니다.';

  @override
  String get settingsSectionApp => '앱 설정';

  @override
  String get settingsLanguage => '언어';

  @override
  String get settingsLanguageKorean => '한국어';

  @override
  String get settingsLanguageEnglish => 'English';

  @override
  String get settingsDarkMode => '다크 모드';

  @override
  String get settingsDarkModeSubtitle => '앱 전체 테마를 어둡게 변경합니다.';

  @override
  String get settingsKakaoShare => '카카오톡 카드 공유';

  @override
  String get settingsKakaoShareSubtitle => '공유 메뉴에서 카카오톡 공유를 표시합니다.';

  @override
  String get settingsSectionSleep => '수면 모드';

  @override
  String get settingsBedtimeNotification => '취침 알림';

  @override
  String get settingsBedtime => '취침 시간';

  @override
  String settingsSleepTimer(Object minutes) {
    return '기본 수면 타이머: $minutes분';
  }

  @override
  String settingsMinutes(Object minutes) {
    return '$minutes분';
  }

  @override
  String get settingsSectionScreenTime => '화면 시간 제한';

  @override
  String get settingsScreenTimeEnabled => '화면 시간 제한 사용';

  @override
  String settingsDailyLimit(Object minutes) {
    return '일일 제한: $minutes분';
  }

  @override
  String get settingsSectionAppInfo => '앱 정보';

  @override
  String get settingsAppVersion => '앱 버전';

  @override
  String get settingsPrivacyPolicy => '개인정보처리방침';

  @override
  String get settingsTermsOfService => '이용약관';

  @override
  String get settingsSectionPrivacy => '개인정보';

  @override
  String get settingsRevokeParentalConsent => '부모 동의 철회';

  @override
  String get settingsDeleteAllData => '내 데이터 모두 삭제';

  @override
  String get settingsDeleteAllDataSubtitle => '책, 캐릭터, 읽기 기록 등 모든 데이터가 삭제됩니다.';

  @override
  String get creditsTitle => '크레딧';

  @override
  String get creditsRestorePurchases => '구매 복원';

  @override
  String get creditsLoadError => '크레딧 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get creditsMyCredits => '내 크레딧';

  @override
  String creditsTotalCreated(Object count) {
    return '총 $count권 생성';
  }

  @override
  String get creditsUnit => '크레딧';

  @override
  String get creditsBuyCredits => '크레딧 구매';

  @override
  String get creditsBadgeCancelScheduled => '해지 예정';

  @override
  String get creditsBadgeActive => '활성';

  @override
  String get creditsSubscriptionInfo => '구독 정보';

  @override
  String get creditsNoActivePlan => '현재 구독 중인 플랜이 없습니다.';

  @override
  String get creditsStartSubscription => '구독 시작하기';

  @override
  String creditsPlanSubscriptionLabel(Object planName) {
    return '$planName 구독';
  }

  @override
  String get creditsDefaultPlanName => '기본';

  @override
  String get creditsMonthlyCredits => '월간 크레딧';

  @override
  String creditsCreditCount(Object count) {
    return '$count개';
  }

  @override
  String get creditsNextRenewal => '다음 갱신일';

  @override
  String get creditsCancelNotice => '현재 결제 주기가 끝나면 무료 플랜으로 전환됩니다.';

  @override
  String get creditsCancelSubscription => '구독 취소';

  @override
  String get creditsPlansTitle => '구독 플랜';

  @override
  String get creditsNoAvailablePlans => '현재 이용 가능한 구독 플랜이 없습니다.';

  @override
  String get creditsPlanFallbackName => '플랜';

  @override
  String get creditsCurrentPlan => '현재 플랜';

  @override
  String get creditsFree => '무료';

  @override
  String creditsPricePerMonth(Object price) {
    return '₩$price/월';
  }

  @override
  String creditsMonthlyCreatable(Object count) {
    return '월 $count권 생성 가능';
  }

  @override
  String get creditsSubscribe => '구독하기';

  @override
  String get creditsPackTitle => '크레딧 팩';

  @override
  String creditsPackName(Object count) {
    return '$count 크레딧 팩';
  }

  @override
  String get creditsPackSubtitle => '필요할 때 즉시 충전';

  @override
  String get creditsBuy => '구매';

  @override
  String get creditsTransactionsTitle => '거래 내역';

  @override
  String get creditsTransactionFallback => '거래';

  @override
  String get creditsRestoring => '구매 내역을 복원하고 있어요...';

  @override
  String get creditsRestoreFailed => '복원에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get creditsPaymentCancelledOrFailed => '결제가 취소되었거나 실패했어요.';

  @override
  String get creditsAlreadyProcessed => '이미 처리된 결제입니다.';

  @override
  String get creditsAlreadySubscribed => '이미 같은 플랜을 이용 중입니다.';

  @override
  String get creditsVerifiedReflected => '결제가 확인되어 크레딧이 반영되었어요.';

  @override
  String get creditsVerifyFailed => '결제 검증에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get creditsStoreUnavailable => '스토어 결제를 사용할 수 없어요.';

  @override
  String get creditsProceedStorePayment => '스토어 결제를 진행해주세요.';

  @override
  String get creditsCannotStartStorePurchase => '스토어 구매를 시작할 수 없어요.';

  @override
  String get creditsSubscriptionStarted => '구독이 시작되었습니다!';

  @override
  String get creditsSubscribeFailed => '구독에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get creditsCancelConfirmContent =>
      '정말 구독을 취소하시겠어요? 현재 기간이 끝날 때까지는 계속 사용할 수 있어요.';

  @override
  String get creditsNo => '아니오';

  @override
  String get creditsConfirmCancel => '취소하기';

  @override
  String get creditsSubscriptionCancelled => '구독이 취소되었습니다.';

  @override
  String get creditsCancelFailed => '구독 취소에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get charactersTitle => '내 캐릭터';

  @override
  String get charactersAddTooltip => '캐릭터 추가';

  @override
  String get charactersRefreshTooltip => '새로고침';

  @override
  String get charactersEmptyTitle => '아직 캐릭터가 없어요';

  @override
  String get charactersEmptySubtitle => '사진으로 캐릭터를 만들어보세요!';

  @override
  String get charactersEmptyCreateButton => '사진으로 캐릭터 만들기';

  @override
  String get charactersLoadErrorTitle => '캐릭터를 불러올 수 없어요';

  @override
  String get charactersRetry => '다시 시도';

  @override
  String get charactersFabCreating => '생성 중...';

  @override
  String get charactersFabCreate => '사진으로 만들기';

  @override
  String get charactersOptionsTitle => '새 캐릭터 만들기';

  @override
  String get charactersOptionsSubtitle => '캐릭터 생성 방식을 선택하세요';

  @override
  String get charactersOptionTextTitle => '직접 입력하기';

  @override
  String get charactersOptionTextSubtitle => '이름, 나이, 특징만 입력';

  @override
  String get charactersOptionCameraTitle => '카메라로 촬영';

  @override
  String get charactersOptionCameraSubtitle => '사진을 분석해서 캐릭터 생성';

  @override
  String get charactersOptionGalleryTitle => '갤러리에서 선택';

  @override
  String get charactersOptionGallerySubtitle => '기존 사진에서 캐릭터 생성';

  @override
  String get charactersOptionDrawingTitle => '아이 그림에서 변환';

  @override
  String get charactersOptionDrawingSubtitle => '그림 사진을 캐릭터+시트로 변환';

  @override
  String charactersCreatedSnack(Object name) {
    return '$name 캐릭터가 생성되었어요!';
  }

  @override
  String charactersCreatedWithSheetsSnack(Object name, Object count) {
    return '$name 캐릭터와 시트 $count장을 만들었어요!';
  }

  @override
  String get charactersCreateFailed => '캐릭터 생성에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get charactersImagePickFailed => '이미지를 선택할 수 없어요. 다시 시도해주세요.';

  @override
  String get charactersNameDialogTitle => '캐릭터 이름';

  @override
  String get charactersNameDialogHint => '캐릭터 이름을 입력하세요 (선택)';

  @override
  String get charactersCancel => '취소';

  @override
  String get charactersConfirm => '확인';

  @override
  String get charactersDeleteDialogTitle => '캐릭터 삭제';

  @override
  String charactersDeleteDialogContent(Object name) {
    return '\"$name\" 캐릭터를 삭제할까요?';
  }

  @override
  String get charactersDelete => '삭제';

  @override
  String get charactersDeletedSnack => '캐릭터가 삭제되었어요.';

  @override
  String get charactersDeleteFailed => '캐릭터 삭제에 실패했어요. 다시 시도해주세요.';

  @override
  String get charactersDefaultName => '새 캐릭터';

  @override
  String get charactersAddCardLoading => '캐릭터 생성 중...';

  @override
  String get charactersAddCardTitle => '새 캐릭터 추가';

  @override
  String get charactersAddCardSubtitle => '사진으로 나만의 캐릭터를 만들어보세요';

  @override
  String get charactersDetailDescription => '설명';

  @override
  String get charactersDetailPersonality => '성격';

  @override
  String get charactersDetailAppearance => '외형';

  @override
  String get charactersDetailAge => '나이';

  @override
  String get charactersDetailFace => '얼굴';

  @override
  String get charactersDetailHair => '머리';

  @override
  String get charactersDetailSkin => '피부';

  @override
  String get charactersDetailBody => '체형';

  @override
  String get charactersDetailClothing => '의상';

  @override
  String get charactersDetailTop => '상의';

  @override
  String get charactersDetailBottom => '하의';

  @override
  String get charactersDetailShoes => '신발';

  @override
  String get charactersDetailAccessories => '액세서리';

  @override
  String get charactersDetailStyleNotes => '스타일 노트';

  @override
  String get charactersDetailIdentityLock => '🔒 일관성 고정 특징';

  @override
  String get charactersDetailCreateBookButton => '이 캐릭터로 새 책 만들기';

  @override
  String charactersCreatedDate(Object year, Object month, Object day) {
    return '$year년 $month월 $day일 생성';
  }

  @override
  String get charactersRoleChild => '아이';

  @override
  String get charactersRoleBrother => '형/오빠';

  @override
  String get charactersRoleSister => '누나/언니';

  @override
  String get charactersRoleMom => '엄마';

  @override
  String get charactersRoleDad => '아빠';

  @override
  String get charactersRoleGrandma => '할머니';

  @override
  String get charactersRoleGrandpa => '할아버지';

  @override
  String get charactersRoleFriend => '친구';

  @override
  String get charactersRoleTeacher => '선생님';

  @override
  String get charactersRolePet => '반려동물';

  @override
  String get charactersFormTitle => '새 캐릭터 만들기';

  @override
  String get charactersFormRoleLabel => '누구인가요?';

  @override
  String get charactersFormCustomRole => '직접 입력';

  @override
  String get charactersFormCustomRoleHint => '예: 삼촌, 이모, 마법사, 요정...';

  @override
  String get charactersFormNameLabel => '이름';

  @override
  String get charactersFormNameHint => '캐릭터 이름을 입력하세요';

  @override
  String get charactersFormTraitsLabel => '성격/특징';

  @override
  String get charactersFormTraitsHelper => '여러 개 선택 가능';

  @override
  String get charactersFormTraitsExtraHint => '추가 특징 입력 (선택)';

  @override
  String get charactersFormSubmit => '캐릭터 만들기';

  @override
  String get charactersFormRoleRequired => '역할을 입력해주세요';

  @override
  String get charactersFormRoleSelect => '역할을 선택해주세요';

  @override
  String get charactersFormNameRequired => '이름을 입력해주세요';

  @override
  String get charactersFormTraitsRequired => '성격/특징을 선택해주세요';

  @override
  String get viewerBookLoadError => '책을 불러올 수 없어요';

  @override
  String get viewerGoBack => '돌아가기';

  @override
  String viewerSleepRemaining(Object time) {
    return '수면 $time';
  }

  @override
  String get viewerCompletionTitle => '완독 축하해요!';

  @override
  String viewerCompletionStreak(Object streak) {
    return '🔥 $streak일 연속 읽기 달성! 정말 대단해요.';
  }

  @override
  String get viewerCompletionMessage => '마지막 페이지까지 읽었어요. 다음 동화도 시작해볼까요?';

  @override
  String get viewerCreateNextStory => '다음 동화 만들기';

  @override
  String get viewerGoToLibrary => '서재로 가기';

  @override
  String get viewerCover => '표지';

  @override
  String viewerPageIndicator(Object current, Object total) {
    return '$current / $total';
  }

  @override
  String viewerLearningWordCount(Object count) {
    return '단어 $count';
  }

  @override
  String viewerLearningQuizCount(Object count) {
    return '퀴즈 $count';
  }

  @override
  String viewerLearningQuestionCount(Object count) {
    return '질문 $count';
  }

  @override
  String viewerLearningBar(Object parts) {
    return '학습 모드 · $parts';
  }

  @override
  String get viewerCloseTooltip => '닫기';

  @override
  String get viewerMoreOptionsTooltip => '더보기';

  @override
  String get viewerPreviousPageTooltip => '이전 페이지';

  @override
  String get viewerNextPageTooltip => '다음 페이지';

  @override
  String get viewerPlanUpgradeNeeded => '플랜 업그레이드가 필요해요';

  @override
  String get viewerCreditShortage => '크레딧이 부족해요';

  @override
  String get viewerAudioPlayFailed => '오디오 재생에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get viewerSleepModeEnded => '수면 모드 시간이 종료되었어요.';

  @override
  String get viewerFollowReadingOff => '따라 읽기 모드 끄기';

  @override
  String get viewerFollowReadingOn => '따라 읽기 모드 켜기';

  @override
  String get viewerFollowReadingSubtitle => '오디오 진행에 맞춰 문장을 강조해요';

  @override
  String get viewerDualLanguageOff => '이중언어 표시 끄기';

  @override
  String get viewerDualLanguageOn => '이중언어 동시 표시';

  @override
  String get viewerDualLanguageSubtitle => '한국어/영어를 한 화면에서 볼 수 있어요';

  @override
  String get viewerBranchStoryTitle => '분기형 스토리 모드';

  @override
  String get viewerBranchStorySubtitle => '선택지에 따라 결말이 달라지는 모드';

  @override
  String get viewerRetellTitle => '다른 연령으로 다시 쓰기';

  @override
  String get viewerRetellSubtitle => '같은 그림으로 글만 새 연령대에 맞춰요';

  @override
  String get viewerRetellInProgress => '새 연령대로 다시 쓰는 중…';

  @override
  String get viewerRetellFailed => '다시 쓰기에 실패했어요';

  @override
  String get viewerMilestoneRewardEarned => '보너스 크레딧이 지급됐어요!';

  @override
  String get viewerMilestoneConfirm => '좋아요!';

  @override
  String get viewerLearningModeTitle => '학습 모드';

  @override
  String get viewerLearningModeSubtitle => '단어, 질문, 퀴즈';

  @override
  String get viewerParentGuideTitle => '부모 가이드';

  @override
  String get viewerParentGuideSubtitle => '토론 주제, 활동 아이디어';

  @override
  String get viewerPronunciationTitle => '발음 연습';

  @override
  String get viewerPronunciationSubtitle => '현재 페이지 문장으로 발음을 평가해요';

  @override
  String get viewerRegeneratePageTitle => '이 페이지 다시 만들기';

  @override
  String get viewerSameCharacterNewStory => '같은 캐릭터로 새 이야기';

  @override
  String get viewerExportPdf => 'PDF로 내보내기';

  @override
  String get viewerOrderPhysicalBook => '실물책 주문';

  @override
  String get viewerOrderPhysicalBookSubtitle => 'POD 주문으로 인쇄본을 받아볼 수 있어요';

  @override
  String get viewerSleepModeStop => '수면 모드 종료';

  @override
  String get viewerSleepModeStart => '수면 모드 시작';

  @override
  String viewerSleepModeRemaining(Object time) {
    return '남은 시간 $time';
  }

  @override
  String get viewerSleepModeDescription => '화면 어둡게 + 오디오 자동재생 + 페이지 자동넘김';

  @override
  String get viewerPrint => '인쇄하기';

  @override
  String get viewerShare => '공유하기';

  @override
  String get viewerRegenerateDialogTitle => '페이지 다시 만들기';

  @override
  String get viewerRegenerateDialogContent => '어떤 부분을 다시 만들까요?';

  @override
  String get viewerCancel => '취소';

  @override
  String get viewerRegenerateTextOnly => '텍스트만';

  @override
  String get viewerRegenerateImageOnly => '그림만';

  @override
  String get viewerRegenerateRegion => '이 부분만 고치기';

  @override
  String get inpaintTitle => '부분 수정';

  @override
  String get inpaintInstructions => '고칠 부분을 손가락으로 칠한 뒤, 어떻게 바꿀지 적어주세요.';

  @override
  String get inpaintRegionPromptLabel => '어떻게 바꿀까요?';

  @override
  String get inpaintRegionPromptHint => '예: 하늘을 노을빛으로';

  @override
  String get inpaintReset => '지우기';

  @override
  String get inpaintApply => '적용';

  @override
  String get inpaintNeedRegionAndPrompt => '고칠 영역과 설명을 모두 입력해주세요.';

  @override
  String get inpaintFailed => '부분 수정에 실패했어요.';

  @override
  String get viewerRegenerateAll => '모두';

  @override
  String get viewerRegenerateNotSupported => '이 책은 페이지 재생성을 지원하지 않아요';

  @override
  String get viewerRegenerating => '페이지를 다시 만들고 있어요...';

  @override
  String get viewerRegenerateStarted => '페이지 재생성이 시작되었어요. 잠시만 기다려주세요.';

  @override
  String get viewerRegenerateFailed => '재생성에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get viewerPdfGenerating => 'PDF 생성 중...';

  @override
  String viewerPdfSaved(Object fileName) {
    return 'PDF 저장 완료: $fileName';
  }

  @override
  String get viewerPdfDownloadFailed => 'PDF 다운로드에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get viewerShareLink => '공유 링크';

  @override
  String get viewerShareCopyUrl => 'URL 복사';

  @override
  String get viewerShareMessage => '메시지';

  @override
  String get viewerShareKakao => '카카오톡';

  @override
  String get viewerShareCover => '표지 공유';

  @override
  String get viewerSharePdf => 'PDF 공유';

  @override
  String get viewerShareMore => '더보기';

  @override
  String viewerShareTextSimple(Object title) {
    return '$title\n\nAI Story Book으로 만든 동화책이에요!';
  }

  @override
  String get viewerCopyDone => '복사 완료';

  @override
  String viewerShareLinkText(Object title, Object url) {
    return '우리 아이가 주인공인 동화책 \"$title\" 📖\n$url\n\nAistorybook에서 만들었어요';
  }

  @override
  String get viewerShareLinkFailed => '공유 링크 생성에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String viewerShareFullText(Object title) {
    return '📚 $title\n\nAI Story Book으로 만든 동화책이에요!\n아이에게 특별한 이야기를 선물하세요 ✨';
  }

  @override
  String get viewerKakaoDescription => 'AI Story Book으로 만든 동화책';

  @override
  String viewerKakaoShareText(
      Object title, Object deepLink, Object fallbackUrl) {
    return '📚 $title\n\n카카오톡으로 동화책을 공유해요!\n$deepLink\n$fallbackUrl';
  }

  @override
  String viewerKakaoShareSubject(Object title) {
    return 'AI Story Book - $title';
  }

  @override
  String get viewerPrintFailed => '인쇄에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String viewerShareCoverText(Object title) {
    return '$title - 표지 이미지';
  }

  @override
  String get viewerShareCoverFailed => '표지 공유에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String viewerSharePdfText(Object title) {
    return '$title - AI Story Book으로 만든 동화책';
  }

  @override
  String get viewerSharePdfFailed => 'PDF 공유에 실패했어요. 잠시 후 다시 시도해주세요.';

  @override
  String viewerCoverImageSemantics(Object title) {
    return '동화책 표지: $title';
  }

  @override
  String viewerPageImageSemantics(Object page) {
    return '$page페이지 삽화';
  }

  @override
  String get viewerLearn => '학습하기';

  @override
  String get viewerPlayAudioTooltip => '오디오 재생';

  @override
  String get viewerPauseAudioTooltip => '오디오 일시정지';

  @override
  String get viewerLanguageToggleTooltip => '언어 전환';

  @override
  String get viewerLanguageKo => '한';

  @override
  String get viewerLanguageEn => 'EN';

  @override
  String get viewerTabWord => '단어';

  @override
  String get viewerTabQuestion => '질문';

  @override
  String get viewerTabQuiz => '퀴즈';

  @override
  String get viewerNoVocab => '이 페이지에는 단어 학습이 없어요';

  @override
  String get viewerNoComprehension => '이 페이지에는 이해 질문이 없어요';

  @override
  String get viewerNoQuiz => '이 페이지에는 퀴즈가 없어요';

  @override
  String viewerComprehensionQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String viewerComprehensionAnswer(Object answer) {
    return 'A. $answer';
  }

  @override
  String get viewerShowAnswer => '정답 보기';

  @override
  String viewerQuizQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String get viewerCheckAnswer => '정답 확인';

  @override
  String get viewerQuizCorrect => '정답이에요!';

  @override
  String get viewerQuizIncorrect => '다시 생각해봐요';

  @override
  String get viewerGuideSummaryTitle => '이야기 요약';

  @override
  String get viewerGuideDiscussionTitle => '대화 나누기';

  @override
  String get viewerGuideActivitiesTitle => '함께 해보기';

  @override
  String get navShellHome => '홈';

  @override
  String get navShellCreate => '만들기';

  @override
  String get navShellLibrary => '서재';

  @override
  String get navShellCharacters => '캐릭터';

  @override
  String get creditShortageTitle => '크레딧이 부족해요';

  @override
  String get creditShortageMessage => '아래 방법으로 크레딧을 충전하고 동화책 만들기를 이어갈 수 있어요.';

  @override
  String get creditShortageFreeTitle => '무료 크레딧 받기';

  @override
  String get creditShortageFreeSubtitle => '광고 시청 또는 초대로 무료 크레딧';

  @override
  String get creditShortageSubscribeTitle => '구독하기';

  @override
  String get creditShortageSubscribeSubtitle => '월 구독으로 넉넉하게 이용하기';

  @override
  String get creditShortagePurchaseTitle => '크레딧 구매';

  @override
  String get creditShortagePurchaseSubtitle => '필요한 만큼 바로 충전하기';

  @override
  String get creditShortageClose => '닫기';

  @override
  String vocabGameQuestion(Object word) {
    return '\"$word\"의 뜻은?';
  }

  @override
  String get vocabGameCorrectFeedback => '잘했어요! ⭐';

  @override
  String vocabGameIncorrectFeedback(Object meaning) {
    return '다시 한 번 기억해요: $meaning';
  }

  @override
  String vocabGameChoiceLabel(Object choice) {
    return '보기: $choice';
  }

  @override
  String get characterSourceTitle => '우리 아이를 주인공으로';

  @override
  String get characterSourceSubtitle => '사진으로 만들거나 기본 캐릭터를 골라보세요';

  @override
  String get characterSourcePhotoCamera => '사진 촬영';

  @override
  String get characterSourceGallery => '갤러리';

  @override
  String get characterSourcePresetSectionLabel => '사진 없이 시작 · 기본 캐릭터';

  @override
  String get characterSourcePresetLoadError => '기본 캐릭터를 불러오지 못했어요.';

  @override
  String get characterSourceCreateFailed => '주인공을 만들지 못했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get characterSourcePhotoMissingId =>
      '사진으로 주인공을 만들지 못했어요. 잠시 후 다시 시도해주세요.';

  @override
  String get characterSourcePhotoFailed =>
      '사진으로 주인공을 만들지 못했어요. 보호자 동의/권한을 확인해주세요.';

  @override
  String get ageGateTitle => '부모 확인';

  @override
  String get ageGateDescription => '구매 화면 접근 전 부모 확인이 필요해요.';

  @override
  String get ageGateAnswerHint => '정답 입력';

  @override
  String get ageGateCancel => '취소';

  @override
  String get ageGateWrongAnswer => '정답이 아니에요.';

  @override
  String get ageGateConfirm => '확인';

  @override
  String get consentTitle => '부모 동의';

  @override
  String get consentSubtitle => '아동 보호를 위해 아래 항목에 대한 부모 동의가 필요합니다.';

  @override
  String get consentAgreeAll => '약관 전체 동의';

  @override
  String get consentAgreeAllSubtitle => '아래 항목에 모두 동의합니다.';

  @override
  String get consentPrivacyRequired => '개인정보 수집 및 이용에 동의 (필수)';

  @override
  String get consentPhotoOptionalTitle => '사진으로 우리 아이 주인공 만들기 (선택)';

  @override
  String get consentPhotoDisclosure =>
      '아이 사진은 동화 캐릭터 생성에만 쓰입니다. · 받는 곳: AI 콘텐츠 처리 업체(미국 등 국외) · 항목: 아이 얼굴 사진 · 목적: 동화 캐릭터 생성 · 보유·이용기간: 캐릭터 일관성 유지를 위해 서비스 이용 기간 동안 보관, 동의 철회·삭제 요청 시 즉시 파기 · 운영자는 사진을 직접 열람하지 않습니다. · 거부권: 동의하지 않아도 사진 외 기능은 그대로 이용할 수 있어요(선택).';

  @override
  String get photoConsentAgree => '동의';

  @override
  String get photoConsentCancel => '취소';

  @override
  String get photoConsentLoadFailed => '동의 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';

  @override
  String get consentDataProcessingRequired => '데이터 처리 및 저장 정책에 동의 (필수)';

  @override
  String get consentAcceptButton => '동의하고 시작하기';

  @override
  String get consentRejectButton => '동의하지 않음';

  @override
  String get consentRejectDialogTitle => '동의가 필요합니다';

  @override
  String get consentRejectDialogContent => '아동 보호 정책상 부모 동의 없이는 앱을 이용할 수 없습니다.';

  @override
  String get consentRejectDialogOk => '확인';

  @override
  String get consentSaveError => '동의 저장에 실패했어요. 네트워크 확인 후 다시 시도해주세요.';

  @override
  String get themeLunarNewYear => '설날';

  @override
  String get themeChuseok => '추석';

  @override
  String get themeChildrensDay => '어린이날';

  @override
  String get themeChristmas => '크리스마스';

  @override
  String get themeDailyHabits => '생활습관';

  @override
  String get themeEmotionalCoaching => '감정코칭';

  @override
  String get themeFriendship => '우정';

  @override
  String get themeFamily => '가족';

  @override
  String get themeAdventure => '모험';

  @override
  String get themeNature => '자연';

  @override
  String get themeScience => '과학';

  @override
  String get themeTimeTravel => '시간여행';

  @override
  String get themeAnimal => '동물';

  @override
  String get themeDinosaur => '공룡';

  @override
  String get themeOccupation => '직업';

  @override
  String get themeFictionWorld => '작품 속으로';

  @override
  String get viewerShareRevoke => '공유 링크 철회';

  @override
  String get viewerShareRevokeDone => '공유 링크를 철회했어요.';

  @override
  String get viewerShareRevokeFailed => '철회에 실패했어요. 다시 시도해주세요.';

  @override
  String get viewerShareParentRequired => '공유하려면 부모 인증이 필요해요.';

  @override
  String get lockExtendDone => '화면 시간을 10분 연장했어요.';

  @override
  String get lockTitle => '오늘의 화면 시간 제한에 도달했어요';

  @override
  String get lockSubtitle => '부모 확인 후 10분 연장할 수 있어요.';

  @override
  String get lockExtendButton => '부모 인증 후 10분 연장';

  @override
  String lockUsage(int used, int limit) {
    return '오늘 사용 $used분 / 제한 $limit분';
  }

  @override
  String growthShareText(int booksRead, int levelNumber, String levelLabel,
      int scoreValue, int vocabLearned, int currentStreak) {
    return '📚 우리 아이 읽기 성장 보고서\n\n📖 읽은 책: $booksRead권\n⭐ 읽기 레벨: Lv.$levelNumber ($levelLabel)\n📊 종합 점수: $scoreValue/100\n🔤 학습 어휘: $vocabLearned개\n🔥 연속 읽기: $currentStreak일\n\nAI 동화책으로 매일 한 권씩 우리 아이 읽기 성장 📖';
  }

  @override
  String get growthCtaTitle => '성장을 자랑하고, 이어가세요';

  @override
  String get growthCtaSubtitle => '매일 한 권이 우리 아이 읽기 성장을 만들어요.';

  @override
  String get growthShareSemantic => '우리 아이 읽기 성장 공유하기';

  @override
  String get growthShareButton => '성장 공유';

  @override
  String get growthCreateSemantic => '새 동화책 만들기';

  @override
  String get growthCreateButton => '새 책 만들기';

  @override
  String get growthConfidenceHigh => '신뢰도 높음';

  @override
  String get growthConfidenceMedium => '신뢰도 보통';

  @override
  String get growthConfidenceLow => '더 읽을수록 정확해져요';

  @override
  String growthHeroSemantic(
      int levelNumber, String levelLabel, int scoreValue, String confidence) {
    return '추정 읽기 레벨 $levelNumber, $levelLabel. 읽은 책·어휘·정확도·완독 종합 점수 $scoreValue점 만점 100점. 신뢰도 $confidence.';
  }

  @override
  String growthScoreSummary(int scoreValue) {
    return '읽은 책·어휘·정확도·완독을 종합한 추정 점수 $scoreValue/100';
  }

  @override
  String growthBooksValue(int count) {
    return '$count권';
  }

  @override
  String growthDaysValue(int count) {
    return '$count일';
  }

  @override
  String growthLongestStreak(int count) {
    return '최장 $count일';
  }

  @override
  String growthWordsValue(int count) {
    return '$count개';
  }

  @override
  String get growthWeeklyTitle => '우리 아이 성장 (주간)';

  @override
  String growthWeekSingle(int count) {
    return '이번 주 $count권';
  }

  @override
  String growthWeekDeltaUp(int last, int delta) {
    return '이번 주 $last권 · 지난 주보다 $delta권 더 읽었어요 👏';
  }

  @override
  String growthWeekDeltaDown(int last, int delta) {
    return '이번 주 $last권 · 지난 주보다 $delta권 적어요';
  }

  @override
  String growthWeekDeltaSame(int last) {
    return '이번 주 $last권 · 지난 주와 같아요';
  }

  @override
  String get growthWeekThis => '이번';

  @override
  String growthWeekN(int week) {
    return '$week주';
  }

  @override
  String get growthLeagueMaster => '마스터 리그';

  @override
  String get growthLeagueChallenge => '도전 리그';

  @override
  String get growthLeagueGrowth => '성장 리그';

  @override
  String get growthEncourageTop => '또래 중 최상위! 정말 잘하고 있어요 🎉';

  @override
  String get growthEncourageAhead => '또래보다 앞서가고 있어요 👍';

  @override
  String get growthEncourageOnPar => '또래와 비슷하게 잘 읽고 있어요';

  @override
  String get growthEncourageGrow => '매일 읽을수록 쑥쑥 자라요. 오늘도 한 권 어때요? 🌱';

  @override
  String get growthSelfGrowthTitle => '우리 아이 읽기 성장';

  @override
  String growthSelfGrowthSummary(int books, int vocab) {
    return '이번까지 책 $books권 · 학습 어휘 $vocab개';
  }

  @override
  String get growthSelfGrowthNote =>
      '이 나이엔 등수보다 매일 읽는 습관이 가장 중요해요. 또래 비교는 더 큰 친구들에게 보여드려요.';

  @override
  String growthPeerSubtitleBaseline(String ageBand) {
    return '아직 또래 표본이 적어 $ageBand세 기준값과 비교 (참고용)';
  }

  @override
  String growthPeerSubtitle(String ageBand, int peerCount) {
    return '같은 $ageBand세 또래 $peerCount명 기준 · 읽기 종합 점수';
  }

  @override
  String get growthCompareScoreLabel => '읽기 종합 점수';

  @override
  String growthScorePoints(int score) {
    return '$score점';
  }

  @override
  String growthPeerScorePoints(int score) {
    return '또래 $score점';
  }

  @override
  String growthPeerBooksValue(String value) {
    return '또래 $value권';
  }

  @override
  String growthPeerWordsValue(String value) {
    return '또래 $value개';
  }

  @override
  String growthPeerAccuracyPercent(int percent) {
    return '또래 $percent%';
  }

  @override
  String get growthPeerTitle => '또래 비교';

  @override
  String growthTopPercent(int percent) {
    return '상위 $percent%';
  }

  @override
  String get growthDisclaimer =>
      '읽기 점수·레벨은 읽은 책·완독·학습 어휘·퀴즈 정확도를 종합한 추정치예요. 공인 척도는 아니며, 아이가 꾸준히 읽을수록 더 정확해집니다.';

  @override
  String get growthLoadError => '성장 리포트를 불러오지 못했어요.';
}
