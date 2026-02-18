import 'json_parsing.dart';

/// Job 상태
enum JobState {
  queued,
  running,
  failed,
  done;

  static JobState fromString(String value) {
    return JobState.values.firstWhere(
      (e) => e.name == value,
      orElse: () => JobState.queued,
    );
  }
}

/// Job 상태 응답 모델
class JobStatus {
  final String jobId;
  final JobState status;
  final int progress;
  final String? currentStep;
  final String? errorCode;
  final String? errorMessage;
  final BookResult? result;

  JobStatus({
    required this.jobId,
    required this.status,
    required this.progress,
    this.currentStep,
    this.errorCode,
    this.errorMessage,
    this.result,
  });

  factory JobStatus.fromJson(Map<String, dynamic> json) {
    final resultJson =
        JsonParsing.asNullableMap(json['result'], field: 'result');

    return JobStatus(
      jobId: JsonParsing.asRequiredString(json['job_id'], field: 'job_id'),
      status: JobState.fromString(
        JsonParsing.asRequiredString(json['status'], field: 'status'),
      ),
      progress:
          JsonParsing.asOptionalInt(json['progress'], field: 'progress') ?? 0,
      currentStep: JsonParsing.asOptionalString(json['current_step']),
      errorCode: JsonParsing.asOptionalString(json['error_code']),
      errorMessage: JsonParsing.asOptionalString(json['error_message']),
      result: resultJson == null ? null : BookResult.fromJson(resultJson),
    );
  }

  bool get isComplete => status == JobState.done;
  bool get isFailed => status == JobState.failed;
  bool get isRunning => status == JobState.running || status == JobState.queued;
}

/// 책 결과 모델
class BookResult {
  final String bookId;
  final String? jobId;
  final String title;
  final String coverImageUrl;
  final List<PageResult> pages;
  final String? characterId;
  // 시리즈 정보
  final String? seriesId;
  final int? seriesIndex;
  // 다국어 제목
  final String? titleKo;
  final String? titleEn;
  // 학습 자산
  final LearningAssets? learningAssets;

  BookResult({
    required this.bookId,
    this.jobId,
    required this.title,
    required this.coverImageUrl,
    required this.pages,
    this.characterId,
    this.seriesId,
    this.seriesIndex,
    this.titleKo,
    this.titleEn,
    this.learningAssets,
  });

  factory BookResult.fromJson(Map<String, dynamic> json) {
    final pages = JsonParsing.asList(json['pages'], field: 'pages')
        .map((page) => PageResult.fromJson(
              JsonParsing.asMap(page, field: 'pages[]'),
            ))
        .toList();
    final learningAssetsJson = JsonParsing.asNullableMap(
        json['learning_assets'],
        field: 'learning_assets');

    return BookResult(
      bookId: JsonParsing.asRequiredString(json['book_id'], field: 'book_id'),
      jobId: JsonParsing.asOptionalString(json['job_id']),
      title: JsonParsing.asRequiredString(json['title'], field: 'title'),
      coverImageUrl: JsonParsing.asRequiredString(
        json['cover_image_url'],
        field: 'cover_image_url',
      ),
      pages: pages,
      characterId: JsonParsing.asOptionalString(json['character_id']),
      seriesId: JsonParsing.asOptionalString(json['series_id']),
      seriesIndex: JsonParsing.asOptionalInt(json['series_index'],
          field: 'series_index'),
      titleKo: JsonParsing.asOptionalString(json['title_ko']),
      titleEn: JsonParsing.asOptionalString(json['title_en']),
      learningAssets: learningAssetsJson == null
          ? null
          : LearningAssets.fromJson(learningAssetsJson),
    );
  }

  /// 현재 언어에 맞는 제목 반환
  String getTitle(String language) {
    if (language == 'ko' && titleKo != null) return titleKo!;
    if (language == 'en' && titleEn != null) return titleEn!;
    return title;
  }
}

/// 페이지 결과 모델
class PageResult {
  final int pageNumber;
  final String text;
  final String imageUrl;
  final String? audioUrl;
  // 다국어 텍스트
  final String? textKo;
  final String? textEn;
  final String? audioUrlKo;
  final String? audioUrlEn;
  // 학습 자산
  final List<VocabItem>? vocab;
  final List<ComprehensionQuestion>? comprehensionQuestions;
  final List<QuizItem>? quiz;

  PageResult({
    required this.pageNumber,
    required this.text,
    required this.imageUrl,
    this.audioUrl,
    this.textKo,
    this.textEn,
    this.audioUrlKo,
    this.audioUrlEn,
    this.vocab,
    this.comprehensionQuestions,
    this.quiz,
  });

