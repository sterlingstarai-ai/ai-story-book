// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'AI Story Book';

  @override
  String get readingGrowthTitle => 'Reading Growth';

  @override
  String get readingGrowthEntryTitle => 'View reading growth';

  @override
  String get readingGrowthEntrySubtitle =>
      'Watch your child\'s reading skills grow';

  @override
  String get estimatedReadingLevel => 'Your child\'s estimated reading level';

  @override
  String get booksReadLabel => 'Books read';

  @override
  String get currentStreakLabel => 'Reading streak';

  @override
  String get vocabLearnedLabel => 'Words learned';

  @override
  String get quizAccuracyLabel => 'Quiz accuracy';

  @override
  String get retry => 'Retry';

  @override
  String get onboardingSkip => 'Skip';

  @override
  String get onboardingNext => 'Next';

  @override
  String get onboardingStart => 'Get started';

  @override
  String get onboardingSlide1Title => 'AI custom stories';

  @override
  String get onboardingSlide1Subtitle =>
      'AI creates stories tailored to your child.';

  @override
  String get onboardingSlide2Title => 'Make characters from photos';

  @override
  String get onboardingSlide2Subtitle =>
      'Turn your child\'s photo into the story\'s hero.';

  @override
  String get onboardingSlide3Title => 'A daily reading habit';

  @override
  String get onboardingSlide3Subtitle =>
      'Build a daily reading habit with streaks.';

  @override
  String get onboardingSlide4Title => 'Start for free';

  @override
  String get onboardingSlide4Subtitle =>
      'Make your first storybook with 3 starter credits.';

  @override
  String onboardingPageIndicator(int current, int total) {
    return 'Page $current of $total';
  }

  @override
  String get homeTitle => 'AI Story Book';

  @override
  String get homeSettingsTooltip => 'Settings';

  @override
  String get homeHeaderSubtitle => 'Create custom storybooks for your child';

  @override
  String get homeSectionTodayReading => 'Today\'s reading';

  @override
  String get homeSectionForParents => 'For parents';

  @override
  String get homeRecentBooksTitle => 'Recently created';

  @override
  String get homeViewAll => 'View all';

  @override
  String get homeEmptyTitle => 'No storybooks yet';

  @override
  String get homeEmptySubtitle => 'Create your first storybook!';

  @override
  String get homeLibraryErrorTitle => 'Couldn\'t load your storybooks';

  @override
  String get homeCreateCardTitle => 'Create a new storybook';

  @override
  String get homeCreateCardSubtitle =>
      'Make a custom storybook\nwith your child as the hero';

  @override
  String get homeQuickStartTitle => 'Start with my character';

  @override
  String homeStreakDaysLabel(Object days) {
    return '$days-day reading streak';
  }

  @override
  String get homeReadTodayBadge => 'Read today';

  @override
  String get homeNotReadTodayBadge => 'Not done today';

  @override
  String homeStreakSummary(Object total, Object longest) {
    return 'Read on $total days total · Best $longest days';
  }

  @override
  String get homeRecent7Days => 'Last 7 days';

  @override
  String homeTodayStoryLabel(Object theme) {
    return 'Today\'s storybook · $theme';
  }

  @override
  String get homeContinueReading => 'Continue reading';

  @override
  String get homeMakeTodayStory => 'Make today\'s storybook';

  @override
  String get homeStreakLoading => 'Loading streak info...';

  @override
  String get homeStreakErrorTitle => 'Streak card error';

  @override
  String get homeStreakLoadError => 'Couldn\'t load streak info.';

  @override
  String get homeGrowthEntryTitle => 'View reading growth';

  @override
  String homeGrowthSubtitleStats(Object vocab, Object accuracy) {
    return '$vocab words learned · $accuracy% accuracy';
  }

  @override
  String get homeWeekdayMon => 'Mon';

  @override
  String get homeWeekdayTue => 'Tue';

  @override
  String get homeWeekdayWed => 'Wed';

  @override
  String get homeWeekdayThu => 'Thu';

  @override
  String get homeWeekdayFri => 'Fri';

  @override
  String get homeWeekdaySat => 'Sat';

  @override
  String get homeWeekdaySun => 'Sun';

  @override
  String get homeWeekdayUnknown => '-';

  @override
  String get createTitle => 'Create a New Storybook';

  @override
  String get createCloseTooltip => 'Close';

  @override
  String get createTopicLabel => 'What kind of story shall we make?';

  @override
  String get createTopicHint => 'e.g. A story about a rabbit flying in the sky';

  @override
  String get createTopicRequired => 'Please enter a story topic';

  @override
  String get createTopicTooShort => 'Please add a little more detail';

  @override
  String get createChildNameLabel => 'Your child\'s name (optional)';

  @override
  String get createChildNameHint => 'e.g. Minji';

  @override
  String get createAgeLabel => 'Child\'s age group';

  @override
  String get createAgeHelp3to5 => 'Simple words, 1-2 short sentences, repetition and sound words';

  @override
  String get createAgeHelp5to7 => 'Familiar words, 2-3 sentences, feelings and simple dialogue';

  @override
  String get createAgeHelp7to9 => 'Richer words, 2-4 sentences, cause and effect';

  @override
  String get createAgeHelpAdult => 'No length limit, dense narrative';

  @override
  String get createStyleLabel => 'Art style';

  @override
  String get createThemeLabel => 'Theme (optional)';

  @override
  String get createThemeNone => 'None';

  @override
  String get createCharacterLabel => 'Main character';

  @override
  String get createAddCharacter => 'Add character';

  @override
  String get createCharacterHint =>
      'Pick an existing character, or let AI create a new one';

  @override
  String get createAiCharacterTitle => 'AI creates a new character';

  @override
  String get createAiCharacterDesc =>
      'Automatically creates a character that fits the story';

  @override
  String get createChildProtagonistTitle =>
      'Make your child the main character';

  @override
  String get createChildProtagonistDesc =>
      'Create the main character from a photo or a default character';

  @override
  String get createOrSelectExisting => 'Or choose an existing character';

  @override
  String createSelectedCount(Object count) {
    return '$count selected (family/friend stories possible)';
  }

  @override
  String get createAddCharacterTip =>
      'Add a character to make a series with the same character!';

  @override
  String get createCharacterLoadError => 'Couldn\'t load characters';

  @override
  String get createMakeButton => 'Make Storybook';

  @override
  String get createPlanUpgradeTitle => 'A plan upgrade is needed';

  @override
  String get createCreditShortageTitle => 'Not enough credits';

  @override
  String get createFailedSnack =>
      'Failed to create the storybook. Please try again in a moment.';

  @override
  String get libraryTitle => 'My Library';

  @override
  String get libraryRefresh => 'Refresh';

  @override
  String get librarySortNewest => 'Newest';

  @override
  String get librarySortOldest => 'Oldest';

  @override
  String get librarySortTitle => 'By title';

  @override
  String get libraryStyleWatercolor => 'Watercolor';

  @override
  String get libraryStyleCartoon => 'Cartoon';

  @override
  String get libraryStyle3d => '3D';

  @override
  String get libraryStylePixel => 'Pixel';

  @override
  String get libraryStyleOilPainting => 'Oil painting';

  @override
  String get libraryStyleClaymation => 'Claymation';

  @override
  String get libraryStyleRealistic => 'Realistic';

  @override
  String get libraryAge3to5 => 'Ages 3-5';

  @override
  String get libraryAge5to7 => 'Ages 5-7';

  @override
  String get libraryAge7to9 => 'Ages 7-9';

  @override
  String get libraryAgeAdult => 'Adult';

  @override
  String get libraryRenameDialogTitle => 'Rename storybook';

  @override
  String get libraryRenameFieldLabel => 'Title';

  @override
  String get libraryRenameFieldHint => 'Please enter the storybook title';

  @override
  String get libraryCancel => 'Cancel';

  @override
  String get librarySave => 'Save';

  @override
  String get libraryRenameSuccess => 'The storybook name has been updated.';

  @override
  String get libraryDeleteDialogTitle => 'Delete storybook';

  @override
  String libraryDeleteDialogContent(Object title) {
    return 'Delete \"$title\"?\nDeleted storybooks cannot be recovered.';
  }

  @override
  String get libraryDelete => 'Delete';

  @override
  String get libraryDeleteSuccess => 'The storybook has been deleted.';

  @override
  String get libraryErrorNetwork =>
      'Please check your internet connection and try again.';

  @override
  String get libraryErrorGeneric =>
      'An error occurred while processing your request. Please try again in a moment.';

  @override
  String libraryShareMessage(Object title) {
    return '📚 $title\n\nThis is a storybook made with AI Story Book.\nShare a special story with your child!';
  }

  @override
  String get libraryShareFailed =>
      'Sharing failed. Please try again in a moment.';

  @override
  String get librarySortLabel => 'Sort';

  @override
  String get libraryStyleLabel => 'Style';

  @override
  String get libraryAgeLabel => 'Age';

  @override
  String get libraryFilterAll => 'All';

  @override
  String get libraryResetFilters => 'Reset filters';

  @override
  String get libraryEmptyFilterTitle => 'No storybooks match your filters';

  @override
  String get libraryEmptyTitle => 'You haven\'t made any storybooks yet';

  @override
  String get libraryEmptyFilterSubtitle =>
      'Clear the filters to view your full library.';

  @override
  String get libraryEmptySubtitle => 'Make your first storybook!';

  @override
  String get libraryCreateNew => 'Make a new storybook';

  @override
  String get libraryLoadError => 'Couldn\'t load your library';

  @override
  String get libraryRetry => 'Retry';

  @override
  String get libraryDateToday => 'Today';

  @override
  String get libraryDateYesterday => 'Yesterday';

  @override
  String libraryDateDaysAgo(Object days) {
    return '$days days ago';
  }

  @override
  String libraryDateMonthDay(Object month, Object day) {
    return '$month/$day';
  }

  @override
  String get libraryClose => 'Close';

  @override
  String get libraryOfflineBanner =>
      'You\'re offline. Showing recently loaded storybooks.';

  @override
  String get libraryBookOptions => 'Storybook options';

  @override
  String get libraryMenuRename => 'Rename';

  @override
  String get libraryMenuShare => 'Share';

  @override
  String get libraryMenuDelete => 'Delete';

  @override
  String get loadingTitle => 'Creating your storybook';

  @override
  String get loadingCompleted => 'All done!';

  @override
  String get loadingErrorTitle => 'Something went wrong';

  @override
  String get loadingUnknownError => 'Unknown error';

  @override
  String get loadingRetryButton => 'Retry';

  @override
  String get loadingCheckStatusButton => 'Check status again';

  @override
  String get loadingBackToHomeButton => 'Back to home';

  @override
  String get loadingStepWaiting => 'Waiting...';

  @override
  String get loadingStepPreparing => 'Preparing...';

  @override
  String get loadingStepNormalize => 'Analyzing your input';

  @override
  String get loadingStepModerateInput => 'Checking safety';

  @override
  String get loadingStepGenerateStory => 'Writing the story';

  @override
  String get loadingStepGenerateCharacterSheet => 'Designing the character';

  @override
  String get loadingStepGenerateImagePrompts => 'Preparing the illustrations';

  @override
  String get loadingStepGenerateImages => 'Drawing the illustrations';

  @override
  String get loadingStepModerateOutput => 'Running the final check';

  @override
  String get loadingStepPackage => 'Wrapping things up';

  @override
  String get loadingTip1 =>
      'The story is written with words and sentences suited to your child';

  @override
  String get loadingTip2 =>
      'The AI takes care to keep the character consistent';

  @override
  String get loadingTip3 =>
      'You can revisit finished storybooks anytime in your library';

  @override
  String get loadingTip4 => 'You can regenerate any page you don\'t like later';

  @override
  String get loadingTip5 =>
      'You can also make a series of storybooks with the same character';

  @override
  String get profilesTitle => 'Child Profiles';

  @override
  String get profilesAddTooltip => 'Add profile';

  @override
  String get profilesLoadError => 'Couldn\'t load profile information.';

  @override
  String get profilesDialogAddTitle => 'Add Profile';

  @override
  String get profilesDialogEditTitle => 'Edit Profile';

  @override
  String get profilesNameLabel => 'Name';

  @override
  String get profilesNameHint => 'e.g. Minji';

  @override
  String get profilesNameRequired => 'Please enter a name.';

  @override
  String get profilesBirthYearLabel => 'Birth year (optional)';

  @override
  String get profilesBirthMonthLabel => 'Month';

  @override
  String profilesYearOption(Object year) {
    return '$year';
  }

  @override
  String profilesMonthOption(Object month) {
    return '$month';
  }

  @override
  String profilesAgeBandAuto(Object band) {
    return 'Age band auto: $band yrs';
  }

  @override
  String get profilesBirthHint =>
      'Enter the birth year and month to set the age band automatically (optional).';

  @override
  String get profilesAgeBandLabel => 'Age band';

  @override
  String get profilesAgeBand35 => 'Ages 3-5';

  @override
  String get profilesAgeBand57 => 'Ages 5-7';

  @override
  String get profilesAgeBand79 => 'Ages 7-9';

  @override
  String get profilesAgeBandAdult => 'Adult';

  @override
  String profilesAgeBandValue(Object label) {
    return 'Age band: $label';
  }

  @override
  String get profilesSetAsDefaultSwitch => 'Set as default profile';

  @override
  String get profilesCancel => 'Cancel';

  @override
  String get profilesAddAction => 'Add';

  @override
  String get profilesSaveAction => 'Save';

  @override
  String get profilesCreateFailed =>
      'Failed to create the profile. Please try again in a moment.';

  @override
  String get profilesEditFailed => 'Failed to edit the profile.';

  @override
  String get profilesSetDefaultFailed => 'Failed to set the default profile.';

  @override
  String get profilesDeleteTitle => 'Delete Profile';

  @override
  String get profilesDeleteConfirm => 'Delete this profile?';

  @override
  String get profilesDeleteAction => 'Delete';

  @override
  String get profilesDeleteFailed => 'Failed to delete the profile.';

  @override
  String get profilesEmpty => 'No profiles registered';

  @override
  String get profilesCreateFirst => 'Create your first profile';

  @override
  String get profilesDefaultBadge => 'Default';

  @override
  String get profilesActiveBadge => 'Active';

  @override
  String get profilesMenuActivate => 'Use as active profile';

  @override
  String get profilesMenuSetDefault => 'Set as default profile';

  @override
  String get profilesMenuEdit => 'Edit';

  @override
  String get voiceProfilesTitle => 'Family voices';

  @override
  String get voiceProfilesAddTooltip => 'Add voice profile';

  @override
  String get voiceProfilesMenuTooltip => 'Open menu';

  @override
  String get voiceProfilesLoadError => 'Could not load family voice info.';

  @override
  String get voiceProfilesAddTitle => 'Add voice profile';

  @override
  String get voiceProfilesEditTitle => 'Edit voice profile';

  @override
  String get voiceProfilesLabelFieldLabel => 'Name / label';

  @override
  String get voiceProfilesLabelFieldHint => 'e.g. Mom\'s voice';

  @override
  String get voiceProfilesLabelRequired => 'Please enter a label.';

  @override
  String get voiceProfilesRelationshipFieldLabel => 'Relationship';

  @override
  String get voiceProfilesRelationshipFieldHint => 'e.g. mother, grandmother';

  @override
  String get voiceProfilesSampleUrlFieldLabel => 'Sample audio URL';

  @override
  String get voiceProfilesSampleUrlRequired =>
      'Please enter a sample audio URL.';

  @override
  String get voiceProfilesSampleUrlInvalid => 'Please enter a valid URL.';

  @override
  String get voiceProfilesSampleUploadSuccess =>
      'Voice sample upload complete.';

  @override
  String get voiceProfilesSampleUploadError =>
      'Sample upload failed. Please try again.';

  @override
  String get voiceProfilesUploading => 'Uploading...';

  @override
  String get voiceProfilesUploadAudioButton => 'Upload audio file';

  @override
  String get voiceProfilesConsentToggle => 'Guardian consent complete';

  @override
  String get voiceProfilesActiveToggle => 'Active status';

  @override
  String get voiceProfilesCancel => 'Cancel';

  @override
  String get voiceProfilesAdd => 'Add';

  @override
  String get voiceProfilesSave => 'Save';

  @override
  String get voiceProfilesCreateError => 'Failed to create voice profile.';

  @override
  String get voiceProfilesEditError => 'Failed to edit voice profile.';

  @override
  String get voiceProfilesRevokeError => 'Failed to revoke consent.';

  @override
  String get voiceProfilesDeleteTitle => 'Delete voice profile';

  @override
  String get voiceProfilesDeleteConfirm => 'Delete this voice profile?';

  @override
  String get voiceProfilesDelete => 'Delete';

  @override
  String get voiceProfilesDeleteError => 'Failed to delete voice profile.';

  @override
  String get voiceProfilesEmpty =>
      'No family voices registered yet.\nTap the + button in the top right to add one.';

  @override
  String get voiceProfilesUnnamed => 'Unnamed';

  @override
  String get voiceProfilesMenuEdit => 'Edit';

  @override
  String get voiceProfilesMenuRevoke => 'Revoke consent';

  @override
  String get voiceProfilesMenuDelete => 'Delete';

  @override
  String voiceProfilesRelationshipPrefix(Object relationship) {
    return 'Relationship: $relationship';
  }

  @override
  String get voiceProfilesConsentDone => 'Consent complete';

  @override
  String get voiceProfilesConsentNeeded => 'Consent needed';

  @override
  String get voiceProfilesActive => 'Active';

  @override
  String get voiceProfilesInactive => 'Inactive';

  @override
  String get podOrderTitle => 'Order printed book';

  @override
  String get podOrderBookLabel => 'Storybook to order';

  @override
  String get podOrderRecipientNameLabel => 'Recipient name';

  @override
  String get podOrderRecipientNameError => 'Please enter the recipient name.';

  @override
  String get podOrderAddressLabel => 'Address';

  @override
  String get podOrderAddressError => 'Please enter the address.';

  @override
  String get podOrderPostalLabel => 'Postal code';

  @override
  String get podOrderPostalError => 'Please enter the postal code.';

  @override
  String get podOrderCountryLabel => 'Country code';

  @override
  String get podOrderCountryError => 'Please enter the country code.';

  @override
  String get podOrderPhoneLabel => 'Phone number';

  @override
  String get podOrderPhoneError => 'Please enter the phone number.';

  @override
  String get podOrderQuantityLabel => 'Quantity';

  @override
  String podOrderQuantityValue(Object count) {
    return '$count copies';
  }

  @override
  String podOrderEstimatedTotal(Object amount) {
    return 'Est. $amount KRW';
  }

  @override
  String get podOrderSubmitting => 'Processing order...';

  @override
  String get podOrderSubmitButton => 'Place order';

  @override
  String get podOrderSubmitSuccess => 'Your order has been received.';

  @override
  String get podOrderSubmitError =>
      'Failed to place the order. Please check your details.';

  @override
  String get podOrderStatusError => 'Failed to load the order status.';

  @override
  String get podOrderStatusTitle => 'Order status';

  @override
  String podOrderOrderNumber(Object orderId) {
    return 'Order number: $orderId';
  }

  @override
  String podOrderProviderOrderNumber(Object providerOrderId) {
    return 'Supplier order number: $providerOrderId';
  }

  @override
  String get podOrderCopyTooltip => 'Copy';

  @override
  String get podOrderProviderOrderCopied => 'Copied the supplier order number.';

  @override
  String podOrderStatusValue(Object status) {
    return 'Status: $status';
  }

  @override
  String podOrderPaymentAmount(Object amount) {
    return 'Payment amount: $amount KRW';
  }

  @override
  String podOrderSyncValue(Object source) {
    return 'Sync: $source';
  }

  @override
  String podOrderTrackingNumber(Object trackingNumber) {
    return 'Tracking number: $trackingNumber';
  }

  @override
  String get podOrderRefreshStatus => 'Refresh status';

  @override
  String get podOrderDecreaseQuantityTooltip => 'Decrease quantity';

  @override
  String get podOrderIncreaseQuantityTooltip => 'Increase quantity';

  @override
  String get branchStoryTitle => 'Branching story';

  @override
  String get branchStoryRefreshTooltip => 'Refresh';

  @override
  String get branchStoryLoadError => 'Couldn\'t load the branching story.';

  @override
  String get branchStoryResumeStatus =>
      'Continuing reading from where you left off.';

  @override
  String get branchStoryEndingReached =>
      'You\'ve reached the ending of this branch.';

  @override
  String get branchStoryChoiceApplied => 'Your choice was applied.';

  @override
  String branchStoryEndingArrived(Object selected) {
    return 'Ending reached: $selected';
  }

  @override
  String branchStorySelected(Object selected) {
    return 'Selected: $selected';
  }

  @override
  String get branchStoryChoiceFailed =>
      'Couldn\'t apply your choice. Please try again.';

  @override
  String get branchStorySampleText1 =>
      'The rabbit stood at a fork in the road.';

  @override
  String get branchStorySampleText2 => 'On the left path, it met a new friend.';

  @override
  String get branchStorySampleText3 =>
      'On the right path, it discovered a treasure.';

  @override
  String get branchStorySampleOptionLeft => 'Take the left path';

  @override
  String get branchStorySampleOptionRight => 'Take the right path';

  @override
  String get branchStorySampleCreated => 'Created a sample branching story.';

  @override
  String get branchStorySampleCreateFailed =>
      'Couldn\'t create the sample branch.';

  @override
  String branchStoryNodeLabel(Object nodeKey) {
    return 'Node: $nodeKey';
  }

  @override
  String branchStoryPageLabel(Object pageNumber) {
    return 'Page $pageNumber';
  }

  @override
  String get branchStoryImageSemantics => 'Branching story illustration';

  @override
  String get branchStoryOptionsHeading => 'Choices';

  @override
  String get branchStoryNoOptions =>
      'There are no more choices. This is the ending of this branch.';

  @override
  String get branchStoryPreviousChoice => 'Previous choice';

  @override
  String get branchStoryRestart => 'Restart';

  @override
  String get branchStoryRetry => 'Retry';

  @override
  String get branchStoryEmptyTitle => 'There\'s no branching story yet.';

  @override
  String get branchStoryEmptySubtitle =>
      'Create a sample branch to try an interactive story right away.';

  @override
  String get branchStorySampleCreating => 'Creating...';

  @override
  String get branchStoryCreateSample => 'Create sample branch';

  @override
  String get pronunciationTitle => 'Pronunciation Practice';

  @override
  String pronunciationIntro(Object pageNumber) {
    return 'Pronunciation is evaluated against the sentence on storybook page $pageNumber.';
  }

  @override
  String get pronunciationExpectedLabel => 'Reference sentence';

  @override
  String get pronunciationTranscriptLabel => 'Read sentence (text input)';

  @override
  String get pronunciationTranscriptHint =>
      'Please enter the sentence your child read.';

  @override
  String get pronunciationEvaluating => 'Evaluating...';

  @override
  String get pronunciationEvaluateButton => 'Evaluate pronunciation';

  @override
  String get pronunciationEvaluateAudioButton => 'Evaluate with audio file';

  @override
  String pronunciationScore(Object score) {
    return 'Pronunciation score: $score';
  }

  @override
  String get pronunciationNoFeedback => 'No feedback available.';

  @override
  String get pronunciationErrorBothRequired =>
      'Please enter both the reference sentence and the read sentence.';

  @override
  String get pronunciationErrorEvaluateFailed =>
      'Pronunciation evaluation failed. Please try again in a moment.';

  @override
  String get pronunciationErrorExpectedRequired =>
      'Please enter the reference sentence first.';

  @override
  String get pronunciationErrorAudioEvaluateFailed =>
      'Audio pronunciation evaluation failed. Please try again.';

  @override
  String get parentDashboardLoadError => 'Couldn\'t load the dashboard data.';

  @override
  String get parentDashboardReportMonthly => 'Monthly report';

  @override
  String get parentDashboardReportWeekly => 'Weekly report';

  @override
  String get parentDashboardTitle => 'Parent dashboard';

  @override
  String get parentDashboardRefreshTooltip => 'Refresh';

  @override
  String get parentDashboardSegmentWeekly => 'Weekly';

  @override
  String get parentDashboardSegmentMonthly => 'Monthly';

  @override
  String get parentDashboardThemeUnspecified => 'Unspecified';

  @override
  String get parentDashboardMetricTotalBooksTitle => 'Total storybooks read';

  @override
  String parentDashboardMetricTotalBooksValue(Object count) {
    return '$count';
  }

  @override
  String get parentDashboardMetricTotalMinutesTitle => 'Total reading time';

  @override
  String parentDashboardMetricTotalMinutesValue(Object minutes) {
    return '$minutes min';
  }

  @override
  String get parentDashboardMetricAvgMinutesTitle => 'Average reading time';

  @override
  String parentDashboardMetricAvgMinutesValue(Object minutes) {
    return '$minutes min';
  }

  @override
  String get parentDashboardMetricPreferredThemeTitle => 'Preferred theme';

  @override
  String get parentDashboardLearningTitle => 'Learning progress';

  @override
  String parentDashboardLearningStreakLine(Object current, Object longest) {
    return 'Current streak $current days · Best $longest days';
  }

  @override
  String parentDashboardLearningSessionLine(Object completed, Object total) {
    return 'Completed sessions $completed / total sessions $total';
  }

  @override
  String parentDashboardLearningCompletionLine(Object rate) {
    return 'Completion rate $rate%';
  }

  @override
  String get parentDashboardDailyChartTitle => 'Daily reading time';

  @override
  String get settingsLoadError => 'Couldn\'t load settings.';

  @override
  String get settingsSaved => 'Settings saved.';

  @override
  String get settingsSaveError =>
      'Failed to save settings. Please try again shortly.';

  @override
  String get settingsBedtimeNotificationTitle =>
      'It\'s time to read today\'s storybook';

  @override
  String get settingsBedtimeNotificationBody =>
      'Let\'s read today\'s storybook together before bed';

  @override
  String get settingsRevokeConsentTitle => 'Revoke consent';

  @override
  String get settingsRevokeConsentContent =>
      'If you revoke consent, app usage will be restricted and you can proceed with data deletion.';

  @override
  String get settingsCancel => 'Cancel';

  @override
  String get settingsRevoke => 'Revoke';

  @override
  String get settingsRevokeConsentError =>
      'Failed to process the revocation. Please check your network and try again.';

  @override
  String get settingsConsentRevoked => 'Consent has been revoked.';

  @override
  String get settingsDeleteAllTitle => 'Delete all my data';

  @override
  String get settingsDeleteAllContent =>
      'This action cannot be undone. Do you want to continue?';

  @override
  String get settingsContinue => 'Continue';

  @override
  String get settingsFinalConfirmTitle => 'Final confirmation';

  @override
  String get settingsFinalConfirmPrompt =>
      'To proceed with deletion, type \"삭제\" below.';

  @override
  String get settingsDeleteKeyword => 'Delete';

  @override
  String get settingsDeleteKeywordMismatch =>
      'The confirmation text does not match.';

  @override
  String get settingsDeleteError =>
      'Failed to delete data. Please try again shortly.';

  @override
  String get settingsLinkCopied => 'Link copied.';

  @override
  String get settingsTitle => 'Settings';

  @override
  String get settingsSave => 'Save';

  @override
  String get settingsSectionAccount => 'Account';

  @override
  String get settingsChildProfile => 'Child profile';

  @override
  String get settingsParentDashboard => 'Parent dashboard';

  @override
  String get settingsParentDashboardSubtitle => 'Weekly/monthly reading report';

  @override
  String get settingsFamilyVoice => 'Family voice';

  @override
  String get settingsFamilyVoiceSubtitle =>
      'Manage recording samples and consent status';

  @override
  String get settingsCreditsSubscription => 'Credits/Subscription';

  @override
  String get settingsSectionApp => 'App settings';

  @override
  String get settingsLanguage => 'Language';

  @override
  String get settingsLanguageKorean => '한국어';

  @override
  String get settingsLanguageEnglish => 'English';

  @override
  String get settingsDarkMode => 'Dark mode';

  @override
  String get settingsDarkModeSubtitle =>
      'Changes the entire app theme to dark.';

  @override
  String get settingsKakaoShare => 'KakaoTalk card sharing';

  @override
  String get settingsKakaoShareSubtitle =>
      'Shows KakaoTalk sharing in the share menu.';

  @override
  String get settingsSectionSleep => 'Sleep mode';

  @override
  String get settingsBedtimeNotification => 'Bedtime notification';

  @override
  String get settingsBedtime => 'Bedtime';

  @override
  String settingsSleepTimer(Object minutes) {
    return 'Default sleep timer: $minutes min';
  }

  @override
  String settingsMinutes(Object minutes) {
    return '$minutes min';
  }

  @override
  String get settingsSectionScreenTime => 'Screen time limit';

  @override
  String get settingsScreenTimeEnabled => 'Enable screen time limit';

  @override
  String settingsDailyLimit(Object minutes) {
    return 'Daily limit: $minutes min';
  }

  @override
  String get settingsSectionAppInfo => 'App info';

  @override
  String get settingsAppVersion => 'App version';

  @override
  String get settingsPrivacyPolicy => 'Privacy policy';

  @override
  String get settingsTermsOfService => 'Terms of service';

  @override
  String get settingsSectionPrivacy => 'Privacy';

  @override
  String get settingsRevokeParentalConsent => 'Revoke parental consent';

  @override
  String get settingsDeleteAllData => 'Delete all my data';

  @override
  String get settingsDeleteAllDataSubtitle =>
      'All data including storybooks, characters, and reading records will be deleted.';

  @override
  String get creditsTitle => 'Credits';

  @override
  String get creditsRestorePurchases => 'Restore Purchases';

  @override
  String get creditsLoadError =>
      'Couldn\'t load credit info. Please try again in a moment.';

  @override
  String get creditsMyCredits => 'My Credits';

  @override
  String creditsTotalCreated(Object count) {
    return '$count created in total';
  }

  @override
  String get creditsUnit => 'credits';

  @override
  String get creditsBuyCredits => 'Buy Credits';

  @override
  String get creditsBadgeCancelScheduled => 'Cancellation scheduled';

  @override
  String get creditsBadgeActive => 'Active';

  @override
  String get creditsSubscriptionInfo => 'Subscription Info';

  @override
  String get creditsNoActivePlan => 'You have no active subscription plan.';

  @override
  String get creditsStartSubscription => 'Start Subscription';

  @override
  String creditsPlanSubscriptionLabel(Object planName) {
    return '$planName subscription';
  }

  @override
  String get creditsDefaultPlanName => 'Basic';

  @override
  String get creditsMonthlyCredits => 'Monthly Credits';

  @override
  String creditsCreditCount(Object count) {
    return '$count';
  }

  @override
  String get creditsNextRenewal => 'Next Renewal';

  @override
  String get creditsCancelNotice =>
      'When the current billing cycle ends, you\'ll switch to the free plan.';

  @override
  String get creditsCancelSubscription => 'Cancel Subscription';

  @override
  String get creditsPlansTitle => 'Subscription Plans';

  @override
  String get creditsNoAvailablePlans =>
      'No subscription plans are currently available.';

  @override
  String get creditsPlanFallbackName => 'Plan';

  @override
  String get creditsCurrentPlan => 'Current Plan';

  @override
  String get creditsFree => 'Free';

  @override
  String creditsPricePerMonth(Object price) {
    return '₩$price/month';
  }

  @override
  String creditsMonthlyCreatable(Object count) {
    return 'Create up to $count per month';
  }

  @override
  String get creditsSubscribe => 'Subscribe';

  @override
  String get creditsPackTitle => 'Credit Packs';

  @override
  String creditsPackName(Object count) {
    return '$count Credit Pack';
  }

  @override
  String get creditsPackSubtitle => 'Top up instantly when you need it';

  @override
  String get creditsBuy => 'Buy';

  @override
  String get creditsTransactionsTitle => 'Transaction History';

  @override
  String get creditsTransactionFallback => 'Transaction';

  @override
  String get creditsRestoring => 'Restoring your purchases...';

  @override
  String get creditsRestoreFailed =>
      'Restore failed. Please try again in a moment.';

  @override
  String get creditsPaymentCancelledOrFailed =>
      'The payment was cancelled or failed.';

  @override
  String get creditsAlreadyProcessed =>
      'This payment has already been processed.';

  @override
  String get creditsAlreadySubscribed => 'You\'re already on the same plan.';

  @override
  String get creditsVerifiedReflected =>
      'Payment confirmed and credits have been applied.';

  @override
  String get creditsVerifyFailed =>
      'Payment verification failed. Please try again in a moment.';

  @override
  String get creditsStoreUnavailable => 'Store payments are unavailable.';

  @override
  String get creditsProceedStorePayment =>
      'Please proceed with the store payment.';

  @override
  String get creditsCannotStartStorePurchase =>
      'Couldn\'t start the store purchase.';

  @override
  String get creditsSubscriptionStarted => 'Subscription started!';

  @override
  String get creditsSubscribeFailed =>
      'Subscription failed. Please try again in a moment.';

  @override
  String get creditsCancelConfirmContent =>
      'Are you sure you want to cancel your subscription? You can keep using it until the current period ends.';

  @override
  String get creditsNo => 'No';

  @override
  String get creditsConfirmCancel => 'Cancel';

  @override
  String get creditsSubscriptionCancelled =>
      'Your subscription has been cancelled.';

  @override
  String get creditsCancelFailed =>
      'Failed to cancel the subscription. Please try again in a moment.';

  @override
  String get charactersTitle => 'My Characters';

  @override
  String get charactersAddTooltip => 'Add character';

  @override
  String get charactersRefreshTooltip => 'Refresh';

  @override
  String get charactersEmptyTitle => 'No characters yet';

  @override
  String get charactersEmptySubtitle => 'Make a character from a photo!';

  @override
  String get charactersEmptyCreateButton => 'Make a character from a photo';

  @override
  String get charactersLoadErrorTitle => 'Couldn\'t load characters';

  @override
  String get charactersRetry => 'Retry';

  @override
  String get charactersFabCreating => 'Creating...';

  @override
  String get charactersFabCreate => 'Make from photo';

  @override
  String get charactersOptionsTitle => 'Make a new character';

  @override
  String get charactersOptionsSubtitle => 'Choose how to create the character';

  @override
  String get charactersOptionTextTitle => 'Enter manually';

  @override
  String get charactersOptionTextSubtitle => 'Enter just name, age, and traits';

  @override
  String get charactersOptionCameraTitle => 'Take a photo';

  @override
  String get charactersOptionCameraSubtitle =>
      'Analyze a photo to create a character';

  @override
  String get charactersOptionGalleryTitle => 'Choose from gallery';

  @override
  String get charactersOptionGallerySubtitle =>
      'Create a character from an existing photo';

  @override
  String get charactersOptionDrawingTitle => 'Convert from a child\'s drawing';

  @override
  String get charactersOptionDrawingSubtitle =>
      'Turn a drawing photo into a character and sheet';

  @override
  String charactersCreatedSnack(Object name) {
    return 'Character $name has been created!';
  }

  @override
  String charactersCreatedWithSheetsSnack(Object name, Object count) {
    return 'Made character $name with $count sheets!';
  }

  @override
  String get charactersCreateFailed =>
      'Failed to create the character. Please try again in a moment.';

  @override
  String get charactersImagePickFailed =>
      'Couldn\'t select the image. Please try again.';

  @override
  String get charactersNameDialogTitle => 'Character name';

  @override
  String get charactersNameDialogHint => 'Enter a character name (optional)';

  @override
  String get charactersCancel => 'Cancel';

  @override
  String get charactersConfirm => 'OK';

  @override
  String get charactersDeleteDialogTitle => 'Delete character';

  @override
  String charactersDeleteDialogContent(Object name) {
    return 'Delete the character \"$name\"?';
  }

  @override
  String get charactersDelete => 'Delete';

  @override
  String get charactersDeletedSnack => 'The character has been deleted.';

  @override
  String get charactersDeleteFailed =>
      'Failed to delete the character. Please try again.';

  @override
  String get charactersDefaultName => 'New character';

  @override
  String get charactersAddCardLoading => 'Creating character...';

  @override
  String get charactersAddCardTitle => 'Add a new character';

  @override
  String get charactersAddCardSubtitle =>
      'Make your own character from a photo';

  @override
  String get charactersDetailDescription => 'Description';

  @override
  String get charactersDetailPersonality => 'Personality';

  @override
  String get charactersDetailAppearance => 'Appearance';

  @override
  String get charactersDetailAge => 'Age';

  @override
  String get charactersDetailFace => 'Face';

  @override
  String get charactersDetailHair => 'Hair';

  @override
  String get charactersDetailSkin => 'Skin';

  @override
  String get charactersDetailBody => 'Body';

  @override
  String get charactersDetailClothing => 'Clothing';

  @override
  String get charactersDetailTop => 'Top';

  @override
  String get charactersDetailBottom => 'Bottom';

  @override
  String get charactersDetailShoes => 'Shoes';

  @override
  String get charactersDetailAccessories => 'Accessories';

  @override
  String get charactersDetailStyleNotes => 'Style notes';

  @override
  String get charactersDetailCreateBookButton =>
      'Make a new storybook with this character';

  @override
  String charactersCreatedDate(Object year, Object month, Object day) {
    return 'Created on $year-$month-$day';
  }

  @override
  String get charactersRoleChild => 'Child';

  @override
  String get charactersRoleBrother => 'Older brother';

  @override
  String get charactersRoleSister => 'Older sister';

  @override
  String get charactersRoleMom => 'Mom';

  @override
  String get charactersRoleDad => 'Dad';

  @override
  String get charactersRoleGrandma => 'Grandma';

  @override
  String get charactersRoleGrandpa => 'Grandpa';

  @override
  String get charactersRoleFriend => 'Friend';

  @override
  String get charactersRoleTeacher => 'Teacher';

  @override
  String get charactersRolePet => 'Pet';

  @override
  String get charactersFormTitle => 'Make a new character';

  @override
  String get charactersFormRoleLabel => 'Who is it?';

  @override
  String get charactersFormCustomRole => 'Enter manually';

  @override
  String get charactersFormCustomRoleHint =>
      'e.g. uncle, aunt, wizard, fairy...';

  @override
  String get charactersFormNameLabel => 'Name';

  @override
  String get charactersFormNameHint => 'Enter a character name';

  @override
  String get charactersFormTraitsLabel => 'Personality / Traits';

  @override
  String get charactersFormTraitsHelper => 'You can select multiple';

  @override
  String get charactersFormTraitsExtraHint =>
      'Enter additional traits (optional)';

  @override
  String get charactersFormSubmit => 'Make character';

  @override
  String get charactersFormRoleRequired => 'Please enter a role';

  @override
  String get charactersFormRoleSelect => 'Please select a role';

  @override
  String get charactersFormNameRequired => 'Please enter a name';

  @override
  String get charactersFormTraitsRequired =>
      'Please select personality / traits';

  @override
  String get viewerBookLoadError => 'Couldn\'t load the storybook';

  @override
  String get viewerGoBack => 'Go back';

  @override
  String viewerSleepRemaining(Object time) {
    return 'Sleep $time';
  }

  @override
  String get viewerCompletionTitle => 'Congrats on finishing!';

  @override
  String viewerCompletionStreak(Object streak) {
    return '🔥 $streak-day reading streak achieved! Amazing.';
  }

  @override
  String get viewerCompletionMessage =>
      'You read to the last page. Shall we start the next storybook?';

  @override
  String get viewerCreateNextStory => 'Make the next storybook';

  @override
  String get viewerGoToLibrary => 'Go to library';

  @override
  String get viewerCover => 'Cover';

  @override
  String viewerPageIndicator(Object current, Object total) {
    return '$current / $total';
  }

  @override
  String viewerLearningWordCount(Object count) {
    return 'Words $count';
  }

  @override
  String viewerLearningQuizCount(Object count) {
    return 'Quiz $count';
  }

  @override
  String viewerLearningQuestionCount(Object count) {
    return 'Questions $count';
  }

  @override
  String viewerLearningBar(Object parts) {
    return 'Learning mode · $parts';
  }

  @override
  String get viewerCloseTooltip => 'Close';

  @override
  String get viewerMoreOptionsTooltip => 'More options';

  @override
  String get viewerPreviousPageTooltip => 'Previous page';

  @override
  String get viewerNextPageTooltip => 'Next page';

  @override
  String get viewerPlanUpgradeNeeded => 'You need to upgrade your plan';

  @override
  String get viewerCreditShortage => 'You don\'t have enough credits';

  @override
  String get viewerAudioPlayFailed =>
      'Audio playback failed. Please try again in a moment.';

  @override
  String get viewerSleepModeEnded => 'Sleep mode time has ended.';

  @override
  String get viewerFollowReadingOff => 'Turn off follow-along reading';

  @override
  String get viewerFollowReadingOn => 'Turn on follow-along reading';

  @override
  String get viewerFollowReadingSubtitle =>
      'Highlights sentences as the audio plays';

  @override
  String get viewerDualLanguageOff => 'Turn off dual-language display';

  @override
  String get viewerDualLanguageOn => 'Show both languages at once';

  @override
  String get viewerDualLanguageSubtitle =>
      'View Korean and English on one screen';

  @override
  String get viewerBranchStoryTitle => 'Branching story mode';

  @override
  String get viewerBranchStorySubtitle =>
      'The ending changes based on your choices';

  @override
  String get viewerLearningModeTitle => 'Learning mode';

  @override
  String get viewerLearningModeSubtitle => 'Words, questions, quiz';

  @override
  String get viewerParentGuideTitle => 'Parent guide';

  @override
  String get viewerParentGuideSubtitle => 'Discussion topics, activity ideas';

  @override
  String get viewerPronunciationTitle => 'Pronunciation practice';

  @override
  String get viewerPronunciationSubtitle =>
      'Evaluate your pronunciation with the current page\'s sentences';

  @override
  String get viewerRegeneratePageTitle => 'Remake this page';

  @override
  String get viewerSameCharacterNewStory => 'New story with the same character';

  @override
  String get viewerExportPdf => 'Export as PDF';

  @override
  String get viewerOrderPhysicalBook => 'Order a physical book';

  @override
  String get viewerOrderPhysicalBookSubtitle =>
      'Receive a printed copy via print-on-demand';

  @override
  String get viewerSleepModeStop => 'Exit sleep mode';

  @override
  String get viewerSleepModeStart => 'Start sleep mode';

  @override
  String viewerSleepModeRemaining(Object time) {
    return 'Time remaining $time';
  }

  @override
  String get viewerSleepModeDescription =>
      'Dim screen + auto audio playback + auto page turn';

  @override
  String get viewerPrint => 'Print';

  @override
  String get viewerShare => 'Share';

  @override
  String get viewerRegenerateDialogTitle => 'Remake page';

  @override
  String get viewerRegenerateDialogContent => 'Which part should we remake?';

  @override
  String get viewerCancel => 'Cancel';

  @override
  String get viewerRegenerateTextOnly => 'Text only';

  @override
  String get viewerRegenerateImageOnly => 'Image only';

  @override
  String get viewerRegenerateAll => 'All';

  @override
  String get viewerRegenerateNotSupported =>
      'This storybook doesn\'t support page regeneration';

  @override
  String get viewerRegenerating => 'Remaking the page...';

  @override
  String get viewerRegenerateStarted =>
      'Page regeneration has started. Please wait a moment.';

  @override
  String get viewerRegenerateFailed =>
      'Regeneration failed. Please try again in a moment.';

  @override
  String get viewerPdfGenerating => 'Generating PDF...';

  @override
  String viewerPdfSaved(Object fileName) {
    return 'PDF saved: $fileName';
  }

  @override
  String get viewerPdfDownloadFailed =>
      'PDF download failed. Please try again in a moment.';

  @override
  String get viewerShareLink => 'Share link';

  @override
  String get viewerShareCopyUrl => 'Copy URL';

  @override
  String get viewerShareMessage => 'Message';

  @override
  String get viewerShareKakao => 'KakaoTalk';

  @override
  String get viewerShareCover => 'Share cover';

  @override
  String get viewerSharePdf => 'Share PDF';

  @override
  String get viewerShareMore => 'More';

  @override
  String viewerShareTextSimple(Object title) {
    return '$title\n\nA storybook made with AI Story Book!';
  }

  @override
  String get viewerCopyDone => 'Copied';

  @override
  String viewerShareLinkText(Object title, Object url) {
    return 'A storybook starring our child \"$title\" 📖\n$url\n\nMade with Aistorybook';
  }

  @override
  String get viewerShareLinkFailed =>
      'Failed to create the share link. Please try again in a moment.';

  @override
  String viewerShareFullText(Object title) {
    return '📚 $title\n\nA storybook made with AI Story Book!\nGift your child a special story ✨';
  }

  @override
  String get viewerKakaoDescription => 'A storybook made with AI Story Book';

  @override
  String viewerKakaoShareText(
      Object title, Object deepLink, Object fallbackUrl) {
    return '📚 $title\n\nShare the storybook via KakaoTalk!\n$deepLink\n$fallbackUrl';
  }

  @override
  String viewerKakaoShareSubject(Object title) {
    return 'AI Story Book - $title';
  }

  @override
  String get viewerPrintFailed =>
      'Printing failed. Please try again in a moment.';

  @override
  String viewerShareCoverText(Object title) {
    return '$title - Cover image';
  }

  @override
  String get viewerShareCoverFailed =>
      'Failed to share the cover. Please try again in a moment.';

  @override
  String viewerSharePdfText(Object title) {
    return '$title - A storybook made with AI Story Book';
  }

  @override
  String get viewerSharePdfFailed =>
      'Failed to share the PDF. Please try again in a moment.';

  @override
  String viewerCoverImageSemantics(Object title) {
    return 'Storybook cover: $title';
  }

  @override
  String viewerPageImageSemantics(Object page) {
    return 'Page $page illustration';
  }

  @override
  String get viewerLearn => 'Learn';

  @override
  String get viewerPlayAudioTooltip => 'Play audio';

  @override
  String get viewerPauseAudioTooltip => 'Pause audio';

  @override
  String get viewerLanguageToggleTooltip => 'Switch language';

  @override
  String get viewerLanguageKo => '한';

  @override
  String get viewerLanguageEn => 'EN';

  @override
  String get viewerTabWord => 'Words';

  @override
  String get viewerTabQuestion => 'Questions';

  @override
  String get viewerTabQuiz => 'Quiz';

  @override
  String get viewerNoVocab => 'There\'s no word study on this page';

  @override
  String get viewerNoComprehension =>
      'There are no comprehension questions on this page';

  @override
  String get viewerNoQuiz => 'There\'s no quiz on this page';

  @override
  String viewerComprehensionQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String viewerComprehensionAnswer(Object answer) {
    return 'A. $answer';
  }

  @override
  String get viewerShowAnswer => 'Show answer';

  @override
  String viewerQuizQuestion(Object index, Object question) {
    return 'Q$index. $question';
  }

  @override
  String get viewerCheckAnswer => 'Check answer';

  @override
  String get viewerQuizCorrect => 'Correct!';

  @override
  String get viewerQuizIncorrect => 'Think again';

  @override
  String get viewerGuideSummaryTitle => 'Story summary';

  @override
  String get viewerGuideDiscussionTitle => 'Talk together';

  @override
  String get viewerGuideActivitiesTitle => 'Try together';

  @override
  String get navShellHome => 'Home';

  @override
  String get navShellCreate => 'Create';

  @override
  String get navShellLibrary => 'Library';

  @override
  String get navShellCharacters => 'Characters';

  @override
  String get creditShortageTitle => 'You\'re out of credits';

  @override
  String get creditShortageMessage =>
      'Top up your credits using the options below to keep making storybooks.';

  @override
  String get creditShortageFreeTitle => 'Get free credits';

  @override
  String get creditShortageFreeSubtitle =>
      'Free credits by watching an ad or inviting friends';

  @override
  String get creditShortageSubscribeTitle => 'Subscribe';

  @override
  String get creditShortageSubscribeSubtitle =>
      'Use plenty with a monthly subscription';

  @override
  String get creditShortagePurchaseTitle => 'Buy credits';

  @override
  String get creditShortagePurchaseSubtitle =>
      'Top up exactly as much as you need';

  @override
  String get creditShortageClose => 'Close';

  @override
  String vocabGameQuestion(Object word) {
    return 'What does \"$word\" mean?';
  }

  @override
  String get vocabGameCorrectFeedback => 'Well done! ⭐';

  @override
  String vocabGameIncorrectFeedback(Object meaning) {
    return 'Let\'s remember it again: $meaning';
  }

  @override
  String vocabGameChoiceLabel(Object choice) {
    return 'Choice: $choice';
  }

  @override
  String get characterSourceTitle => 'Make your child the hero';

  @override
  String get characterSourceSubtitle =>
      'Create from a photo or pick a default character';

  @override
  String get characterSourcePhotoCamera => 'Take a photo';

  @override
  String get characterSourceGallery => 'Gallery';

  @override
  String get characterSourcePresetSectionLabel =>
      'Start without a photo · Default characters';

  @override
  String get characterSourcePresetLoadError =>
      'Couldn\'t load the default characters.';

  @override
  String get characterSourceCreateFailed =>
      'Couldn\'t create the hero. Please try again in a moment.';

  @override
  String get characterSourcePhotoMissingId =>
      'Couldn\'t create the hero from the photo. Please try again in a moment.';

  @override
  String get characterSourcePhotoFailed =>
      'Couldn\'t create the hero from the photo. Please check guardian consent and permissions.';

  @override
  String get ageGateTitle => 'Parent verification';

  @override
  String get ageGateDescription =>
      'Parent verification is required before accessing the purchase screen.';

  @override
  String get ageGateAnswerHint => 'Enter the correct answer';

  @override
  String get ageGateCancel => 'Cancel';

  @override
  String get ageGateWrongAnswer => 'That\'s not the correct answer.';

  @override
  String get ageGateConfirm => 'Confirm';
}
