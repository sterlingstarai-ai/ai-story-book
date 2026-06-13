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
  String podOrderEstimatedTotal(Object amount) {
    return '예상 $amount원';
  }

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
  String podOrderPaymentAmount(Object amount) {
    return '결제금액: $amount원';
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
}
