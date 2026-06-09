import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

/// 약관 버전 — 개정 시 올리면 재동의를 유발(서버 consent_version과 맞춤).
const kConsentVersion = 'v2';

class ConsentScreen extends ConsumerStatefulWidget {
  const ConsentScreen({super.key});

  @override
  ConsumerState<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends ConsumerState<ConsentScreen> {
  bool _privacy = false;
  bool _photo = false;
  bool _dataProcess = false;
  bool _submitting = false;

  // 필수 동의는 개인정보·데이터 처리뿐. 사진(아동 얼굴)은 *선택* — 데이터 최소수집·자유 동의
  // 원칙(PIPA)에 맞춰 앱 진입을 막지 않고, 실제 '사진 주인공' 사용 시점에 동의받는다.
  bool get _canContinue => _privacy && _dataProcess;

  void _setAll(bool value) {
    setState(() {
      _privacy = value;
      _photo = value;
      _dataProcess = value;
    });
  }

  Future<void> _accept() async {
    if (!_canContinue || _submitting) {
      return;
    }
    setState(() => _submitting = true);

    final prefs = ref.read(sharedPreferencesProvider);
    final apiClient = ref.read(apiClientProvider);
    final parental = ref.read(parentalControlServiceProvider);

    try {
      // 1) 서버에 동의 기록(사진 기능 게이트의 근거) — 성공해야 진행
      await apiClient.grantConsent(
        privacy: _privacy,
        photos: _photo,
        dataProcessing: _dataProcess,
        consentVersion: kConsentVersion,
      );
      // 2) 로컬 플래그 저장
      await parental.setConsent(prefs, true);
      if (!mounted) {
        return;
      }
      Navigator.pushReplacementNamed(context, '/onboarding');
    } catch (e) {
      if (!mounted) {
        return;
      }
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('동의 저장에 실패했어요. 네트워크 확인 후 다시 시도해주세요.'),
        ),
      );
    }
  }

  void _reject() {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('동의가 필요합니다'),
        content: const Text('아동 보호 정책상 부모 동의 없이는 앱을 이용할 수 없습니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('확인'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 콘텐츠(PIPA 법정 고지 포함)는 스크롤 — 큰 글자·작은 화면에서도 안 잘림.
              // 버튼은 스크롤뷰 밖 하단에 고정(항상 보임, 오버플로우 없음).
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: AppSpacing.md),
                      const Text('부모 동의', style: AppTextStyles.heading1),
                      const SizedBox(height: AppSpacing.sm),
                      const Text(
                        '아동 보호를 위해 아래 항목에 대한 부모 동의가 필요합니다.',
                        style: AppTextStyles.bodySmall,
                      ),
                      const SizedBox(height: AppSpacing.xl),
                      Container(
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight,
                          borderRadius: BorderRadius.circular(AppRadius.md),
                        ),
                        child: CheckboxListTile(
                          value: _privacy && _photo && _dataProcess,
                          onChanged: (value) => _setAll(value ?? false),
                          title: const Text(
                            '약관 전체 동의',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: const Text('아래 항목에 모두 동의합니다.'),
                        ),
                      ),
                      const Divider(height: AppSpacing.lg),
                      CheckboxListTile(
                        value: _privacy,
                        onChanged: (value) =>
                            setState(() => _privacy = value ?? false),
                        title: const Text('개인정보 수집 및 이용에 동의 (필수)'),
                      ),
                      CheckboxListTile(
                        value: _photo,
                        onChanged: (value) =>
                            setState(() => _photo = value ?? false),
                        title: const Text('사진으로 우리 아이 주인공 만들기 (선택)'),
                        subtitle: const Text(
                          '아이 사진은 동화 캐릭터 생성에만 쓰입니다. · 받는 곳: AI 콘텐츠 처리 업체'
                          '(미국 등 국외) · 항목: 아이 얼굴 사진 · 목적: 동화 캐릭터 생성 '
                          '· 보유·이용기간: 캐릭터 일관성 유지를 위해 서비스 이용 기간 동안 보관, 동의 철회·삭제 요청 시 즉시 파기 '
                          '· 운영자는 사진을 직접 열람하지 않습니다. '
                          '· 거부권: 동의하지 않아도 사진 외 기능은 그대로 이용할 수 있어요(선택).',
                          style: TextStyle(fontSize: 12),
                        ),
                        isThreeLine: true,
                      ),
                      CheckboxListTile(
                        value: _dataProcess,
                        onChanged: (value) =>
                            setState(() => _dataProcess = value ?? false),
                        title: const Text('데이터 처리 및 저장 정책에 동의 (필수)'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              SizedBox(
                width: double.infinity,
                height: 64,
                child: ElevatedButton(
                  onPressed: (_canContinue && !_submitting) ? _accept : null,
                  child: _submitting
                      ? const SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Text('동의하고 시작하기'),
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              SizedBox(
                width: double.infinity,
                height: 64,
                child: OutlinedButton(
                  onPressed: _reject,
                  child: const Text('동의하지 않음'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
