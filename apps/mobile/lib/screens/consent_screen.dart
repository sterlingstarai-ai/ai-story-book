import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

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

  bool get _canContinue => _privacy && _photo && _dataProcess;

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
                  value: _canContinue,
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
                onChanged: (value) => setState(() => _privacy = value ?? false),
                title: const Text('개인정보 수집 및 이용에 동의 (필수)'),
              ),
              CheckboxListTile(
                value: _photo,
                onChanged: (value) => setState(() => _photo = value ?? false),
                title: const Text('사진 데이터 처리(우리 아이 주인공)에 동의 (필수)'),
                subtitle: const Text(
                  '업로드한 사진은 동화 캐릭터 생성을 위해 AI로 처리(해외 서버 포함)되며, '
                  '동의 철회 시 사진·캐릭터가 즉시 파기됩니다.',
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
              const Spacer(),
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
