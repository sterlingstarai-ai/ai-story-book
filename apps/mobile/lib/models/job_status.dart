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
    final errorJson = JsonParsing.asNullableMap(json['error'], field: 'error');

    return JobStatus(
      jobId: JsonParsing.asRequiredString(json['job_id'], field: 'job_id'),
      status: JobState.fromString(
        JsonParsing.asRequiredString(json['status'], field: 'status'),
      ),
      progress:
          JsonParsing.asOptionalInt(json['progress'], field: 'progress') ?? 0,
      currentStep: JsonParsing.asOptionalString(json['current_step']),
      errorCode: JsonParsing.asOptionalString(json['error_code']) ??
          JsonParsing.asOptionalString(errorJson?['code']),
      errorMessage: JsonParsing.asOptionalString(json['error_message']) ??
          JsonParsing.asOptionalString(errorJson?['message']) ??
          JsonParsing.asOptionalString(json['detail']),
      result: resultJson == null ? null : BookResult.fromJson(resultJson),
    );
  }

  bool get isComplete => status == JobState.done;
  bool get isFailed => status == JobState.failed;
  bool get isRunning => status == JobState.running || status == JobState.queued;
}

class AssetStatusDetail {
  final String state;
  final String? reason;
  final String? url;

  AssetStatusDetail({
    required this.state,
    this.reason,
    this.url,
  });

  factory AssetStatusDetail.fromJson(Map<String, dynamic> json) {
    return AssetStatusDetail(
      state: JsonParsing.asRequiredString(json['state'], field: 'state'),
      reason: JsonParsing.asOptionalString(json['reason']),
      url: JsonParsing.asOptionalString(json['url']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'state': state,
      if (reason != null) 'reason': reason,
      if (url != null) 'url': url,
    };
  }
}

class GenerationWarning {
  final String code;
  final String message;
  final String? asset;
  final int? pageNumber;

  GenerationWarning({
    required this.code,
    required this.message,
    this.asset,
    this.pageNumber,
  });

  factory GenerationWarning.fromJson(Map<String, dynamic> json) {
    return GenerationWarning(
      code: JsonParsing.asRequiredString(json['code'], field: 'code'),
      message: JsonParsing.asRequiredString(json['message'], field: 'message'),
      asset: JsonParsing.asOptionalString(json['asset']),
      pageNumber:
          JsonParsing.asOptionalInt(json['page_number'], field: 'page_number'),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'code': code,
      'message': message,
      if (asset != null) 'asset': asset,
      if (pageNumber != null) 'page_number': pageNumber,
    };
  }
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
  final List<GenerationWarning> generationWarnings;

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
    this.generationWarnings = const [],
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
    final generationWarnings = JsonParsing.asNullableList(
                json['generation_warnings'],
                field: 'generation_warnings')
            ?.map((warning) => GenerationWarning.fromJson(
                  JsonParsing.asMap(warning, field: 'generation_warnings[]'),
                ))
            .toList() ??
        const <GenerationWarning>[];

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
      generationWarnings: generationWarnings,
    );
  }

  /// 현재 언어에 맞는 제목 반환
  String getTitle(String language) {
    if (language == 'ko' && titleKo != null) return titleKo!;
    if (language == 'en' && titleEn != null) return titleEn!;
    return title;
  }

  bool get hasGenerationWarnings => generationWarnings.isNotEmpty;

  Map<String, dynamic> toJson() {
    return {
      'book_id': bookId,
      if (jobId != null) 'job_id': jobId,
      'title': title,
      'cover_image_url': coverImageUrl,
      'pages': pages.map((page) => page.toJson()).toList(),
      if (characterId != null) 'character_id': characterId,
      if (seriesId != null) 'series_id': seriesId,
      if (seriesIndex != null) 'series_index': seriesIndex,
      if (titleKo != null) 'title_ko': titleKo,
      if (titleEn != null) 'title_en': titleEn,
      if (learningAssets != null) 'learning_assets': learningAssets!.toJson(),
      if (generationWarnings.isNotEmpty)
        'generation_warnings':
            generationWarnings.map((warning) => warning.toJson()).toList(),
    };
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
  final Map<String, AssetStatusDetail> assetStatus;

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
    this.assetStatus = const {},
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
    final assetStatusJson =
        JsonParsing.asNullableMap(json['asset_status'], field: 'asset_status');
    final assetStatus = <String, AssetStatusDetail>{};
    if (assetStatusJson != null) {
      for (final entry in assetStatusJson.entries) {
        assetStatus[entry.key] = AssetStatusDetail.fromJson(
          JsonParsing.asMap(entry.value, field: 'asset_status.${entry.key}'),
        );
      }
    }

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
      assetStatus: assetStatus,
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

  /// 학습 모드 노출 여부 (단어/이해질문/퀴즈 중 하나라도 있으면 true)
  bool get hasLearningContent {
    final hasVocab = vocab != null && vocab!.isNotEmpty;
    final hasComprehension =
        comprehensionQuestions != null && comprehensionQuestions!.isNotEmpty;
    final hasQuiz = quiz != null && quiz!.isNotEmpty;
    return hasVocab || hasComprehension || hasQuiz;
  }

  bool get hasDegradedImage => assetStatus['image']?.state == 'degraded';

  Map<String, dynamic> toJson() {
    return {
      'page_number': pageNumber,
      'text': text,
      'image_url': imageUrl,
      if (audioUrl != null) 'audio_url': audioUrl,
      if (textKo != null) 'text_ko': textKo,
      if (textEn != null) 'text_en': textEn,
      if (audioUrlKo != null) 'audio_url_ko': audioUrlKo,
      if (audioUrlEn != null) 'audio_url_en': audioUrlEn,
      if (vocab != null) 'vocab': vocab!.map((item) => item.toJson()).toList(),
      if (comprehensionQuestions != null)
        'comprehension_questions':
            comprehensionQuestions!.map((item) => item.toJson()).toList(),
      if (quiz != null) 'quiz': quiz!.map((item) => item.toJson()).toList(),
      if (assetStatus.isNotEmpty)
        'asset_status': assetStatus.map(
          (key, value) => MapEntry(key, value.toJson()),
        ),
    };
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

  Map<String, dynamic> toJson() {
    return {
      'word': word,
      'meaning': meaning,
      if (example != null) 'example': example,
    };
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

  Map<String, dynamic> toJson() {
    return {
      'question': question,
      if (answer != null) 'answer': answer,
    };
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

  Map<String, dynamic> toJson() {
    return {
      'question': question,
      'options': options,
      'answer_index': answerIndex,
      if (explanation != null) 'explanation': explanation,
    };
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

  Map<String, dynamic> toJson() {
    return {
      'summary': summary,
      'discussion_prompts': discussionPrompts,
      'activities': activities,
    };
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

  Map<String, dynamic> toJson() {
    return {
      'source_language': sourceLanguage,
      'target_language': targetLanguage,
      'title_translation': titleTranslation,
      'parent_guide': parentGuide.toJson(),
    };
  }
}
