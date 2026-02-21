import 'package:kakao_flutter_sdk_share/kakao_flutter_sdk_share.dart';

class KakaoShareService {
  KakaoShareService();

  static bool _initialized = false;

  static const _nativeAppKey = String.fromEnvironment('KAKAO_NATIVE_APP_KEY');
  static const _webBaseUrl = String.fromEnvironment(
    'SHARE_WEB_BASE_URL',
    defaultValue: 'https://aistorybook.app/books',
  );

  bool get isConfigured => _nativeAppKey.isNotEmpty;

  void ensureInitialized() {
    if (_initialized || !isConfigured) {
      return;
    }
    KakaoSdk.init(nativeAppKey: _nativeAppKey);
    _initialized = true;
  }

  Future<bool> shareBookCard({
    required String bookId,
    required String title,
    required String coverImageUrl,
    String? description,
  }) async {
    if (!isConfigured) {
      return false;
    }

    ensureInitialized();
    final webUrl = Uri.parse('$_webBaseUrl/$bookId');
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
      final available = await ShareClient.instance.isKakaoTalkSharingAvailable();
      if (!available) {
        return false;
      }
      final uri = await ShareClient.instance.shareDefault(template: template);
      await ShareClient.instance.launchKakaoTalk(uri);
      return true;
    } catch (_) {
      return false;
    }
  }
}
