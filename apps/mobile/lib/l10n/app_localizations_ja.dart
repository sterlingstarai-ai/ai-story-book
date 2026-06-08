// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Japanese (`ja`).
class AppLocalizationsJa extends AppLocalizations {
  AppLocalizationsJa([String locale = 'ja']) : super(locale);

  @override
  String get appTitle => 'AIえほん';

  @override
  String get readingGrowthTitle => '読書の成長';

  @override
  String get readingGrowthEntryTitle => '読書の成長を見る';

  @override
  String get readingGrowthEntrySubtitle => 'お子さまの読書力が育つ様子';

  @override
  String get estimatedReadingLevel => 'お子さまの推定読書レベル';

  @override
  String get booksReadLabel => '読んだ本';

  @override
  String get vocabLearnedLabel => '学んだ語彙';

  @override
  String get quizAccuracyLabel => 'クイズ正答率';

  @override
  String get retry => '再試行';
}
