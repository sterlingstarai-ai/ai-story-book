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
  String get currentStreakLabel => '連続読書';

  @override
  String get vocabLearnedLabel => '学んだ語彙';

  @override
  String get quizAccuracyLabel => 'クイズ正答率';

  @override
  String get retry => '再試行';

  @override
  String get onboardingSkip => 'スキップ';

  @override
  String get onboardingNext => '次へ';

  @override
  String get onboardingStart => 'はじめる';

  @override
  String get onboardingSlide1Title => 'AIオーダーメイド絵本';

  @override
  String get onboardingSlide1Subtitle => 'お子さまに合ったお話をAIが作ります。';

  @override
  String get onboardingSlide2Title => '写真からキャラクター作成';

  @override
  String get onboardingSlide2Subtitle => 'お子さまの写真を絵本の主人公にできます。';

  @override
  String get onboardingSlide3Title => '毎日の読書習慣';

  @override
  String get onboardingSlide3Subtitle => 'ストリークで毎日の読書習慣を育てます。';

  @override
  String get onboardingSlide4Title => '無料ではじめる';

  @override
  String get onboardingSlide4Subtitle => '初回3クレジットですぐに絵本を作れます。';

  @override
  String onboardingPageIndicator(int current, int total) {
    return '$totalページ中$currentページ目';
  }
}
