import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/api_client.dart';

/// 사진/그림(아동 얼굴) 사용 직전 JIT 보호자 동의.
///
/// 이미 사진 동의가 있으면 통과, 없으면 PIPA 5요소(수령자·항목·목적·보유·방법) 고지
/// 다이얼로그를 띄워 받는다. 필수 동의(개인정보·데이터처리)는 임의로 만들지 않고 서버의
/// 기존 값을 echo한다(동의 진정성·감사추적 보존). 동의 완료 시 true.
///
/// 캐릭터 생성의 모든 사진/그림 진입점(소스 시트·캐릭터 화면)이 같은 고지를 쓰도록
/// 단일 헬퍼로 둔다(진입점별 고지 누락·불일치 방지).
Future<bool> ensurePhotoConsent(BuildContext context, ApiClient api) async {
  final l = AppLocalizations.of(context);
  Map<String, dynamic> consent;
  try {
    consent = await api.getConsent();
  } catch (_) {
    // H15: getConsent 실패 시 빈 맵을 echo하면 grantConsent(privacy:false,
    // dataProcessing:false)로 기존 필수 동의를 파괴한다. fail-closed로 중단하고
    // 재시도를 안내한다(감사추적·동의 진정성 보존).
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.photoConsentLoadFailed)),
      );
    }
    return false;
  }
  if (consent['photos'] == true) {
    return true;
  }
  if (!context.mounted) {
    return false;
  }
  // H16: PIPA 5요소 법정 고지·제목·버튼을 로컬라이즈(en/ja 사용자도 읽을 수 있는 동의).
  final agreed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(l.consentPhotoOptionalTitle),
          content: Text(l.consentPhotoDisclosure),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(l.photoConsentCancel),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(l.photoConsentAgree),
            ),
          ],
        ),
      ) ??
      false;
  if (!agreed) {
    return false;
  }
  try {
    await api.grantConsent(
      privacy: consent['privacy'] == true,
      photos: true,
      dataProcessing: consent['data_processing'] == true,
    );
    return true;
  } catch (_) {
    return false;
  }
}
