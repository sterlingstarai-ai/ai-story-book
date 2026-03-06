import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';
import '../core/api_error.dart';
import '../core/app_telemetry.dart';
import '../models/models.dart';

/// API 클라이언트
class ApiClient {
  static const Uuid _uuid = Uuid();
  final Dio _dio;
  final String _userKey;
  final String? _profileId;

  ApiClient({
    required String baseUrl,
    required String userKey,
    String? profileId,
    bool enableLogging = kDebugMode,
  })  : _userKey = userKey,
        _profileId = profileId,
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

    // Request correlation + error handling interceptor
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        final requestId = _uuid.v4();
        options.headers['X-Request-ID'] = requestId;
        options.extra['requestId'] = requestId;
        AppTelemetry.logInfo(
          'api_request',
          data: {
            'requestId': requestId,
            'method': options.method,
            'path': options.path,
          },
        );
        handler.next(options);
      },
      onResponse: (response, handler) {
        AppTelemetry.logInfo(
          'api_response',
          data: {
            'requestId': response.requestOptions.extra['requestId'],
            'serverRequestId': response.headers.value('x-request-id'),
            'statusCode': response.statusCode,
            'path': response.requestOptions.path,
          },
        );
        handler.next(response);
      },
      onError: (error, handler) {
        final apiError = ApiError.fromDioException(error);
        AppTelemetry.recordError(
          apiError,
          error.stackTrace,
          context: 'api_error',
          data: {
            'requestId': error.requestOptions.extra['requestId'],
            'serverRequestId': apiError.requestId,
            'path': error.requestOptions.path,
            'statusCode': apiError.statusCode,
            'code': apiError.code,
          },
        );
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
        if (_profileId != null && _profileId!.isNotEmpty)
          'X-Profile-Id': _profileId!,
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
        .asMap()
        .entries
        .map((entry) => Character.fromJson(
              _asJsonMap(
                entry.value,
                context: '/v1/characters.characters[${entry.key}]',
              ),
            ))
        .toList();
  }

  /// 캐릭터 상세
  Future<Character> getCharacter(String characterId) async {
    final response = await _dio.get(
      '/v1/characters/$characterId',
      options: Options(headers: _headers),
    );

    return Character.fromJson(
      _asJsonMap(response.data,
          context: '/v1/characters/$characterId response'),
    );
  }

  /// 캐릭터 삭제
  Future<void> deleteCharacter(String characterId) async {
    await _dio.delete(
      '/v1/characters/$characterId',
      options: Options(headers: _headers),
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

    return _asJsonMap(response.data,
        context: '/v1/characters/from-photo response');
  }

  /// 아이 그림에서 캐릭터 생성 + 시트 생성
  Future<Map<String, dynamic>> createCharacterFromDrawing(
    File drawing, {
    String? name,
    String style = 'storybook_crayon',
    bool generateSheet = true,
  }) async {
    final formData = FormData.fromMap({
      'drawing': await MultipartFile.fromFile(
        drawing.path,
        filename: 'drawing.jpg',
      ),
      if (name != null) 'name': name,
      'style': style,
      'generate_sheet': generateSheet,
    });

    final response = await _dio.post(
      '/v1/characters/from-drawing',
      data: formData,
      options: Options(
        headers: _headers,
        contentType: 'multipart/form-data',
      ),
    );

    return _asJsonMap(
      response.data,
      context: '/v1/characters/from-drawing response',
    );
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

    return _asJsonMap(response.data,
        context: '/v1/characters/from-text response');
  }

  // ==================== Library ====================

  /// 내 서재
  Future<LibraryResponse> getLibrary({
    int limit = 20,
    int offset = 0,
    String? cursor,
    String? style,
    String? targetAge,
    String sort = 'newest',
  }) async {
    final response = await _dio.get(
      '/v1/library',
      queryParameters: {
        'limit': limit,
        'offset': offset,
        if (cursor != null) 'cursor': cursor,
        if (style != null && style.isNotEmpty) 'style': style,
        if (targetAge != null && targetAge.isNotEmpty) 'target_age': targetAge,
        'sort': sort,
      },
      options: Options(headers: _headers),
    );

    return LibraryResponse.fromJson(
      _asJsonMap(response.data, context: '/v1/library response'),
    );
  }

  /// 책 제목 수정
  Future<LibraryBook> updateBookTitle(String bookId, String title) async {
    final response = await _dio.patch(
      '/v1/library/$bookId',
      data: {'title': title},
      options: Options(headers: _headers),
    );
    return LibraryBook.fromJson(
      _asJsonMap(response.data, context: '/v1/library/$bookId patch response'),
    );
  }

  /// 서재 책 삭제
  Future<void> deleteBook(String bookId) async {
    await _dio.delete(
      '/v1/library/$bookId',
      options: Options(headers: _headers),
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
  Future<String> getPageAudioUrl(
    String bookId,
    int pageNumber, {
    String language = 'ko',
  }) async {
    final response = await _dio.get(
      '/v1/books/$bookId/pages/$pageNumber/audio',
      queryParameters: {'language': language},
      options: Options(headers: _headers),
    );

    final data = _asJsonMap(
      response.data,
      context: '/v1/books/$bookId/pages/$pageNumber/audio response',
    );
    return _asString(data['audio_url'], field: 'audio_url');
  }

  /// 사용자 데이터 전체 삭제
  Future<void> deleteMyData() async {
    await _dio.delete(
      '/v1/users/me',
      options: Options(headers: _headers),
    );
  }

  /// 프로필 목록
  Future<Map<String, dynamic>> getProfiles() async {
    final response = await _dio.get(
      '/v1/profiles',
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/profiles response');
  }

  /// 프로필 생성
  Future<Map<String, dynamic>> createProfile({
    required String name,
    required String ageBand,
    String? preferredTheme,
    bool? isDefault,
  }) async {
    final response = await _dio.post(
      '/v1/profiles',
      data: {
        'name': name,
        'age_band': ageBand,
        if (preferredTheme != null) 'preferred_theme': preferredTheme,
        if (isDefault != null) 'is_default': isDefault,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/profiles create response');
  }

  /// 프로필 삭제
  Future<void> deleteProfile(String profileId) async {
    await _dio.delete(
      '/v1/profiles/$profileId',
      options: Options(headers: _headers),
    );
  }

  /// 프로필 수정
  Future<Map<String, dynamic>> updateProfile(
    String profileId, {
    String? name,
    String? ageBand,
    String? preferredTheme,
    String? avatarUrl,
    bool? isDefault,
  }) async {
    final payload = <String, dynamic>{};
    if (name != null) {
      payload['name'] = name;
    }
    if (ageBand != null) {
      payload['age_band'] = ageBand;
    }
    if (preferredTheme != null) {
      payload['preferred_theme'] = preferredTheme;
    }
    if (avatarUrl != null) {
      payload['avatar_url'] = avatarUrl;
    }
    if (isDefault != null) {
      payload['is_default'] = isDefault;
    }

    final response = await _dio.patch(
      '/v1/profiles/$profileId',
      data: payload,
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/profiles/$profileId update');
  }

  /// 설정 조회
  Future<Map<String, dynamic>> getSettings() async {
    final response = await _dio.get(
      '/v1/settings',
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/settings response');
  }

  /// 설정 업데이트
  Future<void> patchSettings(Map<String, dynamic> payload) async {
    await _dio.patch(
      '/v1/settings',
      data: payload,
      options: Options(headers: _headers),
    );
  }

  /// IAP 검증
  Future<Map<String, dynamic>> verifyIap(Map<String, dynamic> payload) async {
    final response = await _dio.post(
      '/v1/iap/verify',
      data: payload,
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/iap/verify response');
  }

  /// 리워드 광고 보상 완료 처리
  Future<Map<String, dynamic>> completeRewardAd({
    String adNetwork = 'admob',
    String? adUnitId,
  }) async {
    final response = await _dio.post(
      '/v1/rewards/ad-complete',
      data: {
        'ad_network': adNetwork,
        if (adUnitId != null) 'ad_unit_id': adUnitId,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data,
        context: '/v1/rewards/ad-complete response');
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

    final data =
        _asJsonMap(response.data, context: '/v1/credits/balance response');
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

    return _asJsonList(response.data,
        context: '/v1/credits/transactions response');
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

    final data =
        _asJsonMap(response.data, context: '/v1/streak/history response');
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

  /// 읽기 리포트 (부모 대시보드)
  Future<Map<String, dynamic>> getReadingReport({
    String period = 'weekly',
  }) async {
    final response = await _dio.get(
      '/v1/streak/report',
      queryParameters: {'period': period},
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/streak/report response');
  }

  /// 가족 음성 프로필 목록
  Future<Map<String, dynamic>> getVoiceProfiles() async {
    final response = await _dio.get(
      '/v1/voice-profiles',
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data, context: '/v1/voice-profiles response');
  }

  /// 가족 음성 샘플 업로드
  Future<Map<String, dynamic>> uploadVoiceSample(
    File sample, {
    String? fileName,
  }) async {
    final formData = FormData.fromMap({
      'sample': await MultipartFile.fromFile(
        sample.path,
        filename: fileName ?? 'voice-sample.m4a',
      ),
    });
    final response = await _dio.post(
      '/v1/voice-profiles/upload-sample',
      data: formData,
      options: Options(
        headers: _headers,
        contentType: 'multipart/form-data',
      ),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/voice-profiles/upload-sample response',
    );
  }

  /// 가족 음성 프로필 생성
  Future<Map<String, dynamic>> createVoiceProfile({
    required String label,
    required String sampleAudioUrl,
    String? relationship,
    String? providerVoiceId,
    required bool consented,
  }) async {
    final response = await _dio.post(
      '/v1/voice-profiles',
      data: {
        'label': label,
        'sample_audio_url': sampleAudioUrl,
        if (relationship != null) 'relationship': relationship,
        if (providerVoiceId != null) 'provider_voice_id': providerVoiceId,
        'consented': consented,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(response.data,
        context: '/v1/voice-profiles create response');
  }

  /// 가족 음성 프로필 수정
  Future<Map<String, dynamic>> updateVoiceProfile(
    String profileId, {
    String? label,
    String? sampleAudioUrl,
    String? relationship,
    String? providerVoiceId,
    bool? consented,
    bool? active,
  }) async {
    final payload = <String, dynamic>{};
    if (label != null) {
      payload['label'] = label;
    }
    if (sampleAudioUrl != null) {
      payload['sample_audio_url'] = sampleAudioUrl;
    }
    if (relationship != null) {
      payload['relationship'] = relationship;
    }
    if (providerVoiceId != null) {
      payload['provider_voice_id'] = providerVoiceId;
    }
    if (consented != null) {
      payload['consented'] = consented;
    }
    if (active != null) {
      payload['active'] = active;
    }

    final response = await _dio.patch(
      '/v1/voice-profiles/$profileId',
      data: payload,
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/voice-profiles/$profileId patch response',
    );
  }

  /// 가족 음성 프로필 동의 철회
  Future<Map<String, dynamic>> revokeVoiceProfileConsent(
      String profileId) async {
    final response = await _dio.post(
      '/v1/voice-profiles/$profileId/revoke-consent',
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/voice-profiles/$profileId/revoke-consent response',
    );
  }

  /// 가족 음성 프로필 삭제
  Future<void> deleteVoiceProfile(String profileId) async {
    await _dio.delete(
      '/v1/voice-profiles/$profileId',
      options: Options(headers: _headers),
    );
  }

  /// 분기형 스토리 그래프 조회
  Future<Map<String, dynamic>> getBranchStoryGraph(String bookId) async {
    final response = await _dio.get(
      '/v1/branch/books/$bookId/graph',
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/branch/books/$bookId/graph response',
    );
  }

  /// 분기형 스토리 그래프 초기화
  Future<Map<String, dynamic>> initializeBranchStory(
    String bookId, {
    required List<Map<String, dynamic>> nodes,
    bool overwrite = false,
  }) async {
    final response = await _dio.post(
      '/v1/branch/books/$bookId/initialize',
      data: {
        'nodes': nodes,
        'overwrite': overwrite,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/branch/books/$bookId/initialize response',
    );
  }

  /// 분기형 스토리 선택지 진행
  Future<Map<String, dynamic>> chooseBranchStoryOption(
    String bookId, {
    required String currentNodeKey,
    String? optionText,
    String? toNodeKey,
  }) async {
    final payload = <String, dynamic>{
      'current_node_key': currentNodeKey,
    };
    if (optionText != null) {
      payload['option_text'] = optionText;
    }
    if (toNodeKey != null) {
      payload['to_node_key'] = toNodeKey;
    }

    final response = await _dio.post(
      '/v1/branch/books/$bookId/choose',
      data: payload,
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/branch/books/$bookId/choose response',
    );
  }

  /// 발음 연습 평가
  Future<Map<String, dynamic>> evaluatePronunciation({
    required String bookId,
    required int pageNumber,
    required String transcript,
    required String expectedText,
    String? audioUrl,
  }) async {
    final response = await _dio.post(
      '/v1/pronunciation/evaluate',
      data: {
        'book_id': bookId,
        'page_number': pageNumber,
        'transcript': transcript,
        'expected_text': expectedText,
        if (audioUrl != null) 'audio_url': audioUrl,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/pronunciation/evaluate response',
    );
  }

  /// 발음 연습 평가 (오디오 업로드 기반 STT)
  Future<Map<String, dynamic>> evaluatePronunciationAudio({
    required File audioFile,
    required String expectedText,
    String? bookId,
    int? pageNumber,
    String language = 'ko',
  }) async {
    final formData = FormData.fromMap({
      'audio_file': await MultipartFile.fromFile(
        audioFile.path,
        filename: audioFile.path.split('/').last,
      ),
      'expected_text': expectedText,
      if (bookId != null) 'book_id': bookId,
      if (pageNumber != null) 'page_number': pageNumber,
      'language': language,
    });
    final response = await _dio.post(
      '/v1/pronunciation/evaluate-audio',
      data: formData,
      options: Options(
        headers: _headers,
        contentType: 'multipart/form-data',
      ),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/pronunciation/evaluate-audio response',
    );
  }

  /// POD 주문 생성
  Future<Map<String, dynamic>> createPodOrder({
    required String bookId,
    required int quantity,
    required Map<String, dynamic> shippingAddress,
  }) async {
    final response = await _dio.post(
      '/v1/pod/orders',
      data: {
        'book_id': bookId,
        'quantity': quantity,
        'shipping_address': shippingAddress,
      },
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/pod/orders response',
    );
  }

  /// POD 주문 조회
  Future<Map<String, dynamic>> getPodOrder(String orderId) async {
    final response = await _dio.get(
      '/v1/pod/orders/$orderId',
      options: Options(headers: _headers),
    );
    return _asJsonMap(
      response.data,
      context: '/v1/pod/orders/$orderId response',
    );
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
      jobId: _readRequiredString(json, 'job_id'),
      status: _readRequiredString(json, 'status'),
    );
  }

  static String _readRequiredString(Map<String, dynamic> json, String field) {
    final value = json[field];
    if (value is String) {
      return value;
    }
    if (value == null) {
      throw FormatException('Missing required field: $field');
    }
    return value.toString();
  }
}
