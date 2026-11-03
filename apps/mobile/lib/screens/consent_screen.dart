import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/scroll_more_hint.dart';
import 'account_recovery_screen.dart';
import 'legal_document_screen.dart';

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
  bool _checkingPhoto = false;
  bool _photoDeletionConfirmed = false;
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  // 필수 동의는 개인정보·데이터 처리뿐. 사진(아동 얼굴)은 *선택* — 데이터 최소수집·자유 동의
  // 원칙(PIPA)에 맞춰 앱 진입을 막지 않고, 실제 '사진 주인공' 사용 시점에 동의받는다.
  bool get _canContinue => _privacy && _dataProcess;

  void _setAll(bool value) {
    setState(() {
      _privacy = value;
      _dataProcess = value;
    });
  }

  /// F1(감사 Q1/M9): 이전에 사진 동의가 켜져 있었는데 이번에 끄고 제출하면, 서버 grant_consent
  /// 는 철회와 **동일하게** 계정의 사진·그림 파생 캐릭터·책·이미지 삭제를 진행한다.
  /// 저장소 삭제는 장애 시 지연·재시도될 수 있다(재설치 후 로컬 동의 플래그만 초기화된
  /// 경우 등에서 도달). 실수 파기를 막기 위해, 사진
  /// 미동의로 제출하는데 서버에 활성 사진 동의가 있으면 철회 버튼과 같은 파괴적 확인을 받는다.
  Future<bool> _confirmPhotoDataDeletionIfNeeded() async {
    final apiClient = ref.read(apiClientProvider);
    bool serverHadPhotos = false;
    try {
      final current = await apiClient.getConsent();
      serverHadPhotos = current['photos'] == true && current['revoked'] != true;
    } catch (_) {
      // An unknown previous consent must not silently authorize photo deletion.
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).consentSaveError),
          ),
        );
      }
      return false;
    }
    if (!serverHadPhotos) {
      return true;
    }
    if (!mounted) {
      return false;
    }
    final l = AppLocalizations.of(context);
    final confirmed =
        await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            scrollable: true,
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
    _photoDeletionConfirmed = confirmed;
    return confirmed;
  }

  Future<void> _accept() async {
    if (!_canContinue || _submitting || _checkingPhoto) {
      return;
    }
    // 사진 동의를 끄고 제출하는 경우, 기수집 사진 파생물 파기 전에 확인을 받는다.
    setState(() => _checkingPhoto = true);
    if (!_photo && !await _confirmPhotoDataDeletionIfNeeded()) {
      if (mounted) setState(() => _checkingPhoto = false);
      return;
    }
    if (!mounted) return;
    setState(() {
      _checkingPhoto = false;
      _submitting = true;
    });

    final prefs = ref.read(sharedPreferencesProvider);
    final apiClient = ref.read(apiClientProvider);
    final parental = ref.read(parentalControlServiceProvider);
    final mediaCleanup = ref.read(localMediaCleanupProvider);
    var cleaningLocalMedia = false;

    try {
      // Persist before the destructive server request: a lost response or app
      // termination must not leave previously cached photo-derived images.
      if (_photoDeletionConfirmed) await mediaCleanup.markPending();
      // 1) 서버에 동의 기록(사진 기능 게이트의 근거) — 성공해야 진행
      final result = await apiClient.grantConsent(
        privacy: _privacy,
        photos: _photo,
        dataProcessing: _dataProcess,
        consentVersion: kConsentVersion,
      );
      cleaningLocalMedia = true;
      if (_photoDeletionConfirmed && mounted) {
        invalidateAccountScope(
          ProviderScope.containerOf(context, listen: false),
        );
      }
      await mediaCleanup.retryPending();
      cleaningLocalMedia = false;
      // 2) 로컬 플래그 저장
      await parental.setConsent(prefs, true);
      if (!mounted) {
        return;
      }
      final seenOnboarding = await parental.hasSeenOnboarding(prefs);
      if (!mounted) return;
      final messenger = ScaffoldMessenger.of(context);
      final purgeUnconfirmed = !_photo && result['purge_incomplete'] != false;
      final pendingMessage = AppLocalizations.of(context).consentDeletionUnconfirmed;
      Navigator.pushReplacementNamed(
        context,
        seenOnboarding ? '/' : '/onboarding',
      );
      if (purgeUnconfirmed) {
        messenger.showSnackBar(SnackBar(content: Text(pendingMessage)));
      }
    } catch (e) {
      if (!mounted) {
        return;
      }
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            cleaningLocalMedia
                ? AppLocalizations.of(context).localMediaCleanupFailed
                : AppLocalizations.of(context).consentSaveError,
          ),
        ),
      );
    }
  }

  void _reject() {
    final l = AppLocalizations.of(context);
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        scrollable: true,
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
      backgroundColor: AppPalette.of(context).background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 콘텐츠(PIPA 법정 고지 포함)는 스크롤 — 큰 글자·작은 화면에서도 안 잘림.
              // 버튼은 스크롤뷰 밖 하단에 고정(항상 보임, 오버플로우 없음).
              Expanded(
                child: Scrollbar(
                  controller: _scrollController,
                  thumbVisibility: true,
                  child: SingleChildScrollView(
                    controller: _scrollController,
                    padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const SizedBox(height: AppSpacing.md),
                        Text(l.consentTitle, style: AppTextStyles.heading1),
                        const SizedBox(height: AppSpacing.sm),
                        Text(l.consentSubtitle, style: AppTextStyles.bodySmall),
                        const SizedBox(height: AppSpacing.sm),
                        Wrap(
                          spacing: AppSpacing.sm,
                          children: [
                            for (final document in LegalDocument.values)
                              TextButton.icon(
                                onPressed: () => Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) =>
                                        LegalDocumentScreen(document: document),
                                  ),
                                ),
                                icon: const Icon(Icons.description_outlined),
                                label: Text(
                                  document == LegalDocument.privacy
                                      ? l.settingsPrivacyPolicy
                                      : l.settingsTermsOfService,
                                ),
                              ),
                          ],
                        ),
                        TextButton.icon(
                          onPressed: _submitting || _checkingPhoto
                              ? null
                              : () async {
                                  final recovered = await openAccountRecovery(
                                    context,
                                    ref,
                                    restoreOnly: true,
                                  );
                                  if (!context.mounted || !recovered) return;
                                  Navigator.pushNamedAndRemoveUntil(
                                    context,
                                    '/startup',
                                    (_) => false,
                                  );
                                },
                          icon: const Icon(Icons.key_outlined),
                          label: Text(l.recoveryRestoreTitle),
                        ),
                        const SizedBox(height: AppSpacing.xl),
                        Container(
                          decoration: BoxDecoration(
                            color: AppPalette.of(context).primaryLight,
                            borderRadius: BorderRadius.circular(AppRadius.md),
                          ),
                          child: CheckboxListTile(
                            value: _privacy && _dataProcess,
                            onChanged: _submitting || _checkingPhoto
                                ? null
                                : (value) => _setAll(value ?? false),
                            title: Text(
                              l.consentRequiredOnly,
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            subtitle: Text(l.consentOptionalSeparate),
                          ),
                        ),
                        const Divider(height: AppSpacing.lg),
                        CheckboxListTile(
                          value: _privacy,
                          onChanged: _submitting || _checkingPhoto
                              ? null
                              : (value) =>
                                    setState(() => _privacy = value ?? false),
                          title: Text(l.consentPrivacyRequired),
                        ),
                        CheckboxListTile(
                          value: _dataProcess,
                          onChanged: _submitting || _checkingPhoto
                              ? null
                              : (value) => setState(
                                  () => _dataProcess = value ?? false,
                                ),
                          title: Text(l.consentDataProcessingRequired),
                        ),
                        CheckboxListTile(
                          value: _photo,
                          onChanged: _submitting || _checkingPhoto
                              ? null
                              : (value) =>
                                    setState(() => _photo = value ?? false),
                          title: Text(l.consentPhotoOptionalTitle),
                          subtitle: Text(
                            l.consentPhotoDisclosure,
                            style: const TextStyle(fontSize: 12),
                          ),
                          isThreeLine: true,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              ScrollMoreHint(controller: _scrollController),
              const SizedBox(height: AppSpacing.sm),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size.fromHeight(64),
                    padding: const EdgeInsets.symmetric(
                      vertical: 16,
                      horizontal: 20,
                    ),
                  ),
                  onPressed: (_canContinue && !_submitting && !_checkingPhoto)
                      ? _accept
                      : null,
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
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(64),
                    padding: const EdgeInsets.symmetric(
                      vertical: 16,
                      horizontal: 20,
                    ),
                  ),
                  onPressed: _submitting || _checkingPhoto ? null : _reject,
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
