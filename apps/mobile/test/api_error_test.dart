import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:flutter/widgets.dart';


import 'package:ai_story_book/core/api_error.dart';

void main() {
  group('ApiError.fromDioException', () {
    test('parses standardized error envelope', () {
      final requestOptions = RequestOptions(path: '/v1/books/abc');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 404,
        data: {
          'detail': 'Book not found',
          'error': {
            'code': 'NOT_FOUND',
            'message': 'Book not found',
            'details': {'resource': 'book', 'id': 'abc'},
          },
        },
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'NOT_FOUND');
      expect(apiError.message, 'Book not found');
      expect(apiError.statusCode, 404);
      expect(apiError.details, {'resource': 'book', 'id': 'abc'});
    });

    test('parses FastAPI detail string fallback', () {
      final requestOptions = RequestOptions(path: '/v1/library');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 400,
        data: {'detail': 'Invalid X-User-Key header'},
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'BAD_REQUEST');
      expect(apiError.message, 'Invalid X-User-Key header');
      expect(apiError.statusCode, 400);
    });

    test('parses validation detail list', () {
      final requestOptions = RequestOptions(path: '/v1/books');
      final detail = [
        {
          'loc': ['body', 'topic'],
          'msg': 'Field required',
          'type': 'missing',
        }
      ];

      final response = Response(
        requestOptions: requestOptions,
        statusCode: 422,
        data: {'detail': detail},
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'VALIDATION_ERROR');
      expect(apiError.message, '입력 정보를 확인해주세요.');
      expect(apiError.statusCode, 422);
      expect(apiError.details, detail);
    });

    test('maps timeout without response', () {
      final requestOptions = RequestOptions(path: '/v1/books');

      final dioError = DioException(
        requestOptions: requestOptions,
        type: DioExceptionType.connectionTimeout,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'TIMEOUT');
      expect(apiError.statusCode, 0);
    });

    test('maps 503 fallback to service unavailable code', () {
      final requestOptions = RequestOptions(path: '/v1/books');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 503,
        data: {'detail': 'temporarily unavailable'},
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'SERVICE_UNAVAILABLE');
      expect(apiError.message, 'temporarily unavailable');
      expect(
        apiError.userMessage,
        '서버가 일시적으로 불안정합니다. 잠시 후 다시 시도해주세요.',
      );
    });

    test('handles non-string envelope code without cast error', () {
      final requestOptions = RequestOptions(path: '/v1/books');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 500,
        data: {
          'error': {
            'code': 1234,
            'message': 'broken envelope code type',
          },
        },
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'INTERNAL_ERROR');
      expect(apiError.message, 'broken envelope code type');
      expect(apiError.statusCode, 500);
    });

    test('reads nested error message from detail map fallback', () {
      final requestOptions = RequestOptions(path: '/v1/books');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 503,
        data: {
          'detail': {
            'error': {'message': 'upstream unavailable'},
          },
        },
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'SERVICE_UNAVAILABLE');
      expect(apiError.message, 'upstream unavailable');
      expect(apiError.statusCode, 503);
    });

    test('preserves payment required message for upgrade guidance', () {
      final requestOptions = RequestOptions(path: '/v1/books');
      final response = Response(
        requestOptions: requestOptions,
        statusCode: 402,
        data: {
          'detail': '무료 플랜은 월 2권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요.',
          'error': {
            'code': 'PAYMENT_REQUIRED',
            'message': '무료 플랜은 월 2권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요.',
          },
        },
      );

      final dioError = DioException(
        requestOptions: requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );

      final apiError = ApiError.fromDioException(dioError);

      expect(apiError.code, 'PAYMENT_REQUIRED');
      expect(
        apiError.userMessage,
        '무료 플랜은 월 2권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요.',
      );
    });
  });

  group('M15 localizedMessage', () {
    test('network/http codes localize; en/ja show no Korean', () async {
      final en = await AppLocalizations.delegate.load(const Locale('en'));
      final ja = await AppLocalizations.delegate.load(const Locale('ja'));

      final conn = ApiError(code: 'CONNECTION_ERROR', message: '인터넷 연결을 확인해주세요.', statusCode: 0);
      expect(conn.localizedMessage(en), en.errorConnection);
      expect(conn.localizedMessage(en), isNot(contains('인터넷')));
      expect(conn.localizedMessage(ja), ja.errorConnection);

      final val = ApiError(code: 'VALIDATION_ERROR', message: 'x', statusCode: 422);
      expect(val.localizedMessage(en), en.errorValidation);

      // M2: ApiError 를 손으로 만들면 서버가 실제로 보내는 코드와 어긋나도 통과한다
      // (실제로 서버는 소문자 `rate_limit_exceeded` 를 보내고 있었고, 이 테스트는 그동안
      // green 이었다 = false-green). 아래 '실제 서버 429 봉투' 테스트가 정본이다.
      final rate = ApiError(code: 'RATE_LIMIT_EXCEEDED', message: 'x', statusCode: 429);
      expect(rate.localizedMessage(ja), ja.errorRateLimit);
    });

    test('실제 서버 429 봉투를 파싱해도 en/ja 에 한국어가 새지 않는다 (M2)', () async {
      final en = await AppLocalizations.delegate.load(const Locale('en'));
      final ja = await AppLocalizations.delegate.load(const Locale('ja'));

      // apps/api/src/core/exceptions.py RateLimitError 가 만드는 실제 응답 본문.
      // 이 리터럴이 서버 계약과 어긋나면 테스트가 깨져야 한다(수제 ApiError 금지).
      final response = Response(
        requestOptions: RequestOptions(path: '/v1/credits/balance'),
        statusCode: 429,
        headers: Headers.fromMap({
          'retry-after': ['60'],
        }),
        data: {
          'detail': '요청 한도 초과. 60초 후 다시 시도해주세요.',
          'error': {
            'code': 'RATE_LIMIT_EXCEEDED',
            'message': '요청 한도 초과. 60초 후 다시 시도해주세요.',
            'details': {'retry_after': 60},
          },
          'request_id': 'req-429',
        },
      );
      final apiError = ApiError.fromDioException(
        DioException(
          requestOptions: response.requestOptions,
          response: response,
          type: DioExceptionType.badResponse,
        ),
      );

      expect(apiError.code, 'RATE_LIMIT_EXCEEDED',
          reason: '서버 봉투 코드가 클라이언트 분기 키와 일치해야 한다');
      expect(apiError.localizedMessage(en), en.errorRateLimit);
      expect(apiError.localizedMessage(en), isNot(contains('한도')));
      expect(apiError.localizedMessage(ja), ja.errorRateLimit);
      expect(apiError.localizedMessage(ja), isNot(contains('한도')));
      expect((apiError.details as Map)['retry_after'], 60);
    });

    test('402 분기는 메시지가 아니라 details.reason 으로 결정된다 (M5)', () {
      ApiError build(String? reason, String message) => ApiError.fromDioException(
            DioException(
              requestOptions: RequestOptions(path: '/v1/books'),
              response: Response(
                requestOptions: RequestOptions(path: '/v1/books'),
                statusCode: 402,
                data: {
                  'detail': message,
                  'error': {
                    'code': 'PAYMENT_REQUIRED',
                    'message': message,
                    if (reason != null) 'details': {'reason': reason},
                  },
                },
              ),
              type: DioExceptionType.badResponse,
            ),
          );

      // 서버가 402 를 영어로 로컬라이즈해도 분기가 유지되어야 한다(핵심).
      final localizedLimit = build(
        'free_plan_monthly_limit',
        'Free plan allows 2 books per month. Please upgrade.',
      );
      expect(localizedLimit.isPlanUpgradeRequired, isTrue);
      expect(localizedLimit.paymentReason, 'free_plan_monthly_limit');

      expect(build('free_plan_style', 'x').isPlanUpgradeRequired, isTrue);
      expect(build('free_plan_feature', 'x').isPlanUpgradeRequired, isTrue);

      // 크레딧 부족은 업그레이드가 아니라 충전 안내다.
      expect(build('insufficient_credits', '크레딧이 부족합니다.').isPlanUpgradeRequired,
          isFalse);
      expect(build('credit_charge_failed', 'x').isPlanUpgradeRequired, isFalse);

      // 402 가 아닌 코드는 무조건 false.
      final notPayment = ApiError(code: 'NOT_FOUND', message: '플랜', statusCode: 404);
      expect(notPayment.isPlanUpgradeRequired, isFalse);
    });

    test('server-message codes (NOT_FOUND/PAYMENT_REQUIRED) keep the specific message', () async {
      final en = await AppLocalizations.delegate.load(const Locale('en'));
      final nf = ApiError(code: 'NOT_FOUND', message: 'Book not found', statusCode: 404);
      expect(nf.localizedMessage(en), 'Book not found');
      final pay = ApiError(code: 'PAYMENT_REQUIRED', message: '무료 플랜은 월 2권까지 생성할 수 있습니다.', statusCode: 402);
      expect(pay.localizedMessage(en), '무료 플랜은 월 2권까지 생성할 수 있습니다.');
    });
  });

}
