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
      'Pick a theme and create your first illustrated storybook.';

  @override
  String get onboardingFirstBookTrialSubtitle =>
      'New accounts get one illustrated storybook free.';

  @override
  String get creditsFirstBookTrial => 'First storybook free for new accounts';

  @override
  String get planFeaturesFreeTrial =>
      'Watercolor and cartoon illustrations|Korean narration for ages 3–5 stories';

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
  String get homePhotoCharacterTitle => 'Make a story with my child';

  @override
  String get homePhotoCharacterSubtitle =>
      'A hero who looks just like them — photos are handled safely';

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
  String get createAgeHelp3to5 =>
      'Usually 3 short sentences, with simple words, sounds and movement';

  @override
  String get createAgeHelp5to7 =>
      'Usually 3–4 sentences, with reasons and short dialogue';

  @override
  String get createAgeHelp7to9 =>
      'Usually 4–6 sentences, with clues and choices that shape the story';

  @override
  String get createAgeHelpAdult =>
      'More layered storytelling and subtle emotions';

  @override
  String get createNarrationPreviewTitle => 'Preview three narration styles';

  @override
  String get createNarrationPreviewSampleLanguage =>
      'The samples are in Korean.';

  @override
  String get createAgePreviewTitle => 'Preview by age';

  @override
  String get createAgePreviewHide => 'Hide the preview';

  @override
  String get createAgePreviewCaption =>
      'The same scene, with a sample of the style and length';

  @override
  String get createAgePreview3to5 =>
      'Flutter, flutter! A blue ribbon danced behind the bush. Haru pointed and said, “There’s our kite, Bori! Let’s call our teacher.”';

  @override
  String get createAgePreview5to7 =>
      'A blue ribbon peeked out of the bush when the wind blew. Haru recognized it from the kite they had flown that morning. Bori stepped closer, then stopped at the thorns. “Let’s keep an eye on the kite and call our teacher.”';

  @override
  String get createAgePreview7to9 =>
      'Haru noticed that the same blue ribbon appeared between the branches every time the wind blew. Bori thought someone might have dropped a piece of string, but Haru spotted two knots at the end. They had tied those knots together when the kite’s tail came loose that morning. Bori stopped at the thorny branches. “Keep watching the ribbon while I get our teacher.”';

  @override
  String get createLanguageLabel => 'Story language';

  @override
  String get createLengthLabel => 'Story length';

  @override
  String get createLengthStandard => '12 pages';

  @override
  String get createLengthShort => '8 pages';

  @override
  String get createLengthHint =>
      '12 pages by default. Choose 8 for a shorter read. Cover not included.';

  @override
  String get createTemplateSectionLabel => 'Start from a suggestion';

  @override
  String get createTemplateAnimalLabel => 'Animal friends';

  @override
  String get createTemplateAnimalTopic =>
      'A brave little animal makes new friends in the forest';

  @override
  String get createTemplateFriendshipLabel => 'Friendship';

  @override
  String get createTemplateFriendshipTopic =>
      'Helping a friend and solving a problem together';

  @override
  String get createTemplateFeelingsLabel => 'Big feelings';

  @override
  String get createTemplateFeelingsTopic =>
      'On a scary night, finding the courage to overcome fear';

  @override
  String get createTemplateSpaceLabel => 'Space adventure';

  @override
  String get createTemplateSpaceTopic =>
      'Exploring stars and planets and discovering something amazing';

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
  String get createRelationshipLabel => 'Relationship (optional)';

  @override
  String get createRelationshipFriends => 'Friends';

  @override
  String get createRelationshipSiblings => 'Siblings';

  @override
  String get createRelationshipFamily => 'Family';

  @override
  String get createForbiddenLabel => 'Things to leave out (optional)';

  @override
  String get createForbiddenViolence => 'Violence';

  @override
  String get createForbiddenScary => 'Scary content';

  @override
  String get createForbiddenSad => 'Sad ending';

  @override
  String get createForbiddenRude => 'Rude language';

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
  String get librarySeriesBadge => 'Series';

  @override
  String get librarySeriesAddVolume => 'Add next volume';

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
  String get loadingImageQualityFailed =>
      'We couldn\'t finish the book because some illustrations couldn\'t be verified. Please try again.';

  @override
  String get loadingStepVerifyIllustrations =>
      'Checking that the illustrations match the story';

  @override
  String get loadingStepRepairIllustrations =>
      'Redrawing illustrations that need changes';

  @override
  String get loadingStepRecheckIllustrations =>
      'Checking the updated illustrations';

  @override
  String get viewerImageQualityFailed =>
      'The updated illustration couldn\'t be verified, so the changes weren\'t saved. Your existing book is unchanged.';

  @override
  String get loadingTitle => 'Creating your storybook';

  @override
  String get loadingIllustrationExample => 'Sample illustration';

  @override
  String get loadingCompleted => 'All done!';

  @override
  String get loadingErrorTitle => 'Something went wrong';

  @override
  String get loadingGenericFailure =>
      'We couldn\'t complete this request. Please try again in a moment.';

  @override
  String get loadingUnknownError => 'Unknown error';

  @override
  String get loadingTimeoutMessage =>
      'Generation is taking longer than expected. Please check the status again.';

  @override
  String get errorValidation => 'Please check your input.';

  @override
  String get errorUnauthorized =>
      'This device’s account connection has expired. Use your recovery code in Settings to reconnect.';

  @override
  String get errorForbidden => 'You don\'t have permission for this.';

  @override
  String get errorInternal =>
      'A server error occurred. Please try again in a moment.';

  @override
  String get errorRateLimit =>
      'Too many requests. Please try again in a moment.';

  @override
  String get errorServiceUnavailable =>
      'The server is temporarily unstable. Please try again in a moment.';

  @override
  String get errorTimeout => 'The request timed out. Please try again.';

  @override
  String get errorConnection => 'Please check your internet connection.';

  @override
  String get errorNetwork => 'A network error occurred.';

  @override
  String get errorCancelled => 'The request was cancelled.';

  @override
  String get loadingSafetyBlockedPrefix => 'This input isn\'t safe:';

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
  String get loadingStepLearningAssets => 'Creating learning materials';

  @override
  String get dailyThemeFriendship => 'Friendship';

  @override
  String get dailyTopicFriendship0 => 'Making a new friend';

  @override
  String get dailyTopicFriendship1 => 'Making up with a friend';

  @override
  String get dailyTopicFriendship2 => 'The joy of sharing';

  @override
  String get dailyTopicFriendship3 => 'Helping each other';

  @override
  String get dailyThemeCourage => 'Courage';

  @override
  String get dailyTopicCourage0 => 'Overcoming fear';

  @override
  String get dailyTopicCourage1 => 'A new challenge';

  @override
  String get dailyTopicCourage2 => 'It\'s okay to make mistakes';

  @override
  String get dailyTopicCourage3 => 'Trying something new';

  @override
  String get dailyThemeKindness => 'Kindness';

  @override
  String get dailyTopicKindness0 => 'The power of small kindness';

  @override
  String get dailyTopicKindness1 => 'A friend who needs help';

  @override
  String get dailyTopicKindness2 => 'A grateful heart';

  @override
  String get dailyTopicKindness3 => 'A caring heart';

  @override
  String get dailyThemeFamily => 'Family';

  @override
  String get dailyTopicFamily0 => 'I love mom and dad';

  @override
  String get dailyTopicFamily1 => 'Together with my sibling';

  @override
  String get dailyTopicFamily2 => 'At grandma and grandpa\'s';

  @override
  String get dailyTopicFamily3 => 'A family trip';

  @override
  String get dailyThemeNature => 'Nature';

  @override
  String get dailyTopicNature0 => 'Exploring the forest';

  @override
  String get dailyTopicNature1 => 'A story of the sea';

  @override
  String get dailyTopicNature2 => 'Spring has come';

  @override
  String get dailyTopicNature3 => 'A starry night';

  @override
  String get dailyThemeGrowth => 'Growth';

  @override
  String get dailyTopicGrowth0 => 'I can do it myself';

  @override
  String get dailyTopicGrowth1 => 'Learning something new';

  @override
  String get dailyTopicGrowth2 => 'Try again after failing';

  @override
  String get dailyTopicGrowth3 => 'Toward my dream';

  @override
  String get dailyThemeImagination => 'Imagination';

  @override
  String get dailyTopicImagination0 => 'A magical world';

  @override
  String get dailyTopicImagination1 => 'A land above the clouds';

  @override
  String get dailyTopicImagination2 => 'The animal friends\' school';

  @override
  String get dailyTopicImagination3 => 'The toys\' secret';

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
  String get voiceProfilesUploadAudioButton => 'Choose audio';

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
  String podOrderEstimatedTotal(Object amount, Object currency) {
    return 'Est. $amount $currency';
  }

  @override
  String get podOrderCityLabel => 'City';

  @override
  String get podOrderCityError => 'Please enter a city.';

  @override
  String get podOrderStateLabel => 'State/Province';

  @override
  String get podOrderStateError => 'State is required for US/CA orders.';

  @override
  String get podOrderAddressLine2Label => 'Address line 2 (optional)';

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
  String podOrderPaymentAmount(Object amount, Object currency) {
    return 'Payment amount: $amount $currency';
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
    return 'Reading streak: $current days · Best: $longest days';
  }

  @override
  String parentDashboardLearningSessionLine(Object completed, Object total) {
    return 'Finished $completed of $total reading sessions';
  }

  @override
  String parentDashboardLearningCompletionLine(Object rate) {
    return 'Completion rate $rate%';
  }

  @override
  String get parentDashboardDailyChartTitle => 'Daily reading time';

  @override
  String get settingsBetaInvitationTitle => 'Copy beta participation ID';

  @override
  String get settingsBetaInvitationSubtitle =>
      'Send this ID to the beta organizer to activate your first story trial.';

  @override
  String get settingsBetaInvitationCopied => 'Beta participation ID copied.';

  @override
  String get settingsBetaInvitationUnavailable =>
      'Could not retrieve your beta participation ID.';

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
      'Revoking consent starts deletion of all characters made from photos or drawings on this account, and their related books and images. This cannot be undone. Storage deletion may take longer to complete. Continue?';

  @override
  String get settingsCancel => 'Cancel';

  @override
  String get settingsRevoke => 'Revoke';

  @override
  String get settingsRevokeConsentError =>
      'Failed to process the revocation. Please check your network and try again.';

  @override
  String get consentDeletionUnconfirmed =>
      'Your consent settings have been saved. Removal of related stored files has not yet been confirmed.';

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
  String settingsFinalConfirmPrompt(Object keyword) {
    return 'To proceed with deletion, type \"$keyword\" below.';
  }

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
  String get settingsPoliciesTitle => 'Policies';

  @override
  String get settingsPoliciesSubtitle =>
      'Credit rollover, subscription cancellation and refunds';

  @override
  String get policyCreditRolloverTitle => 'Credit rollover';

  @override
  String get policyCreditRolloverBody =>
      'Unused credits roll over to the next month while your subscription is active.';

  @override
  String get policyBookAccessTitle => 'Books after cancellation';

  @override
  String get policyBookAccessBody =>
      'Even if you cancel, the books you\'ve already made stay readable and downloadable.';

  @override
  String get policyRefundTitle => 'Cancellations and refunds';

  @override
  String get policyRefundBody =>
      'For purchases made through the App Store or Google Play, use the store’s refund process. If book generation fails, the used story credit is restored automatically.';

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
  String get planFree => 'Free';

  @override
  String get planBasic => 'Basic';

  @override
  String get planPremium => 'Premium';

  @override
  String get planFeaturesFree =>
      '2 books each month|Watercolor & cartoon illustrations|Read stories in the app';

  @override
  String get planFeaturesBasic => '5 books / month|All styles|PDF|Basic TTS';

  @override
  String get planFeaturesPremium =>
      '10 books / month|All features|Premium TTS|Priority processing';

  @override
  String get creditsStorePriceNotice => 'Confirm your store price at checkout';

  @override
  String creditsStoreMonthlyPrice(String price) {
    return '$price/month';
  }

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
  String get charactersEmptySubtitle =>
      'Create a story companion with just a name and a few traits.';

  @override
  String get charactersEmptyCreateButton => 'Create a character';

  @override
  String get charactersLoadErrorTitle => 'Couldn\'t load characters';

  @override
  String get charactersRetry => 'Retry';

  @override
  String get charactersFabCreating => 'Creating...';

  @override
  String get charactersFabCreate => 'Create a character';

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
  String get characterDeletionPending =>
      'The character has been removed. Deletion of some stored files is not yet complete.';

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
      'Describe a character or start with a photo or drawing';

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
  String get charactersDetailIdentityLock =>
      '🔒 Locked features (kept consistent)';

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
  String get viewerRetellTitle => 'Retell at another age';

  @override
  String get viewerRetellSubtitle =>
      'Same pictures, text rewritten for a new age';

  @override
  String get viewerRetellInProgress => 'Retelling for the new age…';

  @override
  String get viewerRetellFailed => 'Couldn\'t retell this book';

  @override
  String get viewerMilestoneRewardEarned => 'You earned bonus credits!';

  @override
  String get viewerMilestoneConfirm => 'Awesome!';

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
      'Dark reading background with continuous narration';

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
  String get viewerRegenerateRegion => 'Fix just this part';

  @override
  String get inpaintTitle => 'Fix a region';

  @override
  String get inpaintInstructions =>
      'Paint the area to fix, then describe the change.';

  @override
  String get inpaintRegionPromptLabel => 'What should change?';

  @override
  String get inpaintRegionPromptHint => 'e.g. make the sky a sunset';

  @override
  String get inpaintReset => 'Clear';

  @override
  String get inpaintApply => 'Apply';

  @override
  String get inpaintNeedRegionAndPrompt =>
      'Paint a region and describe the change.';

  @override
  String get inpaintFailed => 'Couldn\'t fix that region.';

  @override
  String get inpaintApplyingRefreshLater =>
      'Applying your change. Please refresh in a moment.';

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
  String get viewerRegenerateFeedbackTitle => 'How should we change it?';

  @override
  String get viewerRegenerateFeedbackHint => 'e.g. Make it shorter and simpler';

  @override
  String get viewerRegenerateFeedbackRequired =>
      'Tell us what you\'d like changed';

  @override
  String get viewerRegenerateConfirm => 'Regenerate';

  @override
  String get viewerRegenerateCompleted => 'This page has been remade.';

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
    Object title,
    Object deepLink,
    Object fallbackUrl,
  ) {
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
      'A parent or guardian needs to complete this check before continuing.';

  @override
  String get ageGateAnswerHint => 'Enter the correct answer';

  @override
  String get ageGateCancel => 'Cancel';

  @override
  String get ageGateWrongAnswer => 'That\'s not the correct answer.';

  @override
  String get ageGateConfirm => 'Confirm';

  @override
  String get consentTitle => 'Parental Consent';

  @override
  String get consentSubtitle =>
      'To protect children, a parent\'s consent is required for the items below.';

  @override
  String get consentAgreeAll => 'Agree to all';

  @override
  String get consentAgreeAllSubtitle => 'I agree to all of the items below.';

  @override
  String get consentPrivacyRequired =>
      'Consent to the collection and use of personal information (required)';

  @override
  String get consentPhotoOptionalTitle =>
      'Make my child the hero with a photo (optional)';

  @override
  String get consentPhotoDisclosure =>
      '· Recipient: external AI processing providers · Item: the selected photo or drawing · Purpose: storybook character creation · Retention: when you approve the character, we request deletion of the original from service storage. An unapproved original becomes eligible for deletion after 24 hours. The character and related books and images are kept to provide the feature. · Deletion: if you withdraw consent or request deletion, we start deleting the related data. Storage failures can delay completion; we retry. See the privacy policy for external providers\' processing and retention conditions. · Right to refuse: consent is optional and non-photo features remain available.';

  @override
  String get photoConsentAgree => 'Agree';

  @override
  String get photoConsentCancel => 'Cancel';

  @override
  String get photoConsentLoadFailed =>
      'Couldn\'t load your consent info. Please try again in a moment.';

  @override
  String get consentDataProcessingRequired =>
      'Consent to the data processing and storage policy (required)';

  @override
  String get consentAcceptButton => 'Agree and start';

  @override
  String get consentRejectButton => 'Don\'t agree';

  @override
  String get consentRejectDialogTitle => 'Consent required';

  @override
  String get consentRejectDialogContent =>
      'Under our child-protection policy, the app cannot be used without parental consent.';

  @override
  String get consentRejectDialogOk => 'OK';

  @override
  String get consentSaveError =>
      'Failed to save consent. Check your network and try again.';

  @override
  String get themeLunarNewYear => 'Lunar New Year';

  @override
  String get themeChuseok => 'Chuseok';

  @override
  String get themeChildrensDay => 'Children\'s Day';

  @override
  String get themeChristmas => 'Christmas';

  @override
  String get themeDailyHabits => 'Daily Habits';

  @override
  String get themeEmotionalCoaching => 'Emotional Coaching';

  @override
  String get themeSocial => 'Social Skills';

  @override
  String get themeFriendship => 'Friendship';

  @override
  String get themeFamily => 'Family';

  @override
  String get themeAdventure => 'Adventure';

  @override
  String get themeNature => 'Nature';

  @override
  String get themeScience => 'Science';

  @override
  String get themeTimeTravel => 'Time Travel';

  @override
  String get themeAnimal => 'Animals';

  @override
  String get themeDinosaur => 'Dinosaurs';

  @override
  String get themeOccupation => 'Jobs';

  @override
  String get themeFictionWorld => 'Into the Story';

  @override
  String get viewerShareRevoke => 'Revoke shared link';

  @override
  String get viewerShareRevokeDone => 'The shared link has been revoked.';

  @override
  String get viewerShareRevokeFailed => 'Failed to revoke. Please try again.';

  @override
  String get viewerShareParentRequired =>
      'Parent verification is required to share.';

  @override
  String get lockExtendDone => 'Screen time extended by 10 minutes.';

  @override
  String get lockTitle => 'You\'ve reached today\'s screen-time limit';

  @override
  String get lockSubtitle => 'A parent can extend it by 10 minutes.';

  @override
  String get lockExtendButton => 'Verify parent & extend 10 min';

  @override
  String lockUsage(int used, int limit) {
    return 'Used $used min today / limit $limit min';
  }

  @override
  String growthShareText(
    int booksRead,
    int levelNumber,
    String levelLabel,
    int scoreValue,
    int vocabLearned,
    int currentStreak,
  ) {
    return '📚 Reading Growth Report\n\n📖 Books read: $booksRead\n⭐ Reading level: Lv.$levelNumber ($levelLabel)\n📊 Overall score: $scoreValue/100\n🔤 Words learned: $vocabLearned\n🔥 Reading streak: $currentStreak days\n\nGrowing reading one AI storybook at a time 📖';
  }

  @override
  String get growthCtaTitle => 'Show off their growth and keep it going';

  @override
  String get growthCtaSubtitle =>
      'One book a day builds your child\'s reading growth.';

  @override
  String get growthShareSemantic => 'Share your child\'s reading growth';

  @override
  String get growthShareButton => 'Share growth';

  @override
  String get growthCreateSemantic => 'Create a new storybook';

  @override
  String get growthCreateButton => 'New book';

  @override
  String get growthConfidenceHigh => 'High confidence';

  @override
  String get growthConfidenceMedium => 'Medium confidence';

  @override
  String get growthConfidenceLow => 'More reading improves accuracy';

  @override
  String growthHeroSemantic(
    int levelNumber,
    String levelLabel,
    int scoreValue,
    String confidence,
  ) {
    return 'Estimated reading level $levelNumber, $levelLabel. Overall score from books read, vocabulary, accuracy, and completion: $scoreValue out of 100. Confidence: $confidence.';
  }

  @override
  String growthScoreSummary(int scoreValue) {
    return 'Estimated score from books read, vocabulary, accuracy, and completion: $scoreValue/100';
  }

  @override
  String growthBooksValue(int count) {
    return '$count books';
  }

  @override
  String growthDaysValue(int count) {
    return '$count days';
  }

  @override
  String growthLongestStreak(int count) {
    return 'Longest $count days';
  }

  @override
  String growthWordsValue(int count) {
    return '$count words';
  }

  @override
  String get growthWeeklyTitle => 'Your child\'s growth (weekly)';

  @override
  String growthWeekSingle(int count) {
    return 'This week: $count books';
  }

  @override
  String growthWeekDeltaUp(int last, int delta) {
    return 'This week: $last books · $delta more than last week 👏';
  }

  @override
  String growthWeekDeltaDown(int last, int delta) {
    return 'This week: $last books · $delta fewer than last week';
  }

  @override
  String growthWeekDeltaSame(int last) {
    return 'This week: $last books · same as last week';
  }

  @override
  String get growthWeekThis => 'This';

  @override
  String growthWeekN(int week) {
    return 'Wk $week';
  }

  @override
  String get growthLeagueMaster => 'Master League';

  @override
  String get growthLeagueChallenge => 'Challenger League';

  @override
  String get growthLeagueGrowth => 'Growth League';

  @override
  String get growthEncourageTop => 'Top among peers! Doing really well 🎉';

  @override
  String get growthEncourageAhead => 'Ahead of their peers 👍';

  @override
  String get growthEncourageOnPar => 'Reading well, on par with peers';

  @override
  String get growthEncourageGrow =>
      'Reading every day helps them grow. How about a book today? 🌱';

  @override
  String get growthSelfGrowthTitle => 'Your child\'s reading growth';

  @override
  String growthSelfGrowthSummary(int books, int vocab) {
    return '$books books so far · $vocab words learned';
  }

  @override
  String get growthSelfGrowthNote =>
      'At this age, a daily reading habit matters more than rankings. We\'ll show peer comparisons when they\'re older.';

  @override
  String growthPeerSubtitleBaseline(String ageBand) {
    return 'Peer sample is still small, so compared to the $ageBand age benchmark (for reference)';
  }

  @override
  String growthPeerSubtitle(String ageBand, int peerCount) {
    return 'Based on $peerCount peers aged $ageBand · overall reading score';
  }

  @override
  String get growthCompareScoreLabel => 'Overall reading score';

  @override
  String growthScorePoints(int score) {
    return '$score pts';
  }

  @override
  String growthPeerScorePoints(int score) {
    return 'Peers $score pts';
  }

  @override
  String growthPeerBooksValue(String value) {
    return 'Peers $value books';
  }

  @override
  String growthPeerWordsValue(String value) {
    return 'Peers $value words';
  }

  @override
  String growthPeerAccuracyPercent(int percent) {
    return 'Peers $percent%';
  }

  @override
  String get growthPeerTitle => 'Peer comparison';

  @override
  String growthTopPercent(int percent) {
    return 'Top $percent%';
  }

  @override
  String get growthDisclaimer =>
      'Reading scores and levels are estimates based on books read, completion, words learned, and quiz accuracy. They are not a standardized measure and become more accurate the more your child reads.';

  @override
  String get growthLoadError => 'Couldn\'t load the growth report.';

  @override
  String get characterTraitCurious => 'Curious';

  @override
  String get characterTraitLively => 'Lively';

  @override
  String get characterTraitWarm => 'Warm-hearted';

  @override
  String get characterTraitBrave => 'Brave';

  @override
  String get characterTraitFunny => 'Funny';

  @override
  String get characterTraitSmart => 'Smart';

  @override
  String get characterTraitKind => 'Kind';

  @override
  String get characterTraitPlayful => 'Playful';

  @override
  String get characterTraitCalm => 'Calm';

  @override
  String get characterTraitSpirited => 'Spirited';

  @override
  String get notificationBedtimeChannelName => 'Bedtime reminder';

  @override
  String get notificationBedtimeChannelDescription =>
      'Nightly reminder to read today\'s story';

  @override
  String get shareKakaoCardTitle => 'Open the storybook';

  @override
  String get shareKakaoCardDescription =>
      'Check out this storybook made with AI Story Book.';

  @override
  String get homeTodayFallbackTheme => 'Today\'s pick';

  @override
  String get homeTodayFallbackTopic => 'Create today\'s story!';

  @override
  String get growthLevelFallbackLabel => 'Growing';

  @override
  String get growthLevelFirstSteps => 'First steps';

  @override
  String get growthLevelBuildingBasics => 'Building basics';

  @override
  String get growthLevelSteadyGrowth => 'Steady growth';

  @override
  String get growthLevelReadingLeap => 'Reading leap';

  @override
  String get growthLevelFluentReader => 'Fluent reader';

  @override
  String get accountOpening => 'Opening your account';

  @override
  String get accountUnavailableTitle => 'Unable to open your account';

  @override
  String get accountUnavailableMessage =>
      'We could not open your saved account. Unlock your device and retry, or restore it with your recovery code. Keep this app installed while resolving access.';

  @override
  String get accountRetry => 'Try again';

  @override
  String get podOrderingUnavailable =>
      'Physical book ordering is not available in this release.';

  @override
  String get loadingStatusUnavailable =>
      'We could not check your story’s progress. It may still be creating. Check this story’s status again shortly.';

  @override
  String get voiceProfilesUnavailable =>
      'Family voice is unavailable in this release. You can still delete saved voice samples or withdraw consent.';

  @override
  String get loadingStatusUnavailableTitle =>
      'Let\'s check your story\'s progress';

  @override
  String get settingsSavedVoices => 'Manage saved voice samples';

  @override
  String get settingsSavedVoicesSubtitle =>
      'Delete voice data or withdraw consent';

  @override
  String get creditsBetaNotice =>
      'This is a limited free beta. New purchases are unavailable. You can use your existing balance and restore purchases for your current account. Restoring purchases does not recover your story library after changing devices or reinstalling the app.';

  @override
  String get creditBetaLimitTitle =>
      'Check your available features and credits';

  @override
  String get creditBetaLimitMessage =>
      'This feature is unavailable in the free beta, or you have reached your current limit. You can keep reading stories in your library and check your existing balance.';

  @override
  String get creditBetaLibrarySubtitle =>
      'Read the stories you have already made';

  @override
  String get creditBetaStatusSubtitle =>
      'Check your balance and existing purchases';

  @override
  String get libraryDeletionUnconfirmed =>
      'We could not confirm whether the book deletion was processed. Check your connection and try again.';

  @override
  String get libraryDeletionNotStarted =>
      'Book deletion was not started. Check your connection and try again after updating the app and server.';

  @override
  String get libraryDeletionReviewTitle =>
      'A book deletion needs confirmation.';

  @override
  String get libraryDeletionReviewHelp =>
      'Saved data is kept until confirmation. Some older servers cannot confirm automatically.';

  @override
  String get libraryDeletionReviewAction => 'Check again';

  @override
  String get libraryDeletionReviewWaiting =>
      'It is not confirmed yet. Please check again later.';

  @override
  String get libraryDeletionReviewDone =>
      'Confirmed requests were processed. Older saved files still need separate verification.';

  @override
  String get libraryMediaScopeReview =>
      'Your saved book storage needs review. Existing files are preserved; check the account and connection, then try again.';

  @override
  String get libraryDeletionPending =>
      'The book has been removed from your library. Removal of stored files has not yet been confirmed.';

  @override
  String get accountDeletionPending =>
      'Account data and consent have been removed. Some stored files are still being deleted. The server will retry automatically.';

  @override
  String get voiceDeletionPending =>
      'This voice sample can no longer be used. Some stored files are still being deleted. The server will retry automatically.';

  @override
  String get recoveryTitle => 'Account recovery';

  @override
  String get recoveryDescription =>
      'Save a recovery code in a password manager or another safe place before changing or losing this device. Creating a replacement invalidates the previous code.';

  @override
  String get recoveryEnabled => 'Recovery code is enabled';

  @override
  String get recoveryNotEnabled => 'Protect access to your library';

  @override
  String get recoveryCreateCode => 'Create recovery code';

  @override
  String get recoveryReplaceCode => 'Replace recovery code';

  @override
  String get recoverySaveTitle => 'Keep this code safe';

  @override
  String get recoverySaveMessage =>
      'This code can restore your account and library. Anyone with it can take over the account. It is shown only now. Save it outside this app; keep it private.';

  @override
  String get recoveryCopy => 'Copy recovery code';

  @override
  String get recoveryCopied => 'Recovery code copied. Store it safely.';

  @override
  String get recoverySavedCheck => 'I saved the full code outside this app.';

  @override
  String get recoveryConfirmSuffix =>
      'Enter the last 6 characters of the saved code';

  @override
  String get recoveryConfirmSaved => 'Confirm saved code';

  @override
  String get recoveryRestoreTitle => 'Restore an existing account';

  @override
  String get recoveryRestoreMessage =>
      'Enter the recovery code you saved. This device will switch to that account, and its previous device will be signed out. The current and restored libraries are not combined. You will receive a new recovery code.';

  @override
  String get recoveryCodeLabel => 'Recovery code';

  @override
  String get recoveryRestoreButton => 'Restore this account';

  @override
  String get recoveryInvalidCode =>
      'Enter the complete recovery code beginning with ASB-R1-.';

  @override
  String get recoveryFailed =>
      'Recovery could not be confirmed. Check the code, connection, and secure storage, then retry here. If a request was interrupted, keep using this screen so the same device credential can be recovered.';

  @override
  String get recoverySucceeded => 'Your account has been restored';

  @override
  String get recoveryLoadError => 'Could not check recovery status. Try again.';

  @override
  String get recoveryIssueError =>
      'The code could not be displayed. A previous code may have expired. Retry to create and save a new code.';

  @override
  String get recoveryBackupPending =>
      'Save a new recovery code in Settings before losing access to this device.';

  @override
  String get recoveryContinue => 'Continue';

  @override
  String get recoverySwitchNeedsBackup =>
      'Before switching accounts, save a recovery code for the account currently on this device so you can return to its library.';

  @override
  String get reportContentTitle => 'Report a problem';

  @override
  String get reportContentCover => 'Reporting this cover';

  @override
  String reportContentPage(int page) {
    return 'Reporting page $page';
  }

  @override
  String get reportContentHint =>
      'Choose one reason. No name or contact details are needed.';

  @override
  String get reportContentHarmful => 'Violence or dangerous behavior';

  @override
  String get reportContentSexual => 'Sexual content';

  @override
  String get reportContentHate => 'Hate or bullying';

  @override
  String get reportContentPersonal => 'Personal information exposed';

  @override
  String get reportContentImage => 'Problem with the illustration';

  @override
  String get reportContentOther => 'Another content problem';

  @override
  String get reportContentSubmit => 'Send report';

  @override
  String get reportContentSending => 'Sending…';

  @override
  String get reportContentCancel => 'Cancel';

  @override
  String get reportContentClose => 'Back to story';

  @override
  String get reportContentReceived =>
      'Your report has been received for review.';

  @override
  String get reportContentAlreadyReviewed =>
      'This content problem was already reported and reviewed.';

  @override
  String get reportContentFailed =>
      'The report could not be sent. Please try again.';

  @override
  String get homeReadingSubtitle => 'Which story shall we read today?';

  @override
  String get homeReadBook => 'Read story';

  @override
  String get viewerFinishReading => 'Finish reading';

  @override
  String get createAvailableStylesHint =>
      'These illustration styles are available for your account.';

  @override
  String get createOptionsLoading => 'Checking available illustration styles…';

  @override
  String get createOptionsFailed =>
      'We could not check available styles. Check your connection and try again.';

  @override
  String get createSafetyInputHint =>
      'Change the topic to something suitable for children, then try again.';

  @override
  String get createSafetyOutputHint =>
      'We could not safely complete this story. Please choose a different topic.';

  @override
  String get createDailyLimitHint =>
      'You have reached today\'s creation limit. Read a saved story or create another tomorrow.';

  @override
  String get inpaintImageLoadFailed =>
      'The illustration could not load. Reload it to continue editing.';

  @override
  String get voiceProfilesSampleRequiredUpload => 'Upload an audio file first.';

  @override
  String get voiceProfilesSampleSelected => 'Your audio sample is ready.';

  @override
  String get voiceProfilesSampleLinkOption => 'Use an audio link instead';

  @override
  String get parentDashboardEmptyReading =>
      'No reading activity in this period yet. Read a story to start building your record.';

  @override
  String get settingsPagePreparing =>
      'This information page is being prepared.';

  @override
  String get settingsPageOpenError =>
      'We couldn’t open this page. Please try again shortly.';

  @override
  String get characterAvatarTitle => 'Meet your story character';

  @override
  String get characterAvatarGeneratingLabel => 'Creating their look';

  @override
  String get characterAvatarPreviewLabel => 'Ready for your review';

  @override
  String get characterAvatarApprovedLabel => 'Confirmed character';

  @override
  String get characterAvatarFailedLabel => 'Character needs attention';

  @override
  String get characterAvatarGeneratingBody =>
      'We’re creating your story character. You can leave this screen and return from Characters.';

  @override
  String get characterAvatarPreviewBody =>
      'Happy with this look? Once confirmed, this character can be used in future stories.';

  @override
  String get characterAvatarImageLabel => 'Story character preview';

  @override
  String get characterAvatarApprove => 'Use this character';

  @override
  String get characterAvatarRegenerate => 'Try another look';

  @override
  String get characterAvatarOtherPhoto => 'Choose another photo';

  @override
  String get characterAvatarLater => 'Review later';

  @override
  String get characterAvatarTakingLong =>
      'This is taking longer to check. Try again shortly, or return from Characters later.';

  @override
  String get characterAvatarLoadError =>
      'We couldn’t load this character. Please try again.';

  @override
  String get characterAvatarImageError =>
      'We couldn’t load the preview. Please try again.';

  @override
  String get characterAvatarFailedBody =>
      'This character isn’t ready yet. Try another look if available, or choose another photo.';

  @override
  String get characterAvatarRetryLimit =>
      'We can’t create another look from this photo. You can choose a different photo.';

  @override
  String get characterAvatarChanged =>
      'The preview changed. Please review the new look.';

  @override
  String get characterAvatarUpdateError =>
      'We couldn’t confirm your request. Review the latest preview before trying again.';

  @override
  String get characterAvatarUnavailable =>
      'Photo characters are unavailable right now. Choose a preset or try again later.';

  @override
  String get characterAvatarNeedsApproval =>
      'Please confirm your character’s look before creating the story.';

  @override
  String get characterAvatarReferenceUnavailable =>
      'The character image is unavailable. Please check it in Characters.';

  @override
  String get characterSelectionInvalid =>
      'Please check your character selection.';

  @override
  String get characterAvatarHeroLabel => 'Hero of this book';

  @override
  String get characterAvatarApprovedDescription =>
      'This character can join your next story, too.';

  @override
  String get characterAvatarPreparingDescription =>
      'Your story character is being created.';

  @override
  String get characterAvatarFailedDescription =>
      'Try creating again or choose another photo.';

  @override
  String errorMonthlyBookLimit(String limit) {
    return 'The free plan allows $limit books each month. Your limit resets on the first day of next month, Korea time. Remaining credits are kept.';
  }

  @override
  String get errorInsufficientCredits =>
      'You do not have enough credits to create this story.';

  @override
  String get errorPlanFeature =>
      'This feature is not included in your current plan.';

  @override
  String errorRateLimitWait(String seconds) {
    return 'Please wait $seconds seconds before trying again.';
  }

  @override
  String get settingsDeleteUncertain =>
      'We could not confirm the deletion result yet. Retry deletion for this account. If you reopen the app, we will continue checking before opening your library.';

  @override
  String get settingsDeleteLegacyUnresolved =>
      'The server accepted the deletion, but cleanup of data stored on this device could not be confirmed. Data may remain on this device and account access is restricted.';

  @override
  String get legacyCleanupTitle => 'Clear older shared data';

  @override
  String get legacyAccountCleanupTitle => 'Clear this account\'s older media';

  @override
  String get legacyAccountCleanupWarning =>
      'This deletes older images, audio and deletion records for the deleted account on this device. Media from this account\'s other profiles will also be deleted. This cannot be undone. Continue?';

  @override
  String get legacyAccountCleanupAction => 'Clear this account\'s older media';

  @override
  String get legacyCleanupWarning =>
      'This deletes all older shared stories, images, and reading progress on this device. Offline data from other accounts or profiles may also be deleted, and this cannot be undone. Continue?';

  @override
  String get legacyCleanupAction => 'Clear older shared data';

  @override
  String get legacyCleanupCancel => 'Keep data';

  @override
  String get legacyCleanupConfirm => 'Delete all';

  @override
  String get legacyCleanupFailed =>
      'The shared data could not be fully cleared. Check the device and try again.';

  @override
  String get recoveryFinishBackupFirst =>
      'Save the code and complete the backup confirmation below before leaving.';

  @override
  String get charactersRename => 'Rename';

  @override
  String get charactersNameSaved =>
      'Character renamed. The approved appearance is unchanged.';

  @override
  String get charactersManage => 'Manage character';

  @override
  String activeChildLabel(String name) {
    return 'Current child: $name';
  }

  @override
  String get legalReadFull => 'Read full text';

  @override
  String get legalOpenWebsite => 'Open public page';

  @override
  String get legalKoreanOriginal => 'This document is provided in Korean.';

  @override
  String get legalDraftNotice =>
      'Pre-release review copy. The effective date and external processing details will be finalized before publication.';

  @override
  String get consentRequiredOnly => 'Agree to required items';

  @override
  String get consentOptionalSeparate =>
      'Choose photo consent separately below.';

  @override
  String get consentScrollHint => 'Scroll down to read all details.';

  @override
  String get loadingCreditRefunded =>
      'The credits used for this generation have been returned.';

  @override
  String get loadingCreditRefundPending =>
      'Your credits are being returned. Check the status again shortly.';

  @override
  String get loadingCreditNotCharged =>
      'No credits were charged for this generation.';

  @override
  String get errorParentalConsentRequired =>
      'Complete parental consent first. You can review consent in Settings.';

  @override
  String get localMediaCleanupFailed =>
      'We could not confirm removal of cached images on this device. Retry on this screen to continue cleanup.';

  @override
  String get viewerAiNarration => 'AI voice';

  @override
  String get createRequestPending =>
      'Submitting your story request. A delayed response will not cause a duplicate charge.';

  @override
  String get viewerLearningUnavailable =>
      'Learning activities are unavailable for this book. You can still read the complete story.';

  @override
  String get settingsNarratorVoice => 'Narrator voice';

  @override
  String get settingsNarratorVoiceHelp =>
      'AI-generated voice, saved on this device. A new voice may need new audio.';

  @override
  String get settingsNarratorVoiceDefault => 'Default';

  @override
  String get settingsNarratorVoiceWarm => 'Feminine-sounding';

  @override
  String get settingsNarratorVoiceDeep => 'Masculine-sounding';

  @override
  String get settingsNarrationStyle => 'Narration style';

  @override
  String get settingsNarrationStyleHelp =>
      'Saved on this device. A new style may generate new audio.';

  @override
  String get settingsNarrationStyleLegacy => 'Existing narration';

  @override
  String get settingsNarrationStyleNatural => 'Storyteller';

  @override
  String get settingsNarrationStyleAnimated => 'Expressive storytelling';

  @override
  String get settingsNarrationStyleBedtime => 'Bedtime';

  @override
  String get settingsNarrationPreviewHelp =>
      'Hear the same Korean sentence in three styles with the default AI voice. Expressive storytelling varies the delivery of each line.';

  @override
  String get settingsNarrationPreviewGoogleHelp =>
      'Hear the same Korean sentence in three styles with your selected AI voice. Expressive storytelling varies the delivery of each line.';

  @override
  String settingsNarrationPreview(String style) {
    return 'Preview $style';
  }

  @override
  String get settingsNarrationPreviewError => 'Could not play the preview.';
}
