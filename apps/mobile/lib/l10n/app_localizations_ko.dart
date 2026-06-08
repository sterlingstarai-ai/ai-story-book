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
  String get vocabLearnedLabel => '학습 어휘';

  @override
  String get quizAccuracyLabel => '퀴즈 정확도';

  @override
  String get retry => '다시 시도';
}
