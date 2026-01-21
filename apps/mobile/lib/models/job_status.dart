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

  BookResult({
    required this.bookId,
    this.jobId,
    required this.title,
    required this.coverImageUrl,
    required this.pages,
    this.characterId,
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
    );
  }
}

/// 페이지 결과 모델
class PageResult {
  final int pageNumber;
  final String text;
  final String imageUrl;
  final String? audioUrl;

  PageResult({
    required this.pageNumber,
    required this.text,
    required this.imageUrl,
    this.audioUrl,
  });

  factory PageResult.fromJson(Map<String, dynamic> json) {
    return PageResult(
      pageNumber: json['page_number'] as int,
      text: json['text'] as String,
      imageUrl: json['image_url'] as String,
      audioUrl: json['audio_url'] as String?,
    );
  }
}
