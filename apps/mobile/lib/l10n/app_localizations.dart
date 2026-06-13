import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_ja.dart';
import 'app_localizations_ko.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
      : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('ja'),
    Locale('ko')
  ];

  /// Application title
  ///
  /// In en, this message translates to:
  /// **'AI Story Book'**
  String get appTitle;

  /// Title of the reading growth report screen
  ///
  /// In en, this message translates to:
  /// **'Reading Growth'**
  String get readingGrowthTitle;

  /// Home entry card title to open the growth report
  ///
  /// In en, this message translates to:
  /// **'View reading growth'**
  String get readingGrowthEntryTitle;

  /// Home entry card subtitle
  ///
  /// In en, this message translates to:
  /// **'Watch your child\'s reading skills grow'**
  String get readingGrowthEntrySubtitle;

  /// Label above the estimated reading level
  ///
  /// In en, this message translates to:
  /// **'Your child\'s estimated reading level'**
  String get estimatedReadingLevel;

  /// Stat label: number of books read
  ///
  /// In en, this message translates to:
  /// **'Books read'**
  String get booksReadLabel;

  /// Stat label: current reading streak in days
  ///
  /// In en, this message translates to:
  /// **'Reading streak'**
  String get currentStreakLabel;

  /// Stat label: vocabulary words learned
  ///
  /// In en, this message translates to:
  /// **'Words learned'**
  String get vocabLearnedLabel;

  /// Stat label: quiz accuracy
  ///
  /// In en, this message translates to:
  /// **'Quiz accuracy'**
  String get quizAccuracyLabel;

  /// Generic retry button label
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// Onboarding: skip button
  ///
  /// In en, this message translates to:
  /// **'Skip'**
  String get onboardingSkip;

  /// No description provided for @onboardingNext.
  ///
  /// In en, this message translates to:
  /// **'Next'**
  String get onboardingNext;

  /// No description provided for @onboardingStart.
  ///
  /// In en, this message translates to:
  /// **'Get started'**
  String get onboardingStart;

  /// No description provided for @onboardingSlide1Title.
  ///
  /// In en, this message translates to:
  /// **'AI custom stories'**
  String get onboardingSlide1Title;

  /// No description provided for @onboardingSlide1Subtitle.
  ///
  /// In en, this message translates to:
  /// **'AI creates stories tailored to your child.'**
  String get onboardingSlide1Subtitle;

  /// No description provided for @onboardingSlide2Title.
  ///
  /// In en, this message translates to:
  /// **'Make characters from photos'**
  String get onboardingSlide2Title;

  /// No description provided for @onboardingSlide2Subtitle.
  ///
  /// In en, this message translates to:
  /// **'Turn your child\'s photo into the story\'s hero.'**
  String get onboardingSlide2Subtitle;

  /// No description provided for @onboardingSlide3Title.
  ///
  /// In en, this message translates to:
  /// **'A daily reading habit'**
  String get onboardingSlide3Title;

  /// No description provided for @onboardingSlide3Subtitle.
  ///
  /// In en, this message translates to:
  /// **'Build a daily reading habit with streaks.'**
  String get onboardingSlide3Subtitle;

  /// No description provided for @onboardingSlide4Title.
  ///
  /// In en, this message translates to:
  /// **'Start for free'**
  String get onboardingSlide4Title;

  /// No description provided for @onboardingSlide4Subtitle.
  ///
  /// In en, this message translates to:
  /// **'Make your first storybook with 3 starter credits.'**
  String get onboardingSlide4Subtitle;

  /// Accessibility label for the onboarding page indicator
  ///
  /// In en, this message translates to:
  /// **'Page {current} of {total}'**
  String onboardingPageIndicator(int current, int total);

  /// No description provided for @homeTitle.
  ///
  /// In en, this message translates to:
  /// **'AI Story Book'**
  String get homeTitle;

  /// No description provided for @homeSettingsTooltip.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get homeSettingsTooltip;

  /// No description provided for @homeHeaderSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Create custom storybooks for your child'**
  String get homeHeaderSubtitle;

  /// No description provided for @homeSectionTodayReading.
  ///
  /// In en, this message translates to:
  /// **'Today\'s reading'**
  String get homeSectionTodayReading;

  /// No description provided for @homeSectionForParents.
  ///
  /// In en, this message translates to:
  /// **'For parents'**
  String get homeSectionForParents;

  /// No description provided for @homeRecentBooksTitle.
  ///
  /// In en, this message translates to:
  /// **'Recently created'**
  String get homeRecentBooksTitle;

  /// No description provided for @homeViewAll.
  ///
  /// In en, this message translates to:
  /// **'View all'**
  String get homeViewAll;

  /// No description provided for @homeEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No storybooks yet'**
  String get homeEmptyTitle;

  /// No description provided for @homeEmptySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Create your first storybook!'**
  String get homeEmptySubtitle;

  /// No description provided for @homeLibraryErrorTitle.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load your storybooks'**
  String get homeLibraryErrorTitle;

  /// No description provided for @homeCreateCardTitle.
  ///
  /// In en, this message translates to:
  /// **'Create a new storybook'**
  String get homeCreateCardTitle;

  /// No description provided for @homeCreateCardSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Make a custom storybook\nwith your child as the hero'**
  String get homeCreateCardSubtitle;

  /// No description provided for @homeStreakDaysLabel.
  ///
  /// In en, this message translates to:
  /// **'{days}-day reading streak'**
  String homeStreakDaysLabel(Object days);

  /// No description provided for @homeReadTodayBadge.
  ///
  /// In en, this message translates to:
  /// **'Read today'**
  String get homeReadTodayBadge;

  /// No description provided for @homeNotReadTodayBadge.
  ///
  /// In en, this message translates to:
  /// **'Not done today'**
  String get homeNotReadTodayBadge;

  /// No description provided for @homeStreakSummary.
  ///
  /// In en, this message translates to:
  /// **'Read on {total} days total · Best {longest} days'**
  String homeStreakSummary(Object total, Object longest);

  /// No description provided for @homeRecent7Days.
  ///
  /// In en, this message translates to:
  /// **'Last 7 days'**
  String get homeRecent7Days;

  /// No description provided for @homeTodayStoryLabel.
  ///
  /// In en, this message translates to:
  /// **'Today\'s storybook · {theme}'**
  String homeTodayStoryLabel(Object theme);

  /// No description provided for @homeContinueReading.
  ///
  /// In en, this message translates to:
  /// **'Continue reading'**
  String get homeContinueReading;

  /// No description provided for @homeMakeTodayStory.
  ///
  /// In en, this message translates to:
  /// **'Make today\'s storybook'**
  String get homeMakeTodayStory;

  /// No description provided for @homeStreakLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading streak info...'**
  String get homeStreakLoading;

  /// No description provided for @homeStreakErrorTitle.
  ///
  /// In en, this message translates to:
  /// **'Streak card error'**
  String get homeStreakErrorTitle;

  /// No description provided for @homeStreakLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load streak info.'**
  String get homeStreakLoadError;

  /// No description provided for @homeGrowthEntryTitle.
  ///
  /// In en, this message translates to:
  /// **'View reading growth'**
  String get homeGrowthEntryTitle;

  /// No description provided for @homeGrowthSubtitleStats.
  ///
  /// In en, this message translates to:
  /// **'{vocab} words learned · {accuracy}% accuracy'**
  String homeGrowthSubtitleStats(Object vocab, Object accuracy);

  /// No description provided for @homeWeekdayMon.
  ///
  /// In en, this message translates to:
  /// **'Mon'**
  String get homeWeekdayMon;

  /// No description provided for @homeWeekdayTue.
  ///
  /// In en, this message translates to:
  /// **'Tue'**
  String get homeWeekdayTue;

  /// No description provided for @homeWeekdayWed.
  ///
  /// In en, this message translates to:
  /// **'Wed'**
  String get homeWeekdayWed;

  /// No description provided for @homeWeekdayThu.
  ///
  /// In en, this message translates to:
  /// **'Thu'**
  String get homeWeekdayThu;

  /// No description provided for @homeWeekdayFri.
  ///
  /// In en, this message translates to:
  /// **'Fri'**
  String get homeWeekdayFri;

  /// No description provided for @homeWeekdaySat.
  ///
  /// In en, this message translates to:
  /// **'Sat'**
  String get homeWeekdaySat;

  /// No description provided for @homeWeekdaySun.
  ///
  /// In en, this message translates to:
  /// **'Sun'**
  String get homeWeekdaySun;

  /// No description provided for @homeWeekdayUnknown.
  ///
  /// In en, this message translates to:
  /// **'-'**
  String get homeWeekdayUnknown;

  /// No description provided for @createTitle.
  ///
  /// In en, this message translates to:
  /// **'Create a New Storybook'**
  String get createTitle;

  /// No description provided for @createCloseTooltip.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get createCloseTooltip;

  /// No description provided for @createTopicLabel.
  ///
  /// In en, this message translates to:
  /// **'What kind of story shall we make?'**
  String get createTopicLabel;

  /// No description provided for @createTopicHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. A story about a rabbit flying in the sky'**
  String get createTopicHint;

  /// No description provided for @createTopicRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter a story topic'**
  String get createTopicRequired;

  /// No description provided for @createTopicTooShort.
  ///
  /// In en, this message translates to:
  /// **'Please add a little more detail'**
  String get createTopicTooShort;

  /// No description provided for @createChildNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Your child\'s name (optional)'**
  String get createChildNameLabel;

  /// No description provided for @createChildNameHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. Minji'**
  String get createChildNameHint;

  /// No description provided for @createAgeLabel.
  ///
  /// In en, this message translates to:
  /// **'Child\'s age group'**
  String get createAgeLabel;

  /// No description provided for @createStyleLabel.
  ///
  /// In en, this message translates to:
  /// **'Art style'**
  String get createStyleLabel;

  /// No description provided for @createThemeLabel.
  ///
  /// In en, this message translates to:
  /// **'Theme (optional)'**
  String get createThemeLabel;

  /// No description provided for @createThemeNone.
  ///
  /// In en, this message translates to:
  /// **'None'**
  String get createThemeNone;

  /// No description provided for @createCharacterLabel.
  ///
  /// In en, this message translates to:
  /// **'Main character'**
  String get createCharacterLabel;

  /// No description provided for @createAddCharacter.
  ///
  /// In en, this message translates to:
  /// **'Add character'**
  String get createAddCharacter;

  /// No description provided for @createCharacterHint.
  ///
  /// In en, this message translates to:
  /// **'Pick an existing character, or let AI create a new one'**
  String get createCharacterHint;

  /// No description provided for @createAiCharacterTitle.
  ///
  /// In en, this message translates to:
  /// **'AI creates a new character'**
  String get createAiCharacterTitle;

  /// No description provided for @createAiCharacterDesc.
  ///
  /// In en, this message translates to:
  /// **'Automatically creates a character that fits the story'**
  String get createAiCharacterDesc;

  /// No description provided for @createChildProtagonistTitle.
  ///
  /// In en, this message translates to:
  /// **'Make your child the main character'**
  String get createChildProtagonistTitle;

  /// No description provided for @createChildProtagonistDesc.
  ///
  /// In en, this message translates to:
  /// **'Create the main character from a photo or a default character'**
  String get createChildProtagonistDesc;

  /// No description provided for @createOrSelectExisting.
  ///
  /// In en, this message translates to:
  /// **'Or choose an existing character'**
  String get createOrSelectExisting;

  /// No description provided for @createSelectedCount.
  ///
  /// In en, this message translates to:
  /// **'{count} selected (family/friend stories possible)'**
  String createSelectedCount(Object count);

  /// No description provided for @createAddCharacterTip.
  ///
  /// In en, this message translates to:
  /// **'Add a character to make a series with the same character!'**
  String get createAddCharacterTip;

  /// No description provided for @createCharacterLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load characters'**
  String get createCharacterLoadError;

  /// No description provided for @createMakeButton.
  ///
  /// In en, this message translates to:
  /// **'Make Storybook'**
  String get createMakeButton;

  /// No description provided for @createPlanUpgradeTitle.
  ///
  /// In en, this message translates to:
  /// **'A plan upgrade is needed'**
  String get createPlanUpgradeTitle;

  /// No description provided for @createCreditShortageTitle.
  ///
  /// In en, this message translates to:
  /// **'Not enough credits'**
  String get createCreditShortageTitle;

  /// No description provided for @createFailedSnack.
  ///
  /// In en, this message translates to:
  /// **'Failed to create the storybook. Please try again in a moment.'**
  String get createFailedSnack;

  /// No description provided for @libraryTitle.
  ///
  /// In en, this message translates to:
  /// **'My Library'**
  String get libraryTitle;

  /// No description provided for @libraryRefresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get libraryRefresh;

  /// No description provided for @librarySortNewest.
  ///
  /// In en, this message translates to:
  /// **'Newest'**
  String get librarySortNewest;

  /// No description provided for @librarySortOldest.
  ///
  /// In en, this message translates to:
  /// **'Oldest'**
  String get librarySortOldest;

  /// No description provided for @librarySortTitle.
  ///
  /// In en, this message translates to:
  /// **'By title'**
  String get librarySortTitle;

  /// No description provided for @libraryStyleWatercolor.
  ///
  /// In en, this message translates to:
  /// **'Watercolor'**
  String get libraryStyleWatercolor;

  /// No description provided for @libraryStyleCartoon.
  ///
  /// In en, this message translates to:
  /// **'Cartoon'**
  String get libraryStyleCartoon;

  /// No description provided for @libraryStyle3d.
  ///
  /// In en, this message translates to:
  /// **'3D'**
  String get libraryStyle3d;

  /// No description provided for @libraryStylePixel.
  ///
  /// In en, this message translates to:
  /// **'Pixel'**
  String get libraryStylePixel;

  /// No description provided for @libraryStyleOilPainting.
  ///
  /// In en, this message translates to:
  /// **'Oil painting'**
  String get libraryStyleOilPainting;

  /// No description provided for @libraryStyleClaymation.
  ///
  /// In en, this message translates to:
  /// **'Claymation'**
  String get libraryStyleClaymation;

  /// No description provided for @libraryStyleRealistic.
  ///
  /// In en, this message translates to:
  /// **'Realistic'**
  String get libraryStyleRealistic;

  /// No description provided for @libraryAge3to5.
  ///
  /// In en, this message translates to:
  /// **'Ages 3-5'**
  String get libraryAge3to5;

  /// No description provided for @libraryAge5to7.
  ///
  /// In en, this message translates to:
  /// **'Ages 5-7'**
  String get libraryAge5to7;

  /// No description provided for @libraryAge7to9.
  ///
  /// In en, this message translates to:
  /// **'Ages 7-9'**
  String get libraryAge7to9;

  /// No description provided for @libraryAgeAdult.
  ///
  /// In en, this message translates to:
  /// **'Adult'**
  String get libraryAgeAdult;

  /// No description provided for @libraryRenameDialogTitle.
  ///
  /// In en, this message translates to:
  /// **'Rename storybook'**
  String get libraryRenameDialogTitle;

  /// No description provided for @libraryRenameFieldLabel.
  ///
  /// In en, this message translates to:
  /// **'Title'**
  String get libraryRenameFieldLabel;

  /// No description provided for @libraryRenameFieldHint.
  ///
  /// In en, this message translates to:
  /// **'Please enter the storybook title'**
  String get libraryRenameFieldHint;

  /// No description provided for @libraryCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get libraryCancel;

  /// No description provided for @librarySave.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get librarySave;

  /// No description provided for @libraryRenameSuccess.
  ///
  /// In en, this message translates to:
  /// **'The storybook name has been updated.'**
  String get libraryRenameSuccess;

  /// No description provided for @libraryDeleteDialogTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete storybook'**
  String get libraryDeleteDialogTitle;

  /// No description provided for @libraryDeleteDialogContent.
  ///
  /// In en, this message translates to:
  /// **'Delete \"{title}\"?\nDeleted storybooks cannot be recovered.'**
  String libraryDeleteDialogContent(Object title);

  /// No description provided for @libraryDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get libraryDelete;

  /// No description provided for @libraryDeleteSuccess.
  ///
  /// In en, this message translates to:
  /// **'The storybook has been deleted.'**
  String get libraryDeleteSuccess;

  /// No description provided for @libraryErrorNetwork.
  ///
  /// In en, this message translates to:
  /// **'Please check your internet connection and try again.'**
  String get libraryErrorNetwork;

  /// No description provided for @libraryErrorGeneric.
  ///
  /// In en, this message translates to:
  /// **'An error occurred while processing your request. Please try again in a moment.'**
  String get libraryErrorGeneric;

  /// No description provided for @libraryShareMessage.
  ///
  /// In en, this message translates to:
  /// **'📚 {title}\n\nThis is a storybook made with AI Story Book.\nShare a special story with your child!'**
  String libraryShareMessage(Object title);

  /// No description provided for @libraryShareFailed.
  ///
  /// In en, this message translates to:
  /// **'Sharing failed. Please try again in a moment.'**
  String get libraryShareFailed;

  /// No description provided for @librarySortLabel.
  ///
  /// In en, this message translates to:
  /// **'Sort'**
  String get librarySortLabel;

  /// No description provided for @libraryStyleLabel.
  ///
  /// In en, this message translates to:
  /// **'Style'**
  String get libraryStyleLabel;

  /// No description provided for @libraryAgeLabel.
  ///
  /// In en, this message translates to:
  /// **'Age'**
  String get libraryAgeLabel;

  /// No description provided for @libraryFilterAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get libraryFilterAll;

  /// No description provided for @libraryResetFilters.
  ///
  /// In en, this message translates to:
  /// **'Reset filters'**
  String get libraryResetFilters;

  /// No description provided for @libraryEmptyFilterTitle.
  ///
  /// In en, this message translates to:
  /// **'No storybooks match your filters'**
  String get libraryEmptyFilterTitle;

  /// No description provided for @libraryEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'You haven\'t made any storybooks yet'**
  String get libraryEmptyTitle;

  /// No description provided for @libraryEmptyFilterSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Clear the filters to view your full library.'**
  String get libraryEmptyFilterSubtitle;

  /// No description provided for @libraryEmptySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Make your first storybook!'**
  String get libraryEmptySubtitle;

  /// No description provided for @libraryCreateNew.
  ///
  /// In en, this message translates to:
  /// **'Make a new storybook'**
  String get libraryCreateNew;

  /// No description provided for @libraryLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load your library'**
  String get libraryLoadError;

  /// No description provided for @libraryRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get libraryRetry;

  /// No description provided for @libraryDateToday.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get libraryDateToday;

  /// No description provided for @libraryDateYesterday.
  ///
  /// In en, this message translates to:
  /// **'Yesterday'**
  String get libraryDateYesterday;

  /// No description provided for @libraryDateDaysAgo.
  ///
  /// In en, this message translates to:
  /// **'{days} days ago'**
  String libraryDateDaysAgo(Object days);

  /// No description provided for @libraryDateMonthDay.
  ///
  /// In en, this message translates to:
  /// **'{month}/{day}'**
  String libraryDateMonthDay(Object month, Object day);

  /// No description provided for @libraryClose.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get libraryClose;

  /// No description provided for @libraryOfflineBanner.
  ///
  /// In en, this message translates to:
  /// **'You\'re offline. Showing recently loaded storybooks.'**
  String get libraryOfflineBanner;

  /// No description provided for @libraryBookOptions.
  ///
  /// In en, this message translates to:
  /// **'Storybook options'**
  String get libraryBookOptions;

  /// No description provided for @libraryMenuRename.
  ///
  /// In en, this message translates to:
  /// **'Rename'**
  String get libraryMenuRename;

  /// No description provided for @libraryMenuShare.
  ///
  /// In en, this message translates to:
  /// **'Share'**
  String get libraryMenuShare;

  /// No description provided for @libraryMenuDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get libraryMenuDelete;

  /// No description provided for @loadingTitle.
  ///
  /// In en, this message translates to:
  /// **'Creating your storybook'**
  String get loadingTitle;

  /// No description provided for @loadingCompleted.
  ///
  /// In en, this message translates to:
  /// **'All done!'**
  String get loadingCompleted;

  /// No description provided for @loadingErrorTitle.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong'**
  String get loadingErrorTitle;

  /// No description provided for @loadingUnknownError.
  ///
  /// In en, this message translates to:
  /// **'Unknown error'**
  String get loadingUnknownError;

  /// No description provided for @loadingRetryButton.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get loadingRetryButton;

  /// No description provided for @loadingCheckStatusButton.
  ///
  /// In en, this message translates to:
  /// **'Check status again'**
  String get loadingCheckStatusButton;

  /// No description provided for @loadingBackToHomeButton.
  ///
  /// In en, this message translates to:
  /// **'Back to home'**
  String get loadingBackToHomeButton;

  /// No description provided for @loadingStepWaiting.
  ///
  /// In en, this message translates to:
  /// **'Waiting...'**
  String get loadingStepWaiting;

  /// No description provided for @loadingStepPreparing.
  ///
  /// In en, this message translates to:
  /// **'Preparing...'**
  String get loadingStepPreparing;

  /// No description provided for @loadingStepNormalize.
  ///
  /// In en, this message translates to:
  /// **'Analyzing your input'**
  String get loadingStepNormalize;

  /// No description provided for @loadingStepModerateInput.
  ///
  /// In en, this message translates to:
  /// **'Checking safety'**
  String get loadingStepModerateInput;

  /// No description provided for @loadingStepGenerateStory.
  ///
  /// In en, this message translates to:
  /// **'Writing the story'**
  String get loadingStepGenerateStory;

  /// No description provided for @loadingStepGenerateCharacterSheet.
  ///
  /// In en, this message translates to:
  /// **'Designing the character'**
  String get loadingStepGenerateCharacterSheet;

  /// No description provided for @loadingStepGenerateImagePrompts.
  ///
  /// In en, this message translates to:
  /// **'Preparing the illustrations'**
  String get loadingStepGenerateImagePrompts;

  /// No description provided for @loadingStepGenerateImages.
  ///
  /// In en, this message translates to:
  /// **'Drawing the illustrations'**
  String get loadingStepGenerateImages;

  /// No description provided for @loadingStepModerateOutput.
  ///
  /// In en, this message translates to:
  /// **'Running the final check'**
  String get loadingStepModerateOutput;

  /// No description provided for @loadingStepPackage.
  ///
  /// In en, this message translates to:
  /// **'Wrapping things up'**
  String get loadingStepPackage;

  /// No description provided for @loadingTip1.
  ///
  /// In en, this message translates to:
  /// **'The story is written with words and sentences suited to your child'**
  String get loadingTip1;

  /// No description provided for @loadingTip2.
  ///
  /// In en, this message translates to:
  /// **'The AI takes care to keep the character consistent'**
  String get loadingTip2;

  /// No description provided for @loadingTip3.
  ///
  /// In en, this message translates to:
  /// **'You can revisit finished storybooks anytime in your library'**
  String get loadingTip3;

  /// No description provided for @loadingTip4.
  ///
  /// In en, this message translates to:
  /// **'You can regenerate any page you don\'t like later'**
  String get loadingTip4;

  /// No description provided for @loadingTip5.
  ///
  /// In en, this message translates to:
  /// **'You can also make a series of storybooks with the same character'**
  String get loadingTip5;

  /// No description provided for @profilesTitle.
  ///
  /// In en, this message translates to:
  /// **'Child Profiles'**
  String get profilesTitle;

  /// No description provided for @profilesAddTooltip.
  ///
  /// In en, this message translates to:
  /// **'Add profile'**
  String get profilesAddTooltip;

  /// No description provided for @profilesLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load profile information.'**
  String get profilesLoadError;

  /// No description provided for @profilesDialogAddTitle.
  ///
  /// In en, this message translates to:
  /// **'Add Profile'**
  String get profilesDialogAddTitle;

  /// No description provided for @profilesDialogEditTitle.
  ///
  /// In en, this message translates to:
  /// **'Edit Profile'**
  String get profilesDialogEditTitle;

  /// No description provided for @profilesNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Name'**
  String get profilesNameLabel;

  /// No description provided for @profilesNameHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. Minji'**
  String get profilesNameHint;

  /// No description provided for @profilesNameRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter a name.'**
  String get profilesNameRequired;

  /// No description provided for @profilesBirthYearLabel.
  ///
  /// In en, this message translates to:
  /// **'Birth year (optional)'**
  String get profilesBirthYearLabel;

  /// No description provided for @profilesBirthMonthLabel.
  ///
  /// In en, this message translates to:
  /// **'Month'**
  String get profilesBirthMonthLabel;

  /// No description provided for @profilesYearOption.
  ///
  /// In en, this message translates to:
  /// **'{year}'**
  String profilesYearOption(Object year);

  /// No description provided for @profilesMonthOption.
  ///
  /// In en, this message translates to:
  /// **'{month}'**
  String profilesMonthOption(Object month);

  /// No description provided for @profilesAgeBandAuto.
  ///
  /// In en, this message translates to:
  /// **'Age band auto: {band} yrs'**
  String profilesAgeBandAuto(Object band);

  /// No description provided for @profilesBirthHint.
  ///
  /// In en, this message translates to:
  /// **'Enter the birth year and month to set the age band automatically (optional).'**
  String get profilesBirthHint;

  /// No description provided for @profilesAgeBandLabel.
  ///
  /// In en, this message translates to:
  /// **'Age band'**
  String get profilesAgeBandLabel;

  /// No description provided for @profilesAgeBand35.
  ///
  /// In en, this message translates to:
  /// **'Ages 3-5'**
  String get profilesAgeBand35;

  /// No description provided for @profilesAgeBand57.
  ///
  /// In en, this message translates to:
  /// **'Ages 5-7'**
  String get profilesAgeBand57;

  /// No description provided for @profilesAgeBand79.
  ///
  /// In en, this message translates to:
  /// **'Ages 7-9'**
  String get profilesAgeBand79;

  /// No description provided for @profilesAgeBandAdult.
  ///
  /// In en, this message translates to:
  /// **'Adult'**
  String get profilesAgeBandAdult;

  /// No description provided for @profilesAgeBandValue.
  ///
  /// In en, this message translates to:
  /// **'Age band: {label}'**
  String profilesAgeBandValue(Object label);

  /// No description provided for @profilesSetAsDefaultSwitch.
  ///
  /// In en, this message translates to:
  /// **'Set as default profile'**
  String get profilesSetAsDefaultSwitch;

  /// No description provided for @profilesCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get profilesCancel;

  /// No description provided for @profilesAddAction.
  ///
  /// In en, this message translates to:
  /// **'Add'**
  String get profilesAddAction;

  /// No description provided for @profilesSaveAction.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get profilesSaveAction;

  /// No description provided for @profilesCreateFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed to create the profile. Please try again in a moment.'**
  String get profilesCreateFailed;

  /// No description provided for @profilesEditFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed to edit the profile.'**
  String get profilesEditFailed;

  /// No description provided for @profilesSetDefaultFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed to set the default profile.'**
  String get profilesSetDefaultFailed;

  /// No description provided for @profilesDeleteTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete Profile'**
  String get profilesDeleteTitle;

  /// No description provided for @profilesDeleteConfirm.
  ///
  /// In en, this message translates to:
  /// **'Delete this profile?'**
  String get profilesDeleteConfirm;

  /// No description provided for @profilesDeleteAction.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get profilesDeleteAction;

  /// No description provided for @profilesDeleteFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed to delete the profile.'**
  String get profilesDeleteFailed;

  /// No description provided for @profilesEmpty.
  ///
  /// In en, this message translates to:
  /// **'No profiles registered'**
  String get profilesEmpty;

  /// No description provided for @profilesCreateFirst.
  ///
  /// In en, this message translates to:
  /// **'Create your first profile'**
  String get profilesCreateFirst;

  /// No description provided for @profilesDefaultBadge.
  ///
  /// In en, this message translates to:
  /// **'Default'**
  String get profilesDefaultBadge;

  /// No description provided for @profilesActiveBadge.
  ///
  /// In en, this message translates to:
  /// **'Active'**
  String get profilesActiveBadge;

  /// No description provided for @profilesMenuActivate.
  ///
  /// In en, this message translates to:
  /// **'Use as active profile'**
  String get profilesMenuActivate;

  /// No description provided for @profilesMenuSetDefault.
  ///
  /// In en, this message translates to:
  /// **'Set as default profile'**
  String get profilesMenuSetDefault;

  /// No description provided for @profilesMenuEdit.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get profilesMenuEdit;

  /// No description provided for @voiceProfilesTitle.
  ///
  /// In en, this message translates to:
  /// **'Family voices'**
  String get voiceProfilesTitle;

  /// No description provided for @voiceProfilesAddTooltip.
  ///
  /// In en, this message translates to:
  /// **'Add voice profile'**
  String get voiceProfilesAddTooltip;

  /// No description provided for @voiceProfilesMenuTooltip.
  ///
  /// In en, this message translates to:
  /// **'Open menu'**
  String get voiceProfilesMenuTooltip;

  /// No description provided for @voiceProfilesLoadError.
  ///
  /// In en, this message translates to:
  /// **'Could not load family voice info.'**
  String get voiceProfilesLoadError;

  /// No description provided for @voiceProfilesAddTitle.
  ///
  /// In en, this message translates to:
  /// **'Add voice profile'**
  String get voiceProfilesAddTitle;

  /// No description provided for @voiceProfilesEditTitle.
  ///
  /// In en, this message translates to:
  /// **'Edit voice profile'**
  String get voiceProfilesEditTitle;

  /// No description provided for @voiceProfilesLabelFieldLabel.
  ///
  /// In en, this message translates to:
  /// **'Name / label'**
  String get voiceProfilesLabelFieldLabel;

  /// No description provided for @voiceProfilesLabelFieldHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. Mom\'s voice'**
  String get voiceProfilesLabelFieldHint;

  /// No description provided for @voiceProfilesLabelRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter a label.'**
  String get voiceProfilesLabelRequired;

  /// No description provided for @voiceProfilesRelationshipFieldLabel.
  ///
  /// In en, this message translates to:
  /// **'Relationship'**
  String get voiceProfilesRelationshipFieldLabel;

  /// No description provided for @voiceProfilesRelationshipFieldHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. mother, grandmother'**
  String get voiceProfilesRelationshipFieldHint;

  /// No description provided for @voiceProfilesSampleUrlFieldLabel.
  ///
  /// In en, this message translates to:
  /// **'Sample audio URL'**
  String get voiceProfilesSampleUrlFieldLabel;

  /// No description provided for @voiceProfilesSampleUrlRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter a sample audio URL.'**
  String get voiceProfilesSampleUrlRequired;

  /// No description provided for @voiceProfilesSampleUrlInvalid.
  ///
  /// In en, this message translates to:
  /// **'Please enter a valid URL.'**
  String get voiceProfilesSampleUrlInvalid;

  /// No description provided for @voiceProfilesSampleUploadSuccess.
  ///
  /// In en, this message translates to:
  /// **'Voice sample upload complete.'**
  String get voiceProfilesSampleUploadSuccess;

  /// No description provided for @voiceProfilesSampleUploadError.
  ///
  /// In en, this message translates to:
  /// **'Sample upload failed. Please try again.'**
  String get voiceProfilesSampleUploadError;

  /// No description provided for @voiceProfilesUploading.
  ///
  /// In en, this message translates to:
  /// **'Uploading...'**
  String get voiceProfilesUploading;

  /// No description provided for @voiceProfilesUploadAudioButton.
  ///
  /// In en, this message translates to:
  /// **'Upload audio file'**
  String get voiceProfilesUploadAudioButton;

  /// No description provided for @voiceProfilesConsentToggle.
  ///
  /// In en, this message translates to:
  /// **'Guardian consent complete'**
  String get voiceProfilesConsentToggle;

  /// No description provided for @voiceProfilesActiveToggle.
  ///
  /// In en, this message translates to:
  /// **'Active status'**
  String get voiceProfilesActiveToggle;

  /// No description provided for @voiceProfilesCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get voiceProfilesCancel;

  /// No description provided for @voiceProfilesAdd.
  ///
  /// In en, this message translates to:
  /// **'Add'**
  String get voiceProfilesAdd;

  /// No description provided for @voiceProfilesSave.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get voiceProfilesSave;

  /// No description provided for @voiceProfilesCreateError.
  ///
  /// In en, this message translates to:
  /// **'Failed to create voice profile.'**
  String get voiceProfilesCreateError;

  /// No description provided for @voiceProfilesEditError.
  ///
  /// In en, this message translates to:
  /// **'Failed to edit voice profile.'**
  String get voiceProfilesEditError;

  /// No description provided for @voiceProfilesRevokeError.
  ///
  /// In en, this message translates to:
  /// **'Failed to revoke consent.'**
  String get voiceProfilesRevokeError;

  /// No description provided for @voiceProfilesDeleteTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete voice profile'**
  String get voiceProfilesDeleteTitle;

  /// No description provided for @voiceProfilesDeleteConfirm.
  ///
  /// In en, this message translates to:
  /// **'Delete this voice profile?'**
  String get voiceProfilesDeleteConfirm;

  /// No description provided for @voiceProfilesDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get voiceProfilesDelete;

  /// No description provided for @voiceProfilesDeleteError.
  ///
  /// In en, this message translates to:
  /// **'Failed to delete voice profile.'**
  String get voiceProfilesDeleteError;

  /// No description provided for @voiceProfilesEmpty.
  ///
  /// In en, this message translates to:
  /// **'No family voices registered yet.\nTap the + button in the top right to add one.'**
  String get voiceProfilesEmpty;

  /// No description provided for @voiceProfilesUnnamed.
  ///
  /// In en, this message translates to:
  /// **'Unnamed'**
  String get voiceProfilesUnnamed;

  /// No description provided for @voiceProfilesMenuEdit.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get voiceProfilesMenuEdit;

  /// No description provided for @voiceProfilesMenuRevoke.
  ///
  /// In en, this message translates to:
  /// **'Revoke consent'**
  String get voiceProfilesMenuRevoke;

  /// No description provided for @voiceProfilesMenuDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get voiceProfilesMenuDelete;

  /// No description provided for @voiceProfilesRelationshipPrefix.
  ///
  /// In en, this message translates to:
  /// **'Relationship: {relationship}'**
  String voiceProfilesRelationshipPrefix(Object relationship);

  /// No description provided for @voiceProfilesConsentDone.
  ///
  /// In en, this message translates to:
  /// **'Consent complete'**
  String get voiceProfilesConsentDone;

  /// No description provided for @voiceProfilesConsentNeeded.
  ///
  /// In en, this message translates to:
  /// **'Consent needed'**
  String get voiceProfilesConsentNeeded;

  /// No description provided for @voiceProfilesActive.
  ///
  /// In en, this message translates to:
  /// **'Active'**
  String get voiceProfilesActive;

  /// No description provided for @voiceProfilesInactive.
  ///
  /// In en, this message translates to:
  /// **'Inactive'**
  String get voiceProfilesInactive;

  /// No description provided for @podOrderTitle.
  ///
  /// In en, this message translates to:
  /// **'Order printed book'**
  String get podOrderTitle;

  /// No description provided for @podOrderBookLabel.
  ///
  /// In en, this message translates to:
  /// **'Storybook to order'**
  String get podOrderBookLabel;

  /// No description provided for @podOrderRecipientNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Recipient name'**
  String get podOrderRecipientNameLabel;

  /// No description provided for @podOrderRecipientNameError.
  ///
  /// In en, this message translates to:
  /// **'Please enter the recipient name.'**
  String get podOrderRecipientNameError;

  /// No description provided for @podOrderAddressLabel.
  ///
  /// In en, this message translates to:
  /// **'Address'**
  String get podOrderAddressLabel;

  /// No description provided for @podOrderAddressError.
  ///
  /// In en, this message translates to:
  /// **'Please enter the address.'**
  String get podOrderAddressError;

  /// No description provided for @podOrderPostalLabel.
  ///
  /// In en, this message translates to:
  /// **'Postal code'**
  String get podOrderPostalLabel;

  /// No description provided for @podOrderPostalError.
  ///
  /// In en, this message translates to:
  /// **'Please enter the postal code.'**
  String get podOrderPostalError;

  /// No description provided for @podOrderCountryLabel.
  ///
  /// In en, this message translates to:
  /// **'Country code'**
  String get podOrderCountryLabel;

  /// No description provided for @podOrderCountryError.
  ///
  /// In en, this message translates to:
  /// **'Please enter the country code.'**
  String get podOrderCountryError;

  /// No description provided for @podOrderPhoneLabel.
  ///
  /// In en, this message translates to:
  /// **'Phone number'**
  String get podOrderPhoneLabel;

  /// No description provided for @podOrderPhoneError.
  ///
  /// In en, this message translates to:
  /// **'Please enter the phone number.'**
  String get podOrderPhoneError;

  /// No description provided for @podOrderQuantityLabel.
  ///
  /// In en, this message translates to:
  /// **'Quantity'**
  String get podOrderQuantityLabel;

  /// No description provided for @podOrderQuantityValue.
  ///
  /// In en, this message translates to:
  /// **'{count} copies'**
  String podOrderQuantityValue(Object count);

  /// No description provided for @podOrderEstimatedTotal.
  ///
  /// In en, this message translates to:
  /// **'Est. {amount} KRW'**
  String podOrderEstimatedTotal(Object amount);

  /// No description provided for @podOrderSubmitting.
  ///
  /// In en, this message translates to:
  /// **'Processing order...'**
  String get podOrderSubmitting;

  /// No description provided for @podOrderSubmitButton.
  ///
  /// In en, this message translates to:
  /// **'Place order'**
  String get podOrderSubmitButton;

  /// No description provided for @podOrderSubmitSuccess.
  ///
  /// In en, this message translates to:
  /// **'Your order has been received.'**
  String get podOrderSubmitSuccess;

  /// No description provided for @podOrderSubmitError.
  ///
  /// In en, this message translates to:
  /// **'Failed to place the order. Please check your details.'**
  String get podOrderSubmitError;

  /// No description provided for @podOrderStatusError.
  ///
  /// In en, this message translates to:
  /// **'Failed to load the order status.'**
  String get podOrderStatusError;

  /// No description provided for @podOrderStatusTitle.
  ///
  /// In en, this message translates to:
  /// **'Order status'**
  String get podOrderStatusTitle;

  /// No description provided for @podOrderOrderNumber.
  ///
  /// In en, this message translates to:
  /// **'Order number: {orderId}'**
  String podOrderOrderNumber(Object orderId);

  /// No description provided for @podOrderProviderOrderNumber.
  ///
  /// In en, this message translates to:
  /// **'Supplier order number: {providerOrderId}'**
  String podOrderProviderOrderNumber(Object providerOrderId);

  /// No description provided for @podOrderCopyTooltip.
  ///
  /// In en, this message translates to:
  /// **'Copy'**
  String get podOrderCopyTooltip;

  /// No description provided for @podOrderProviderOrderCopied.
  ///
  /// In en, this message translates to:
  /// **'Copied the supplier order number.'**
  String get podOrderProviderOrderCopied;

  /// No description provided for @podOrderStatusValue.
  ///
  /// In en, this message translates to:
  /// **'Status: {status}'**
  String podOrderStatusValue(Object status);

  /// No description provided for @podOrderPaymentAmount.
  ///
  /// In en, this message translates to:
  /// **'Payment amount: {amount} KRW'**
  String podOrderPaymentAmount(Object amount);

  /// No description provided for @podOrderSyncValue.
  ///
  /// In en, this message translates to:
  /// **'Sync: {source}'**
  String podOrderSyncValue(Object source);

  /// No description provided for @podOrderTrackingNumber.
  ///
  /// In en, this message translates to:
  /// **'Tracking number: {trackingNumber}'**
  String podOrderTrackingNumber(Object trackingNumber);

  /// No description provided for @podOrderRefreshStatus.
  ///
  /// In en, this message translates to:
  /// **'Refresh status'**
  String get podOrderRefreshStatus;

  /// No description provided for @podOrderDecreaseQuantityTooltip.
  ///
  /// In en, this message translates to:
  /// **'Decrease quantity'**
  String get podOrderDecreaseQuantityTooltip;

  /// No description provided for @podOrderIncreaseQuantityTooltip.
  ///
  /// In en, this message translates to:
  /// **'Increase quantity'**
  String get podOrderIncreaseQuantityTooltip;

  /// No description provided for @branchStoryTitle.
  ///
  /// In en, this message translates to:
  /// **'Branching story'**
  String get branchStoryTitle;

  /// No description provided for @branchStoryRefreshTooltip.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get branchStoryRefreshTooltip;

  /// No description provided for @branchStoryLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load the branching story.'**
  String get branchStoryLoadError;

  /// No description provided for @branchStoryResumeStatus.
  ///
  /// In en, this message translates to:
  /// **'Continuing reading from where you left off.'**
  String get branchStoryResumeStatus;

  /// No description provided for @branchStoryEndingReached.
  ///
  /// In en, this message translates to:
  /// **'You\'ve reached the ending of this branch.'**
  String get branchStoryEndingReached;

  /// No description provided for @branchStoryChoiceApplied.
  ///
  /// In en, this message translates to:
  /// **'Your choice was applied.'**
  String get branchStoryChoiceApplied;

  /// No description provided for @branchStoryEndingArrived.
  ///
  /// In en, this message translates to:
  /// **'Ending reached: {selected}'**
  String branchStoryEndingArrived(Object selected);

  /// No description provided for @branchStorySelected.
  ///
  /// In en, this message translates to:
  /// **'Selected: {selected}'**
  String branchStorySelected(Object selected);

  /// No description provided for @branchStoryChoiceFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t apply your choice. Please try again.'**
  String get branchStoryChoiceFailed;

  /// No description provided for @branchStorySampleText1.
  ///
  /// In en, this message translates to:
  /// **'The rabbit stood at a fork in the road.'**
  String get branchStorySampleText1;

  /// No description provided for @branchStorySampleText2.
  ///
  /// In en, this message translates to:
  /// **'On the left path, it met a new friend.'**
  String get branchStorySampleText2;

  /// No description provided for @branchStorySampleText3.
  ///
  /// In en, this message translates to:
  /// **'On the right path, it discovered a treasure.'**
  String get branchStorySampleText3;

  /// No description provided for @branchStorySampleOptionLeft.
  ///
  /// In en, this message translates to:
  /// **'Take the left path'**
  String get branchStorySampleOptionLeft;

  /// No description provided for @branchStorySampleOptionRight.
  ///
  /// In en, this message translates to:
  /// **'Take the right path'**
  String get branchStorySampleOptionRight;

  /// No description provided for @branchStorySampleCreated.
  ///
  /// In en, this message translates to:
  /// **'Created a sample branching story.'**
  String get branchStorySampleCreated;

  /// No description provided for @branchStorySampleCreateFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t create the sample branch.'**
  String get branchStorySampleCreateFailed;

  /// No description provided for @branchStoryNodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Node: {nodeKey}'**
  String branchStoryNodeLabel(Object nodeKey);

  /// No description provided for @branchStoryPageLabel.
  ///
  /// In en, this message translates to:
  /// **'Page {pageNumber}'**
  String branchStoryPageLabel(Object pageNumber);

  /// No description provided for @branchStoryImageSemantics.
  ///
  /// In en, this message translates to:
  /// **'Branching story illustration'**
  String get branchStoryImageSemantics;

  /// No description provided for @branchStoryOptionsHeading.
  ///
  /// In en, this message translates to:
  /// **'Choices'**
  String get branchStoryOptionsHeading;

  /// No description provided for @branchStoryNoOptions.
  ///
  /// In en, this message translates to:
  /// **'There are no more choices. This is the ending of this branch.'**
  String get branchStoryNoOptions;

  /// No description provided for @branchStoryPreviousChoice.
  ///
  /// In en, this message translates to:
  /// **'Previous choice'**
  String get branchStoryPreviousChoice;

  /// No description provided for @branchStoryRestart.
  ///
  /// In en, this message translates to:
  /// **'Restart'**
  String get branchStoryRestart;

  /// No description provided for @branchStoryRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get branchStoryRetry;

  /// No description provided for @branchStoryEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'There\'s no branching story yet.'**
  String get branchStoryEmptyTitle;

  /// No description provided for @branchStoryEmptySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Create a sample branch to try an interactive story right away.'**
  String get branchStoryEmptySubtitle;

  /// No description provided for @branchStorySampleCreating.
  ///
  /// In en, this message translates to:
  /// **'Creating...'**
  String get branchStorySampleCreating;

  /// No description provided for @branchStoryCreateSample.
  ///
  /// In en, this message translates to:
  /// **'Create sample branch'**
  String get branchStoryCreateSample;

  /// No description provided for @pronunciationTitle.
  ///
  /// In en, this message translates to:
  /// **'Pronunciation Practice'**
  String get pronunciationTitle;

  /// No description provided for @pronunciationIntro.
  ///
  /// In en, this message translates to:
  /// **'Pronunciation is evaluated against the sentence on storybook page {pageNumber}.'**
  String pronunciationIntro(Object pageNumber);

  /// No description provided for @pronunciationExpectedLabel.
  ///
  /// In en, this message translates to:
  /// **'Reference sentence'**
  String get pronunciationExpectedLabel;

  /// No description provided for @pronunciationTranscriptLabel.
  ///
  /// In en, this message translates to:
  /// **'Read sentence (text input)'**
  String get pronunciationTranscriptLabel;

  /// No description provided for @pronunciationTranscriptHint.
  ///
  /// In en, this message translates to:
  /// **'Please enter the sentence your child read.'**
  String get pronunciationTranscriptHint;

  /// No description provided for @pronunciationEvaluating.
  ///
  /// In en, this message translates to:
  /// **'Evaluating...'**
  String get pronunciationEvaluating;

  /// No description provided for @pronunciationEvaluateButton.
  ///
  /// In en, this message translates to:
  /// **'Evaluate pronunciation'**
  String get pronunciationEvaluateButton;

  /// No description provided for @pronunciationEvaluateAudioButton.
  ///
  /// In en, this message translates to:
  /// **'Evaluate with audio file'**
  String get pronunciationEvaluateAudioButton;

  /// No description provided for @pronunciationScore.
  ///
  /// In en, this message translates to:
  /// **'Pronunciation score: {score}'**
  String pronunciationScore(Object score);

  /// No description provided for @pronunciationNoFeedback.
  ///
  /// In en, this message translates to:
  /// **'No feedback available.'**
  String get pronunciationNoFeedback;

  /// No description provided for @pronunciationErrorBothRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter both the reference sentence and the read sentence.'**
  String get pronunciationErrorBothRequired;

  /// No description provided for @pronunciationErrorEvaluateFailed.
  ///
  /// In en, this message translates to:
  /// **'Pronunciation evaluation failed. Please try again in a moment.'**
  String get pronunciationErrorEvaluateFailed;

  /// No description provided for @pronunciationErrorExpectedRequired.
  ///
  /// In en, this message translates to:
  /// **'Please enter the reference sentence first.'**
  String get pronunciationErrorExpectedRequired;

  /// No description provided for @pronunciationErrorAudioEvaluateFailed.
  ///
  /// In en, this message translates to:
  /// **'Audio pronunciation evaluation failed. Please try again.'**
  String get pronunciationErrorAudioEvaluateFailed;

  /// No description provided for @parentDashboardLoadError.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t load the dashboard data.'**
  String get parentDashboardLoadError;

  /// No description provided for @parentDashboardReportMonthly.
  ///
  /// In en, this message translates to:
  /// **'Monthly report'**
  String get parentDashboardReportMonthly;

  /// No description provided for @parentDashboardReportWeekly.
  ///
  /// In en, this message translates to:
  /// **'Weekly report'**
  String get parentDashboardReportWeekly;

  /// No description provided for @parentDashboardTitle.
  ///
  /// In en, this message translates to:
  /// **'Parent dashboard'**
  String get parentDashboardTitle;

  /// No description provided for @parentDashboardRefreshTooltip.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get parentDashboardRefreshTooltip;

  /// No description provided for @parentDashboardSegmentWeekly.
  ///
  /// In en, this message translates to:
  /// **'Weekly'**
  String get parentDashboardSegmentWeekly;

  /// No description provided for @parentDashboardSegmentMonthly.
  ///
  /// In en, this message translates to:
  /// **'Monthly'**
  String get parentDashboardSegmentMonthly;

  /// No description provided for @parentDashboardThemeUnspecified.
  ///
  /// In en, this message translates to:
  /// **'Unspecified'**
  String get parentDashboardThemeUnspecified;

  /// No description provided for @parentDashboardMetricTotalBooksTitle.
  ///
  /// In en, this message translates to:
  /// **'Total storybooks read'**
  String get parentDashboardMetricTotalBooksTitle;

  /// No description provided for @parentDashboardMetricTotalBooksValue.
  ///
  /// In en, this message translates to:
  /// **'{count}'**
  String parentDashboardMetricTotalBooksValue(Object count);

  /// No description provided for @parentDashboardMetricTotalMinutesTitle.
  ///
  /// In en, this message translates to:
  /// **'Total reading time'**
  String get parentDashboardMetricTotalMinutesTitle;

  /// No description provided for @parentDashboardMetricTotalMinutesValue.
  ///
  /// In en, this message translates to:
  /// **'{minutes} min'**
  String parentDashboardMetricTotalMinutesValue(Object minutes);

  /// No description provided for @parentDashboardMetricAvgMinutesTitle.
  ///
  /// In en, this message translates to:
  /// **'Average reading time'**
  String get parentDashboardMetricAvgMinutesTitle;

  /// No description provided for @parentDashboardMetricAvgMinutesValue.
  ///
  /// In en, this message translates to:
  /// **'{minutes} min'**
  String parentDashboardMetricAvgMinutesValue(Object minutes);

  /// No description provided for @parentDashboardMetricPreferredThemeTitle.
  ///
  /// In en, this message translates to:
  /// **'Preferred theme'**
  String get parentDashboardMetricPreferredThemeTitle;

  /// No description provided for @parentDashboardLearningTitle.
  ///
  /// In en, this message translates to:
  /// **'Learning progress'**
  String get parentDashboardLearningTitle;

  /// No description provided for @parentDashboardLearningStreakLine.
  ///
  /// In en, this message translates to:
  /// **'Current streak {current} days · Best {longest} days'**
  String parentDashboardLearningStreakLine(Object current, Object longest);

  /// No description provided for @parentDashboardLearningSessionLine.
  ///
  /// In en, this message translates to:
  /// **'Completed sessions {completed} / total sessions {total}'**
  String parentDashboardLearningSessionLine(Object completed, Object total);

  /// No description provided for @parentDashboardLearningCompletionLine.
  ///
  /// In en, this message translates to:
  /// **'Completion rate {rate}%'**
  String parentDashboardLearningCompletionLine(Object rate);

  /// No description provided for @parentDashboardDailyChartTitle.
  ///
  /// In en, this message translates to:
  /// **'Daily reading time'**
  String get parentDashboardDailyChartTitle;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'ja', 'ko'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'ja':
      return AppLocalizationsJa();
    case 'ko':
      return AppLocalizationsKo();
  }

  throw FlutterError(
      'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
      'an issue with the localizations generation tool. Please file an issue '
      'on GitHub with a reproducible sample app and the gen-l10n configuration '
      'that was used.');
}
