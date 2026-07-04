import 'dart:io';

import 'package:kakao_flutter_sdk_share/kakao_flutter_sdk_share.dart';

import 'service_availability.dart';

class KakaoShareResult {
  const KakaoShareResult({
    required this.shared,
    this.reason,
  });

  final bool shared;
  final String? reason;
}

class KakaoShareService {
  KakaoShareService();

  static bool _initialized = false;

  static const _nativeAppKey = String.fromEnvironment('KAKAO_NATIVE_APP_KEY');
  static const _webBaseUrl = String.fromEnvironment(
    'SHARE_WEB_BASE_URL',
    defaultValue: 'https://aistorybook.app/books',
  );

  Uri? get _shareBaseUri => Uri.tryParse(_webBaseUrl);

  bool get isConfigured =>
      _nativeAppKey.isNotEmpty &&
      _shareBaseUri != null &&
      _shareBaseUri!.hasScheme &&
      _shareBaseUri!.hasAuthority;

  String? get unavailableReason {
    if (!Platform.isAndroid && !Platform.isIOS) {
      return '카카오 공유는 iOS/Android에서만 지원됩니다.';
    }
    if (_nativeAppKey.isEmpty) {
      return '카카오 네이티브 앱 키가 설정되지 않았습니다.';
    }
    if (_shareBaseUri == null ||
        !_shareBaseUri!.hasScheme ||
        !_shareBaseUri!.hasAuthority) {
      return '카카오 공유용 웹 URL이 올바르지 않습니다.';
    }
    return null;
  }

  ServiceAvailability get availability {
    final reason = unavailableReason;
    if (reason == null) {
      return const ServiceAvailability.available();
    }
    if (!Platform.isAndroid && !Platform.isIOS) {
      return ServiceAvailability.unsupported(reason);
    }
    return ServiceAvailability.misconfigured(reason);
  }

  void ensureInitialized() {
    if (_initialized || !isConfigured) {
      return;
    }
    KakaoSdk.init(nativeAppKey: _nativeAppKey);
    _initialized = true;
  }

  Future<KakaoShareResult> shareBookCard({
    required String bookId,
    required String shareUrl,
    required String title,
    required String coverImageUrl,
    String? description,
  }) async {
    final reason = unavailableReason;
    if (reason != null) {
      return KakaoShareResult(shared: false, reason: reason);
    }

    ensureInitialized();
    // 공개 토큰 페이지(/share/{token})를 링크로 사용한다. 예전의 {base}/books/{bookId}는
    // 공개 페이지로 해석되지 않아(404) 수신자가 책을 볼 수 없었다. bookId는 앱 설치 시
    // 딥링크로 바로 책을 여는 execution params 로만 쓴다.
    final webUrl = Uri.tryParse(shareUrl) ?? Uri.parse('${_shareBaseUri.toString()}/$bookId');
    final appParams = {'book_id': bookId};

    final template = FeedTemplate(
      content: Content(
        title: title,
        description: description ?? 'AI Story Book으로 만든 동화책을 확인해보세요.',
        imageUrl: coverImageUrl.isNotEmpty ? Uri.tryParse(coverImageUrl) : null,
        link: Link(
          webUrl: webUrl,
          mobileWebUrl: webUrl,
          androidExecutionParams: appParams,
          iosExecutionParams: appParams,
        ),
      ),
      buttons: [
        Button(
          title: '동화책 보기',
          link: Link(
            webUrl: webUrl,
            mobileWebUrl: webUrl,
            androidExecutionParams: appParams,
            iosExecutionParams: appParams,
          ),
        ),
      ],
    );

    try {
      final available =
          await ShareClient.instance.isKakaoTalkSharingAvailable();
      if (!available) {
        return const KakaoShareResult(
          shared: false,
          reason: '카카오톡 공유를 사용할 수 없는 기기입니다.',
        );
      }
      final uri = await ShareClient.instance.shareDefault(template: template);
      await ShareClient.instance.launchKakaoTalk(uri);
      return const KakaoShareResult(shared: true);
    } catch (_) {
      return const KakaoShareResult(
        shared: false,
        reason: '카카오 공유에 실패했습니다.',
      );
    }
  }
}
