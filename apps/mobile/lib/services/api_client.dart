import 'dart:io';
import 'package:dio/dio.dart';
import '../core/api_error.dart';
import '../models/models.dart';

/// API 클라이언트
class ApiClient {
  final Dio _dio;
  final String _userKey;

  ApiClient({
    required String baseUrl,
    required String userKey,
  })  : _userKey = userKey,
        _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 30),
          receiveTimeout: const Duration(seconds: 30),
          headers: {
            'Content-Type': 'application/json',
          },
        )) {
    _dio.interceptors.add(LogInterceptor(
      requestBody: true,
      responseBody: true,
    ));

    // Error handling interceptor
    _dio.interceptors.add(InterceptorsWrapper(
      onError: (error, handler) {
        // Convert to standardized ApiError
        final apiError = ApiError.fromDioException(error);
        handler.reject(DioException(
          requestOptions: error.requestOptions,
          error: apiError,
          message: apiError.userMessage,
        ));
      },
    ));
  }

  Map<String, String> get _headers => {
        'X-User-Key': _userKey,
      };

  // ==================== Books ====================

  /// 책 생성 요청
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    final headers = Map<String, String>.from(_headers);
    if (idempotencyKey != null) {
      headers['X-Idempotency-Key'] = idempotencyKey;
    }

    final response = await _dio.post(
      '/v1/books',
      data: spec.toJson(),
      options: Options(headers: headers),
    );

    return CreateBookResponse.fromJson(response.data as Map<String, dynamic>);
  }

  /// 책 생성 상태 조회
  Future<JobStatus> getBookStatus(String jobId) async {
    final response = await _dio.get(
      '/v1/books/$jobId',
      options: Options(headers: _headers),
    );

    return JobStatus.fromJson(response.data as Map<String, dynamic>);
  }

  /// 페이지 재생성
  Future<void> regeneratePage(
    String jobId,
    int pageNumber, {
    required String regenerateTarget,
  }) async {
    await _dio.post(
      '/v1/books/$jobId/pages/$pageNumber/regenerate',
      data: {'regenerate_target': regenerateTarget},
      options: Options(headers: _headers),
    );
  }

  /// 시리즈 다음 권 생성
  Future<CreateBookResponse> createSeriesBook({
    required String characterId,
    required String topic,
    String? theme,
  }) async {
    final response = await _dio.post(
      '/v1/books/series',
      data: {
        'character_id': characterId,
        'topic': topic,
        if (theme != null) 'theme': theme,
      },
      options: Options(headers: _headers),
    );

    return CreateBookResponse.fromJson(response.data as Map<String, dynamic>);
  }

  // ==================== Characters ====================

  /// 캐릭터 저장
  Future<Character> createCharacter(CharacterCreate character) async {
    final response = await _dio.post(
      '/v1/characters',
      data: character.toJson(),
      options: Options(headers: _headers),
    );

    return Character.fromJson(response.data as Map<String, dynamic>);
  }

  /// 캐릭터 목록
  Future<List<Character>> getCharacters() async {
    final response = await _dio.get(
      '/v1/characters',
      options: Options(headers: _headers),
    );

    final data = response.data as Map<String, dynamic>;
    return (data['characters'] as List<dynamic>)
        .map((c) => Character.fromJson(c as Map<String, dynamic>))
        .toList();
  }

  /// 캐릭터 상세
  Future<Character> getCharacter(String characterId) async {
    final response = await _dio.get(
      '/v1/characters/$characterId',
      options: Options(headers: _headers),
    );

    return Character.fromJson(response.data as Map<String, dynamic>);
  }

  /// 사진에서 캐릭터 생성
  Future<Map<String, dynamic>> createCharacterFromPhoto(
    File photo, {
    String? name,
    String style = 'cartoon',
  }) async {
    final formData = FormData.fromMap({
      'photo': await MultipartFile.fromFile(
        photo.path,
        filename: 'photo.jpg',
      ),
      if (name != null) 'name': name,
      'style': style,
    });

    final response = await _dio.post(
      '/v1/characters/from-photo',
      data: formData,
      options: Options(
        headers: _headers,
        contentType: 'multipart/form-data',
      ),
    );

    return response.data as Map<String, dynamic>;
  }

  /// 텍스트로 캐릭터 생성 (사진 없이)
  Future<Map<String, dynamic>> createCharacterFromText({
    required String name,
    required String age,
    required String traits,
    String style = 'cartoon',
  }) async {
    final formData = FormData.fromMap({
      'name': name,
      'age': age,
      'traits': traits,
      'style': style,
    });

    final response = await _dio.post(
      '/v1/characters/from-text',
      data: formData,
      options: Options(
        headers: _headers,
        contentType: 'multipart/form-data',
      ),
    );

    return response.data as Map<String, dynamic>;
  }

  // ==================== Library ====================

  /// 내 서재
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
  }) async {
    final response = await _dio.get(
      '/v1/library',
      queryParameters: {
        'limit': limit,
        'offset': offset,
      },
      options: Options(headers: _headers),
    );

    return LibraryResponse.fromJson(response.data as Map<String, dynamic>);
  }

  /// 책 상세 (서재에서 조회)
  Future<BookResult> getBook(String bookId) async {
    final response = await _dio.get(
      '/v1/books/$bookId/detail',
      options: Options(headers: _headers),
    );

    return BookResult.fromJson(response.data as Map<String, dynamic>);
  }

  /// PDF 다운로드
  Future<List<int>> downloadPdf(String bookId) async {
    final response = await _dio.get<List<int>>(
      '/v1/books/$bookId/pdf',
      options: Options(
        headers: _headers,
        responseType: ResponseType.bytes,
      ),
    );

    final data = response.data;
    if (data == null) {
      throw DioException(
        requestOptions: response.requestOptions,
        message: 'PDF download returned empty response',
      );
    }
    return data;
  }

  /// 책 전체 오디오 생성 요청
  Future<void> generateBookAudio(String bookId) async {
    await _dio.post(
      '/v1/books/$bookId/audio',
      options: Options(headers: _headers),
    );
  }

  /// 페이지 오디오 URL 가져오기 (없으면 생성)
  Future<String> getPageAudioUrl(String bookId, int pageNumber) async {
    final response = await _dio.get(
      '/v1/books/$bookId/pages/$pageNumber/audio',
      options: Options(headers: _headers),
    );

    final data = response.data as Map<String, dynamic>;
    return data['audio_url'] as String;
  }

  // ==================== Credits ====================

  /// 크레딧 상태 조회
  Future<Map<String, dynamic>> getCreditsStatus() async {
    final response = await _dio.get(
      '/v1/credits/status',
      options: Options(headers: _headers),
    );

    return response.data as Map<String, dynamic>;
  }

  /// 크레딧 잔액 조회
  Future<int> getCreditsBalance() async {
    final response = await _dio.get(
      '/v1/credits/balance',
      options: Options(headers: _headers),
    );

    final data = response.data as Map<String, dynamic>;
    return data['credits'] as int;
  }

  /// 거래 내역 조회
  Future<List<dynamic>> getTransactions({int limit = 20, int offset = 0}) async {
    final response = await _dio.get(
      '/v1/credits/transactions',
      queryParameters: {'limit': limit, 'offset': offset},
      options: Options(headers: _headers),
    );

    return response.data as List<dynamic>;
  }

  /// 구독 시작
  Future<void> subscribe(String plan) async {
    await _dio.post(
      '/v1/credits/subscribe',
      data: {'plan': plan},
      options: Options(headers: _headers),
    );
  }

  /// 구독 취소
  Future<void> cancelSubscription() async {
    await _dio.post(
      '/v1/credits/cancel-subscription',
      options: Options(headers: _headers),
    );
  }

  /// 크레딧 추가 (구매)
  Future<int> addCredits(int amount, {String? transactionId}) async {
    final response = await _dio.post(
      '/v1/credits/add',
      data: {
        'amount': amount,
        if (transactionId != null) 'transaction_id': transactionId,
      },
      options: Options(headers: _headers),
    );

    final data = response.data as Map<String, dynamic>;
    return data['new_balance'] as int;
  }

  // ==================== Streak ====================

  /// 스트릭 정보 조회
  Future<Map<String, dynamic>> getStreakInfo() async {
    final response = await _dio.get(
      '/v1/streak/info',
      options: Options(headers: _headers),
    );

    return response.data as Map<String, dynamic>;
  }

  /// 오늘의 동화 조회
  Future<Map<String, dynamic>> getTodayStory() async {
    final response = await _dio.get(
      '/v1/streak/today',
      options: Options(headers: _headers),
    );

    return response.data as Map<String, dynamic>;
  }

  /// 읽기 기록
  Future<Map<String, dynamic>> recordReading({
    required String bookId,
    int readingTime = 0,
    bool completed = false,
  }) async {
    final response = await _dio.post(
      '/v1/streak/read',
      data: {
        'book_id': bookId,
        'reading_time': readingTime,
        'completed': completed,
      },
      options: Options(headers: _headers),
    );

    return response.data as Map<String, dynamic>;
  }

  /// 읽기 기록 히스토리
  Future<List<dynamic>> getReadingHistory({int days = 30}) async {
    final response = await _dio.get(
      '/v1/streak/history',
      queryParameters: {'days': days},
      options: Options(headers: _headers),
    );

    final data = response.data as Map<String, dynamic>;
    return data['history'] as List<dynamic>;
  }

  /// 스트릭 캘린더
  Future<Map<String, dynamic>> getStreakCalendar(int year, int month) async {
    final response = await _dio.get(
      '/v1/streak/calendar',
      queryParameters: {'year': year, 'month': month},
      options: Options(headers: _headers),
    );

    return response.data as Map<String, dynamic>;
  }
}

/// 책 생성 응답
class CreateBookResponse {
  final String jobId;
  final String status;

  CreateBookResponse({
    required this.jobId,
    required this.status,
  });

  factory CreateBookResponse.fromJson(Map<String, dynamic> json) {
    return CreateBookResponse(
      jobId: json['job_id'] as String,
      status: json['status'] as String,
    );
  }
}
