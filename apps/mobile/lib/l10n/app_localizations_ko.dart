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
}
