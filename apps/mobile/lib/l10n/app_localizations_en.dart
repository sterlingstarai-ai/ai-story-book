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
  String get vocabLearnedLabel => 'Words learned';

  @override
  String get quizAccuracyLabel => 'Quiz accuracy';

  @override
  String get retry => 'Retry';
}
