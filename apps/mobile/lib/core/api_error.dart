import 'package:dio/dio.dart';

/// Standardized API error
class ApiError implements Exception {
  final String code;
  final String message;
  final int statusCode;
  final dynamic details;
  final String? requestId;

  ApiError({
    required this.code,
    required this.message,
    required this.statusCode,
    this.details,
    this.requestId,
  });

  /// Create ApiError from DioException
  factory ApiError.fromDioException(DioException e) {
    final response = e.response;

    if (response != null) {
      final statusCode = response.statusCode ?? 500;
      final data = response.data;
      if (data is Map<String, dynamic> && data.containsKey('error')) {
        final error = data['error'];
        if (error is Map<String, dynamic>) {
          final envelopeCode = _nonEmptyString(error['code']) ??
              _nonEmptyString(error['error_code']);
          final envelopeMessage = _nonEmptyString(error['message']);
          return ApiError(
            code: envelopeCode ?? _codeFromStatus(statusCode),
            message: envelopeMessage ??
                _messageFromDetail(data['detail']) ??
                '알 수 없는 오류가 발생했습니다.',
            statusCode: statusCode,
            details: error['details'] ?? _detailsFromDetail(data['detail']),
            requestId: _nonEmptyString(data['request_id']),
          );
        }
      }

      if (data is Map<String, dynamic> && data.containsKey('detail')) {
        return ApiError(
          code: _codeFromStatus(statusCode),
          message: _messageFromDetail(data['detail']) ?? '요청 처리 중 오류가 발생했습니다.',
          statusCode: statusCode,
          details: _detailsFromDetail(data['detail']),
          requestId: _nonEmptyString(data['request_id']),
        );
      }

      // Fallback for non-standard error responses
      return ApiError(
        code: _codeFromStatus(statusCode),
        message: data?.toString() ?? '서버 오류가 발생했습니다.',
        statusCode: statusCode,
        details: data is Map<String, dynamic> ? data : null,
        requestId: data is Map<String, dynamic>
            ? _nonEmptyString(data['request_id'])
            : null,
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

  static String _codeFromStatus(int statusCode) {
    switch (statusCode) {
      case 400:
        return 'BAD_REQUEST';
      case 401:
        return 'UNAUTHORIZED';
      case 402:
        return 'PAYMENT_REQUIRED';
      case 403:
        return 'FORBIDDEN';
      case 404:
        return 'NOT_FOUND';
      case 409:
        return 'CONFLICT';
      case 422:
        return 'VALIDATION_ERROR';
      case 429:
        return 'RATE_LIMIT_EXCEEDED';
      case 502:
        return 'BAD_GATEWAY';
      case 503:
        return 'SERVICE_UNAVAILABLE';
      case 504:
        return 'GATEWAY_TIMEOUT';
      default:
        if (statusCode >= 500) return 'INTERNAL_ERROR';
        return 'API_ERROR';
    }
  }

  static String? _messageFromDetail(dynamic detail) {
    if (detail is String && detail.isNotEmpty) {
      return detail;
    }
    if (detail is Map<String, dynamic>) {
      final msg = _nonEmptyString(detail['message']) ??
          _nonEmptyString(detail['detail']);
      if (msg != null) {
        return msg;
      }

      final error = detail['error'];
      if (error is Map<String, dynamic>) {
        final nestedMessage = _nonEmptyString(error['message']);
        if (nestedMessage != null) {
          return nestedMessage;
        }
      }
      return '요청 처리 중 오류가 발생했습니다.';
    }
    if (detail is List) {
      return '입력 정보를 확인해주세요.';
    }
    return null;
  }

  static dynamic _detailsFromDetail(dynamic detail) {
    if (detail is Map<String, dynamic> || detail is List) {
      return detail;
    }
    return null;
  }

  static String? _nonEmptyString(dynamic value) {
    if (value is! String) return null;
    final trimmed = value.trim();
    return trimmed.isNotEmpty ? trimmed : null;
  }

  /// User-friendly error message
  String get userMessage {
    switch (code) {
      case 'NOT_FOUND':
        return message;
      case 'VALIDATION_ERROR':
        return '입력 정보를 확인해주세요.';
      case 'BAD_REQUEST':
        return message;
      case 'UNAUTHORIZED':
        return '로그인이 필요합니다.';
      case 'FORBIDDEN':
        return '접근 권한이 없습니다.';
      case 'PAYMENT_REQUIRED':
        return message;
      case 'INTERNAL_ERROR':
        return '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.';
      case 'RATE_LIMIT_EXCEEDED':
        return '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.';
      case 'BAD_GATEWAY':
      case 'SERVICE_UNAVAILABLE':
      case 'GATEWAY_TIMEOUT':
        return '서버가 일시적으로 불안정합니다. 잠시 후 다시 시도해주세요.';
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
