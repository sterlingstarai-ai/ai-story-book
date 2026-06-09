import 'package:flutter/material.dart';

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
  Map<String, dynamic> consent;
  try {
    consent = await api.getConsent();
  } catch (_) {
    consent = const <String, dynamic>{};
  }
  if (consent['photos'] == true) {
    return true;
  }
  if (!context.mounted) {
    return false;
  }
  final agreed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('사진으로 우리 아이 주인공 만들기'),
          content: const Text(
            '아이 사진은 동화 캐릭터 생성에만 쓰입니다.\n'
            '· 받는 곳: AI 콘텐츠 처리 업체(미국 등 국외)\n'
            '· 항목: 아이 얼굴 사진 · 목적: 동화 캐릭터 생성\n'
            '· 보유·이용기간: 처리 후 원본 즉시 파기(철회 시에도 즉시 삭제)\n'
            '· 운영자는 사진을 직접 열람하지 않습니다.\n'
            '· 거부권: 동의 안 해도 사진 외 기능은 그대로 이용 가능\n\n'
            '동의하고 사진을 사용할까요?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('동의'),
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
