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
    return JobStatus(
      jobId: json['job_id'] as String,
      status: JobState.fromString(json['status'] as String),
      progress: json['progress'] as int? ?? 0,
      currentStep: json['current_step'] as String?,
      errorCode: json['error_code'] as String?,
      errorMessage: json['error_message'] as String?,
      result: json['result'] != null
          ? BookResult.fromJson(json['result'] as Map<String, dynamic>)
          : null,
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
    return BookResult(
      bookId: json['book_id'] as String,
      jobId: json['job_id'] as String?,
      title: json['title'] as String,
      coverImageUrl: json['cover_image_url'] as String,
      pages: (json['pages'] as List<dynamic>)
          .map((p) => PageResult.fromJson(p as Map<String, dynamic>))
          .toList(),
      characterId: json['character_id'] as String?,
      seriesId: json['series_id'] as String?,
      seriesIndex: json['series_index'] as int?,
      titleKo: json['title_ko'] as String?,
      titleEn: json['title_en'] as String?,
      learningAssets: json['learning_assets'] != null
          ? LearningAssets.fromJson(json['learning_assets'] as Map<String, dynamic>)
          : null,
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
    return PageResult(
      pageNumber: json['page_number'] as int,
      text: json['text'] as String,
      imageUrl: json['image_url'] as String,
      audioUrl: json['audio_url'] as String?,
      textKo: json['text_ko'] as String?,
      textEn: json['text_en'] as String?,
      audioUrlKo: json['audio_url_ko'] as String?,
      audioUrlEn: json['audio_url_en'] as String?,
      vocab: json['vocab'] != null
          ? (json['vocab'] as List<dynamic>)
              .map((v) => VocabItem.fromJson(v as Map<String, dynamic>))
              .toList()
          : null,
      comprehensionQuestions: json['comprehension_questions'] != null
          ? (json['comprehension_questions'] as List<dynamic>)
              .map((q) => ComprehensionQuestion.fromJson(q as Map<String, dynamic>))
              .toList()
          : null,
      quiz: json['quiz'] != null
          ? (json['quiz'] as List<dynamic>)
              .map((q) => QuizItem.fromJson(q as Map<String, dynamic>))
              .toList()
          : null,
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
      word: json['word'] as String,
      meaning: json['meaning'] as String,
      example: json['example'] as String?,
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
      question: json['question'] as String,
      answer: json['answer'] as String?,
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
    return QuizItem(
      question: json['question'] as String,
      options: (json['options'] as List<dynamic>).map((o) => o as String).toList(),
      answerIndex: json['answer_index'] as int,
      explanation: json['explanation'] as String?,
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
    return ParentGuide(
      summary: json['summary'] as String,
      discussionPrompts: (json['discussion_prompts'] as List<dynamic>)
          .map((p) => p as String)
          .toList(),
      activities: (json['activities'] as List<dynamic>)
          .map((a) => a as String)
          .toList(),
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
      sourceLanguage: json['source_language'] as String,
      targetLanguage: json['target_language'] as String,
      titleTranslation: json['title_translation'] as String,
      parentGuide: ParentGuide.fromJson(json['parent_guide'] as Map<String, dynamic>),
    );
  }
}
