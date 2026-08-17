import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
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

  /// F1(감사 Q1/M9): 이전에 사진 동의가 켜져 있었는데 이번에 끄고 제출하면, 서버 grant_consent
  /// 는 철회와 **동일하게** 이 아이 사진으로 만든 캐릭터·책·이미지를 즉시·불가역 파기한다
  /// (재설치 후 로컬 동의 플래그만 초기화된 경우 등에서 도달). 실수 파기를 막기 위해, 사진
  /// 미동의로 제출하는데 서버에 활성 사진 동의가 있으면 철회 버튼과 같은 파괴적 확인을 받는다.
  Future<bool> _confirmPhotoDataDeletionIfNeeded() async {
    final apiClient = ref.read(apiClientProvider);
    bool serverHadPhotos = false;
    try {
      final current = await apiClient.getConsent();
      serverHadPhotos = current['photos'] == true && current['revoked'] != true;
    } catch (_) {
      // 조회 실패 시 파괴적 확인을 강제하지 않는다(동의 저장을 막지 않음).
      return true;
    }
    if (!serverHadPhotos) {
      return true;
    }
    if (!mounted) {
      return false;
    }
    final l = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.settingsRevokeConsentTitle),
            content: Text(l.settingsRevokeConsentContent),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.settingsCancel),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(l.settingsRevoke),
              ),
            ],
          ),
        ) ??
        false;
    return confirmed;
  }

  Future<void> _accept() async {
    if (!_canContinue || _submitting) {
      return;
    }
    // 사진 동의를 끄고 제출하는 경우, 기수집 사진 파생물 파기 전에 확인을 받는다.
    if (!_photo && !await _confirmPhotoDataDeletionIfNeeded()) {
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
        SnackBar(
          content: Text(AppLocalizations.of(context).consentSaveError),
        ),
      );
    }
  }

  void _reject() {
    final l = AppLocalizations.of(context);
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.consentRejectDialogTitle),
        content: Text(l.consentRejectDialogContent),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(l.consentRejectDialogOk),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
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
                      Text(l.consentTitle, style: AppTextStyles.heading1),
                      const SizedBox(height: AppSpacing.sm),
                      Text(
                        l.consentSubtitle,
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
                          title: Text(
                            l.consentAgreeAll,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: Text(l.consentAgreeAllSubtitle),
                        ),
                      ),
                      const Divider(height: AppSpacing.lg),
                      CheckboxListTile(
                        value: _privacy,
                        onChanged: (value) =>
                            setState(() => _privacy = value ?? false),
                        title: Text(l.consentPrivacyRequired),
                      ),
                      CheckboxListTile(
                        value: _photo,
                        onChanged: (value) =>
                            setState(() => _photo = value ?? false),
                        title: Text(l.consentPhotoOptionalTitle),
                        subtitle: Text(
                          l.consentPhotoDisclosure,
                          style: const TextStyle(fontSize: 12),
                        ),
                        isThreeLine: true,
                      ),
                      CheckboxListTile(
                        value: _dataProcess,
                        onChanged: (value) =>
                            setState(() => _dataProcess = value ?? false),
                        title: Text(l.consentDataProcessingRequired),
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
                      : Text(l.consentAcceptButton),
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              SizedBox(
                width: double.infinity,
                height: 64,
                child: OutlinedButton(
                  onPressed: _reject,
                  child: Text(l.consentRejectButton),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
