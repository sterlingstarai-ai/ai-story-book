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
}
