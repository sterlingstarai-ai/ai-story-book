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
}
