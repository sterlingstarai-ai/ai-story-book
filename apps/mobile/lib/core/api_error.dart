import 'package:dio/dio.dart';

/// Standardized API error
class ApiError implements Exception {
  final String code;
  final String message;
  final int statusCode;
  final dynamic details;

  ApiError({
    required this.code,
    required this.message,
    required this.statusCode,
    this.details,
  });

  /// Create ApiError from DioException
  factory ApiError.fromDioException(DioException e) {
    final response = e.response;

    if (response != null) {
      final data = response.data;
      if (data is Map<String, dynamic> && data.containsKey('error')) {
        final error = data['error'] as Map<String, dynamic>;
        return ApiError(
          code: error['code'] as String? ?? 'UNKNOWN_ERROR',
          message: error['message'] as String? ?? '알 수 없는 오류가 발생했습니다.',
          statusCode: response.statusCode ?? 500,
          details: error['details'],
        );
      }
      // Fallback for non-standard error responses
      return ApiError(
        code: 'API_ERROR',
        message: data?.toString() ?? '서버 오류가 발생했습니다.',
        statusCode: response.statusCode ?? 500,
      );
    }

    // Network or timeout errors
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return ApiError(
          code: 'TIMEOUT',
          message: '요청 시간이 초과되었습니다. 다시 시도해주세요.',
          statusCode: 0,
        );
      case DioExceptionType.connectionError:
        return ApiError(
          code: 'CONNECTION_ERROR',
          message: '인터넷 연결을 확인해주세요.',
          statusCode: 0,
        );
      case DioExceptionType.cancel:
        return ApiError(
          code: 'CANCELLED',
          message: '요청이 취소되었습니다.',
          statusCode: 0,
        );
      default:
        return ApiError(
          code: 'NETWORK_ERROR',
          message: '네트워크 오류가 발생했습니다.',
          statusCode: 0,
        );
    }
  }

  /// User-friendly error message
  String get userMessage {
    switch (code) {
      case 'NOT_FOUND':
        return message;
      case 'VALIDATION_ERROR':
        return '입력 정보를 확인해주세요.';
      case 'FORBIDDEN':
        return '접근 권한이 없습니다.';
      case 'PAYMENT_REQUIRED':
        return '크레딧이 부족합니다.';
      case 'RATE_LIMIT_EXCEEDED':
        return '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.';
      case 'TIMEOUT':
        return message;
      case 'CONNECTION_ERROR':
        return message;
      default:
        return message;
    }
  }

  @override
  String toString() => 'ApiError: [$code] $message (status: $statusCode)';
}
