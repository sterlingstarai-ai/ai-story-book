import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