  factory PageResult.fromJson(Map<String, dynamic> json) {
    final vocab = JsonParsing.asNullableList(json['vocab'], field: 'vocab')
        ?.map((item) => VocabItem.fromJson(
              JsonParsing.asMap(item, field: 'vocab[]'),
            ))
        .toList();
    final comprehensionQuestions = JsonParsing.asNullableList(
      json['comprehension_questions'],
      field: 'comprehension_questions',
    )
        ?.map((item) => ComprehensionQuestion.fromJson(
              JsonParsing.asMap(item, field: 'comprehension_questions[]'),
            ))
        .toList();
    final quiz = JsonParsing.asNullableList(json['quiz'], field: 'quiz')
        ?.map((item) => QuizItem.fromJson(
              JsonParsing.asMap(item, field: 'quiz[]'),
            ))
        .toList();

    return PageResult(
      pageNumber:
          JsonParsing.asRequiredInt(json['page_number'], field: 'page_number'),
      text: JsonParsing.asRequiredString(json['text'], field: 'text'),
      imageUrl:
          JsonParsing.asRequiredString(json['image_url'], field: 'image_url'),
      audioUrl: JsonParsing.asOptionalString(json['audio_url']),
      textKo: JsonParsing.asOptionalString(json['text_ko']),
      textEn: JsonParsing.asOptionalString(json['text_en']),
      audioUrlKo: JsonParsing.asOptionalString(json['audio_url_ko']),
      audioUrlEn: JsonParsing.asOptionalString(json['audio_url_en']),
      vocab: vocab,
      comprehensionQuestions: comprehensionQuestions,
      quiz: quiz,
    );
  }

  /// 현재 언어에 맞는 텍스트 반환
  String getText(String language) {
    if (language == 'ko' && textKo != null) return textKo!;
    if (language == 'en' && textEn != null) return textEn!;
    return text;
  }

  /// 현재 언어에 맞는 오디오 URL 반환
  String? getAudioUrl(String language) {
    if (language == 'ko' && audioUrlKo != null) return audioUrlKo;
    if (language == 'en' && audioUrlEn != null) return audioUrlEn;
    return audioUrl;
  }
}

/// 단어 학습 아이템
class VocabItem {
  final String word;
  final String meaning;
  final String? example;

  VocabItem({
    required this.word,
    required this.meaning,
    this.example,
  });

  factory VocabItem.fromJson(Map<String, dynamic> json) {
    return VocabItem(
      word: JsonParsing.asRequiredString(json['word'], field: 'word'),
      meaning: JsonParsing.asRequiredString(json['meaning'], field: 'meaning'),
      example: JsonParsing.asOptionalString(json['example']),
    );
  }
}

/// 이해 질문
class ComprehensionQuestion {
  final String question;
  final String? answer;

  ComprehensionQuestion({
    required this.question,
    this.answer,
  });

  factory ComprehensionQuestion.fromJson(Map<String, dynamic> json) {
    return ComprehensionQuestion(
      question:
          JsonParsing.asRequiredString(json['question'], field: 'question'),
      answer: JsonParsing.asOptionalString(json['answer']),
    );
  }
}

/// 퀴즈 아이템
class QuizItem {
  final String question;
  final List<String> options;
  final int answerIndex;
  final String? explanation;

  QuizItem({
    required this.question,
    required this.options,
    required this.answerIndex,
    this.explanation,
  });

  factory QuizItem.fromJson(Map<String, dynamic> json) {
    final options = JsonParsing.asList(json['options'], field: 'options')
        .map((option) =>
            JsonParsing.asRequiredString(option, field: 'options[]'))
        .toList();

    return QuizItem(
      question:
          JsonParsing.asRequiredString(json['question'], field: 'question'),
      options: options,
      answerIndex: JsonParsing.asRequiredInt(json['answer_index'],
          field: 'answer_index'),
      explanation: JsonParsing.asOptionalString(json['explanation']),
    );
  }
}

/// 부모 가이드
class ParentGuide {
  final String summary;
  final List<String> discussionPrompts;
  final List<String> activities;

  ParentGuide({
    required this.summary,
    required this.discussionPrompts,
    required this.activities,
  });

  factory ParentGuide.fromJson(Map<String, dynamic> json) {
    final discussionPrompts = JsonParsing.asList(
      json['discussion_prompts'],
      field: 'discussion_prompts',
    )
        .map((prompt) =>
            JsonParsing.asRequiredString(prompt, field: 'discussion_prompts[]'))
        .toList();
    final activities = JsonParsing.asList(
      json['activities'],
      field: 'activities',
    )
        .map((activity) =>
            JsonParsing.asRequiredString(activity, field: 'activities[]'))
        .toList();

    return ParentGuide(
      summary: JsonParsing.asRequiredString(json['summary'], field: 'summary'),
      discussionPrompts: discussionPrompts,
      activities: activities,
    );
  }
}

/// 전체 학습 자산
class LearningAssets {
  final String sourceLanguage;
  final String targetLanguage;
  final String titleTranslation;
  final ParentGuide parentGuide;

  LearningAssets({
    required this.sourceLanguage,
    required this.targetLanguage,
    required this.titleTranslation,
    required this.parentGuide,
  });

  factory LearningAssets.fromJson(Map<String, dynamic> json) {
    return LearningAssets(
      sourceLanguage: JsonParsing.asRequiredString(
        json['source_language'],
        field: 'source_language',
      ),
      targetLanguage: JsonParsing.asRequiredString(
        json['target_language'],
        field: 'target_language',
      ),
      titleTranslation: JsonParsing.asRequiredString(
        json['title_translation'],
        field: 'title_translation',
      ),
      parentGuide: ParentGuide.fromJson(
        JsonParsing.asMap(json['parent_guide'], field: 'parent_guide'),
      ),
    );
  }
}
