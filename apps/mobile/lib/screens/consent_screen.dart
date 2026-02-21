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

  bool get _canContinue => _privacy && _photo && _dataProcess;

  Future<void> _accept() async {
    if (!_canContinue) {
      return;
    }

    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.setConsent(prefs, true);

    if (!mounted) {
      return;
    }

    Navigator.pushReplacementNamed(context, '/onboarding');
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
              CheckboxListTile(
                value: _privacy,
                onChanged: (value) => setState(() => _privacy = value ?? false),
                title: const Text('개인정보 수집 및 이용에 동의'),
              ),
              CheckboxListTile(
                value: _photo,
                onChanged: (value) => setState(() => _photo = value ?? false),
                title: const Text('사진 데이터 처리(캐릭터 생성)에 동의'),
              ),
              CheckboxListTile(
                value: _dataProcess,
                onChanged: (value) =>
                    setState(() => _dataProcess = value ?? false),
                title: const Text('데이터 처리 및 저장 정책에 동의'),
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                height: 64,
                child: ElevatedButton(
                  onPressed: _canContinue ? _accept : null,
                  child: const Text('동의하고 시작하기'),
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
