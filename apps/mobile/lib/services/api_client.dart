import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../core/api_error.dart';
import '../models/models.dart';

/// API 클라이언트
class ApiClient {
  final Dio _dio;
  final String _userKey;

  ApiClient({
    required String baseUrl,
    required String userKey,
    bool enableLogging = kDebugMode,
  })  : _userKey = userKey,
        _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 30),
          receiveTimeout: const Duration(seconds: 30),
          headers: {
            'Content-Type': 'application/json',
          },
        )) {
    if (enableLogging) {
      _dio.interceptors.add(LogInterceptor(
        requestBody: true,
        responseBody: true,
      ));
    }

    // Error handling interceptor
    _dio.interceptors.add(InterceptorsWrapper(
      onError: (error, handler) {
        // Convert to standardized ApiError
        final apiError = ApiError.fromDioException(error);
        handler.reject(
          error.copyWith(
            error: apiError,
            message: apiError.userMessage,
          ),
        );
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

    return CreateBookResponse.fromJson(
      _asJsonMap(response.data, context: '/v1/books response'),
    );
  }

  /// 책 생성 상태 조회
  Future<JobStatus> getBookStatus(String jobId) async {
    final response = await _dio.get(
      '/v1/books/$jobId',
      options: Options(headers: _headers),
    );

    return JobStatus.fromJson(
      _asJsonMap(response.data, context: '/v1/books/$jobId response'),
    );
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

    return CreateBookResponse.fromJson(
      _asJsonMap(response.data, context: '/v1/books/series response'),
    );
  }

  // ==================== Characters ====================

  /// 캐릭터 저장
  Future<Character> createCharacter(CharacterCreate character) async {
    final response = await _dio.post(
      '/v1/characters',
      data: character.toJson(),
      options: Options(headers: _headers),
    );

    return Character.fromJson(
      _asJsonMap(response.data, context: '/v1/characters create response'),
    );
  }

  /// 캐릭터 목록
  Future<List<Character>> getCharacters() async {
    final response = await _dio.get(
      '/v1/characters',
      options: Options(headers: _headers),
    );

    final data = _asJsonMap(response.data, context: '/v1/characters response');
    final characters = _asJsonList(
      data['characters'],
      context: '/v1/characters.characters',
    );

    return characters
        .whereType<Map>()
        .map((c) => Character.fromJson(Map<String, dynamic>.from(c)))
        .toList();
  }

  /// 캐릭터 상세
  Future<Character> getCharacter(String characterId) async {
    final response = await _dio.get(
      '/v1/characters/$characterId',
      options: Options(headers: _headers),
    );

    return Character.fromJson(
      _asJsonMap(response.data, context: '/v1/characters/$characterId response'),
    );
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

    return _asJsonMap(response.data, context: '/v1/characters/from-photo response');
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

    return _asJsonMap(response.data, context: '/v1/characters/from-text response');
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

    return LibraryResponse.fromJson(
      _asJsonMap(response.data, context: '/v1/library response'),
    );
  }

  /// 책 상세 (서재에서 조회)
  Future<BookResult> getBook(String bookId) async {
    final response = await _dio.get(
      '/v1/books/$bookId/detail',
      options: Options(headers: _headers),
    );

    return BookResult.fromJson(
      _asJsonMap(response.data, context: '/v1/books/$bookId/detail response'),
    );
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

    final data = _asJsonMap(
      response.data,
      context: '/v1/books/$bookId/pages/$pageNumber/audio response',
    );
    return _asString(data['audio_url'], field: 'audio_url');
  }

  // ==================== Credits ====================

  /// 크레딧 상태 조회
  Future<Map<String, dynamic>> getCreditsStatus() async {
    final response = await _dio.get(
      '/v1/credits/status',
      options: Options(headers: _headers),
    );

    return _asJsonMap(response.data, context: '/v1/credits/status response');
  }

  /// 크레딧 잔액 조회
  Future<int> getCreditsBalance() async {
    final response = await _dio.get(
      '/v1/credits/balance',
      options: Options(headers: _headers),
    );

    final data = _asJsonMap(response.data, context: '/v1/credits/balance response');
    return _asInt(data['credits'], field: 'credits');
  }

  /// 거래 내역 조회
  Future<List<dynamic>> getTransactions(
      {int limit = 20, int offset = 0}) async {
    final response = await _dio.get(
      '/v1/credits/transactions',
      queryParameters: {'limit': limit, 'offset': offset},
      options: Options(headers: _headers),
    );

    return _asJsonList(response.data, context: '/v1/credits/transactions response');
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

  /// 크레딧 추가 (관리자 결제 확정용)
  /// 서버 정책상 관리자 키와 외부 결제 transactionId가 필요합니다.
  Future<int> addCredits(
    int amount, {
    required String transactionId,
    required String adminKey,
  }) async {
    final response = await _dio.post(
      '/v1/credits/add',
      data: {
        'amount': amount,
        'transaction_id': transactionId,
      },
      options: Options(headers: {
        ..._headers,
        'X-Admin-Key': adminKey,
      }),
    );

    final data = _asJsonMap(response.data, context: '/v1/credits/add response');
    return _asInt(data['new_balance'], field: 'new_balance');
  }

  // ==================== Streak ====================

  /// 스트릭 정보 조회
  Future<Map<String, dynamic>> getStreakInfo() async {
    final response = await _dio.get(
      '/v1/streak/info',
      options: Options(headers: _headers),
    );

    return _asJsonMap(response.data, context: '/v1/streak/info response');
  }

  /// 오늘의 동화 조회
  Future<Map<String, dynamic>> getTodayStory() async {
    final response = await _dio.get(
      '/v1/streak/today',
      options: Options(headers: _headers),
    );

    return _asJsonMap(response.data, context: '/v1/streak/today response');
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

    return _asJsonMap(response.data, context: '/v1/streak/read response');
  }

  /// 읽기 기록 히스토리
  Future<List<dynamic>> getReadingHistory({int days = 30}) async {
    final response = await _dio.get(
      '/v1/streak/history',
      queryParameters: {'days': days},
      options: Options(headers: _headers),
    );

    final data = _asJsonMap(response.data, context: '/v1/streak/history response');
    return _asJsonList(data['history'], context: '/v1/streak/history.history');
  }

  /// 스트릭 캘린더
  Future<Map<String, dynamic>> getStreakCalendar(int year, int month) async {
    final response = await _dio.get(
      '/v1/streak/calendar',
      queryParameters: {'year': year, 'month': month},
      options: Options(headers: _headers),
    );

    return _asJsonMap(response.data, context: '/v1/streak/calendar response');
  }

  Map<String, dynamic> _asJsonMap(dynamic value, {required String context}) {
    if (value is Map<String, dynamic>) {
      return value;
    }
    if (value is Map) {
      final mapped = <String, dynamic>{};
      for (final entry in value.entries) {
        if (entry.key == null) {
          continue;
        }
        mapped[entry.key.toString()] = entry.value;
      }
      return mapped;
    }
    throw FormatException('Expected JSON object for $context');
  }

  List<dynamic> _asJsonList(dynamic value, {required String context}) {
    if (value is List<dynamic>) {
      return value;
    }
    if (value is List) {
      return List<dynamic>.from(value);
    }
    throw FormatException('Expected JSON array for $context');
  }

  int _asInt(dynamic value, {required String field}) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      final parsed = int.tryParse(value);
      if (parsed != null) {
        return parsed;
      }
    }
    throw FormatException('Expected integer for $field');
  }

  String _asString(dynamic value, {required String field}) {
    if (value is String) {
      return value;
    }
    if (value == null) {
      throw FormatException('Expected string for $field');
    }
    return value.toString();
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
