import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  static const _appVersion =
      String.fromEnvironment('APP_VERSION', defaultValue: '0.1.0+1');
  static const _privacyPolicyUrl = 'https://aistorybook.com/privacy-policy';
  static const _termsOfServiceUrl = 'https://aistorybook.com/terms';

  bool _isLoading = true;
  bool _isSaving = false;
  bool _isDeleting = false;
  String? _errorMessage;

  String _language = 'ko';
  bool _darkMode = false;
  bool _allowKakaoShare = true;
  bool _bedtimeNotificationEnabled = false;
  TimeOfDay _bedtime = const TimeOfDay(hour: 21, minute: 0);
  double _sleepModeMinutes = 20;
  bool _screenTimeEnabled = false;
  double _dailyLimitMinutes = 60;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    setState(() => _isLoading = true);
    try {
      final api = ref.read(apiClientProvider);
      final data = await api.getSettings();

      final language = data['language']?.toString();
      final bedtimeHour = _toInt(data['bedtime_notification_hour']);
      final bedtimeMinute = _toInt(data['bedtime_notification_minute']);
      final sleepMode = _toInt(data['sleep_mode_default_minutes']);
      final dailyLimit = _toInt(data['daily_limit_minutes']);

      if (!mounted) {
        return;
      }
      final themeNotifier = ref.read(appThemeModeProvider.notifier);
      final screenTimeNotifier = ref.read(screenTimeStateProvider.notifier);
      setState(() {
        if (language != null && (language == 'ko' || language == 'en')) {
          _language = language;
        }
        _darkMode = data['dark_mode'] == true;
        _allowKakaoShare = data['allow_kakao_share'] != false;
        _bedtimeNotificationEnabled =
            data['bedtime_notification_enabled'] == true;
        _bedtime = TimeOfDay(
          hour: bedtimeHour ?? 21,
          minute: bedtimeMinute ?? 0,
        );
        _sleepModeMinutes = (sleepMode ?? 20).toDouble().clamp(10, 60);
        _screenTimeEnabled = data['screen_time_enabled'] == true;
        _dailyLimitMinutes = (dailyLimit ?? 60).toDouble().clamp(30, 120);
        _errorMessage = null;
        _isLoading = false;
      });
      await themeNotifier.setDarkMode(_darkMode);
      await screenTimeNotifier.syncSettings(
        enabled: _screenTimeEnabled,
        dailyLimitMinutes: _dailyLimitMinutes.round(),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = AppLocalizations.of(context).settingsLoadError;
        _isLoading = false;
      });
    }
  }

  int? _toInt(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value);
    }
    return null;
  }

  Future<void> _saveSettings() async {
    setState(() => _isSaving = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.patchSettings(
        {
          'language': _language,
          'dark_mode': _darkMode,
          'allow_kakao_share': _allowKakaoShare,
          'bedtime_notification_enabled': _bedtimeNotificationEnabled,
          'bedtime_notification_hour': _bedtime.hour,
          'bedtime_notification_minute': _bedtime.minute,
          'sleep_mode_default_minutes': _sleepModeMinutes.round(),
          'screen_time_enabled': _screenTimeEnabled,
          'daily_limit_minutes': _dailyLimitMinutes.round(),
        },
      );
      await ref.read(appThemeModeProvider.notifier).setDarkMode(_darkMode);
      await ref.read(screenTimeStateProvider.notifier).syncSettings(
            enabled: _screenTimeEnabled,
            dailyLimitMinutes: _dailyLimitMinutes.round(),
          );
      // 알림 예약은 저장의 부수효과 — 저장 완료 표시를 막지 않도록 백그라운드로 처리.
      unawaited(_applyBedtimeSchedule());

      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppLocalizations.of(context).settingsSaved)),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppLocalizations.of(context).settingsSaveError)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSaving = false);
      }
    }
  }

  /// 취침 알림 토글/시간을 실제 로컬 알림 스케줄에 반영한다(실패는 저장 흐름을 막지 않음).
  Future<void> _applyBedtimeSchedule() async {
    final l = AppLocalizations.of(context);
    final scheduler = ref.read(notificationSchedulerProvider);
    try {
      if (_bedtimeNotificationEnabled) {
        await scheduler.requestPermissions();
        await scheduler.scheduleDailyBedtime(
          hour: _bedtime.hour,
          minute: _bedtime.minute,
          title: l.settingsBedtimeNotificationTitle,
          body: l.settingsBedtimeNotificationBody,
        );
      } else {
        await scheduler.cancelBedtime();
      }
    } catch (_) {
      // 스케줄 실패는 설정 저장 흐름을 막지 않는다(토글 상태 유지).
    }
  }

  Future<void> _pickBedtime() async {
    final selected = await showTimePicker(
      context: context,
      initialTime: _bedtime,
    );
    if (selected == null || !mounted) {
      return;
    }
    setState(() => _bedtime = selected);
  }

  Future<bool> _ensureParentalAuth() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.loadAgeGateSession(prefs);
    if (parental.isAgeGateVerifiedForSession) {
      return true;
    }
    if (!mounted) {
      return false;
    }
    return showAgeGateDialog(context, ref);
  }

  Future<void> _revokeConsent() async {
    // 동의 철회는 파괴적 작업 — 아동이 직접 실행하지 못하게 부모 인증게이트 통과 필수.
    if (!await _ensureParentalAuth()) {
      return;
    }
    if (!mounted) {
      return;
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

    if (!confirmed) {
      return;
    }

    final prefs = ref.read(sharedPreferencesProvider);
    final apiClient = ref.read(apiClientProvider);
    final parental = ref.read(parentalControlServiceProvider);

    // 서버에 철회를 먼저 반영해야 사진 게이트가 실제로 닫히고 아동 사진·파생
    // 캐릭터가 파기된다(성공해야 로컬 철회 진행 — grant 배선과 대칭).
    try {
      await apiClient.revokeConsent();
    } catch (e) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content:
              Text(AppLocalizations.of(context).settingsRevokeConsentError),
        ),
      );
      return;
    }

    await parental.setConsent(prefs, false);

    if (!mounted) {
      return;
    }

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text(AppLocalizations.of(context).settingsConsentRevoked)),
    );
    Navigator.pushNamedAndRemoveUntil(context, '/consent', (_) => false);
  }

  Future<void> _deleteAllData() async {
    // 전체 데이터 삭제(되돌릴 수 없음)도 부모 인증게이트 통과 필수.
    if (!await _ensureParentalAuth()) {
      return;
    }
    if (!mounted) {
      return;
    }
    final l = AppLocalizations.of(context);
    final firstConfirm = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.settingsDeleteAllTitle),
            content: Text(l.settingsDeleteAllContent),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.settingsCancel),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(l.settingsContinue),
              ),
            ],
          ),
        ) ??
        false;

    if (!firstConfirm || !mounted) {
      return;
    }

    final textController = TextEditingController();
    final secondConfirm = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.settingsFinalConfirmTitle),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l.settingsFinalConfirmPrompt),
                const SizedBox(height: AppSpacing.sm),
                TextField(
                  controller: textController,
                  decoration:
                      InputDecoration(hintText: l.settingsDeleteKeyword),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.settingsCancel),
              ),
              TextButton(
                onPressed: () =>
                    Navigator.pop(context, textController.text.trim() == '삭제'),
                child: Text(l.settingsDeleteKeyword),
              ),
            ],
          ),
        ) ??
        false;
    textController.dispose();

    if (!secondConfirm) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(
                AppLocalizations.of(context).settingsDeleteKeywordMismatch)),
      );
      return;
    }

    setState(() => _isDeleting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.deleteMyData();
      final prefs = ref.read(sharedPreferencesProvider);
      await prefs.clear();

      if (!mounted) {
        return;
      }
      Navigator.pushNamedAndRemoveUntil(context, '/consent', (_) => false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).settingsDeleteError)),
      );
    } finally {
      if (mounted) {
        setState(() => _isDeleting = false);
      }
    }
  }

  String _formatTimeOfDay(TimeOfDay time) {
    final hour = time.hour.toString().padLeft(2, '0');
    final minute = time.minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }

  Future<void> _copyUrl(String url) async {
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(AppLocalizations.of(context).settingsLinkCopied)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    if (_isLoading) {
      return Scaffold(
        appBar: AppBar(title: Text(l.settingsTitle)),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(l.settingsTitle),
        actions: [
          TextButton(
            onPressed: _isSaving ? null : _saveSettings,
            child: _isSaving
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Text(l.settingsSave),
          ),
        ],
      ),
      body: ListView(
        children: [
          if (_errorMessage != null)
            Container(
              margin: const EdgeInsets.all(AppSpacing.md),
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.error.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Text(
                _errorMessage!,
                style: AppTextStyles.caption.copyWith(color: AppColors.error),
              ),
            ),
          _SectionHeader(l.settingsSectionAccount),
          ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(l.settingsChildProfile),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/profiles'),
          ),
          ListTile(
            leading: const Icon(Icons.analytics_outlined),
            title: Text(l.settingsParentDashboard),
            subtitle: Text(l.settingsParentDashboardSubtitle),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/parent-dashboard'),
          ),
          ListTile(
            leading: const Icon(Icons.mic_outlined),
            title: Text(l.settingsFamilyVoice),
            subtitle: Text(l.settingsFamilyVoiceSubtitle),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/voice-profiles'),
          ),
          ListTile(
            leading: const Icon(Icons.credit_card),
            title: Text(l.settingsCreditsSubscription),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/credits'),
          ),
          ListTile(
            leading: const Icon(Icons.verified_user_outlined),
            title: Text(l.settingsPoliciesTitle),
            subtitle: Text(l.settingsPoliciesSubtitle),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => showDialog<void>(
              context: context,
              builder: (context) {
                final dl = AppLocalizations.of(context);
                Widget item(String title, String body) => Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(title,
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          const SizedBox(height: 2),
                          Text(body),
                        ],
                      ),
                    );
                return AlertDialog(
                  title: Text(dl.settingsPoliciesTitle),
                  content: SingleChildScrollView(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        item(dl.policyCreditRolloverTitle,
                            dl.policyCreditRolloverBody),
                        item(dl.policyBookAccessTitle, dl.policyBookAccessBody),
                        item(dl.policyRefundTitle, dl.policyRefundBody),
                      ],
                    ),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: Text(dl.libraryClose),
                    ),
                  ],
                );
              },
            ),
          ),
          const Divider(height: 1),
          _SectionHeader(l.settingsSectionApp),
          ListTile(
            title: Text(l.settingsLanguage),
            trailing: DropdownButton<String>(
              value: _language,
              items: [
                DropdownMenuItem(
                    value: 'ko', child: Text(l.settingsLanguageKorean)),
                DropdownMenuItem(
                    value: 'en', child: Text(l.settingsLanguageEnglish)),
              ],
              onChanged: (value) {
                if (value == null) {
                  return;
                }
                setState(() => _language = value);
              },
            ),
          ),
          SwitchListTile(
            title: Text(l.settingsDarkMode),
            subtitle: Text(l.settingsDarkModeSubtitle),
            value: _darkMode,
            onChanged: (value) async {
              setState(() => _darkMode = value);
              await ref.read(appThemeModeProvider.notifier).setDarkMode(value);
            },
          ),
          SwitchListTile(
            title: Text(l.settingsKakaoShare),
            subtitle: Text(l.settingsKakaoShareSubtitle),
            value: _allowKakaoShare,
            onChanged: (value) => setState(() => _allowKakaoShare = value),
          ),
          const Divider(height: 1),
          _SectionHeader(l.settingsSectionSleep),
          SwitchListTile(
            title: Text(l.settingsBedtimeNotification),
            value: _bedtimeNotificationEnabled,
            onChanged: (value) =>
                setState(() => _bedtimeNotificationEnabled = value),
          ),
          if (_bedtimeNotificationEnabled)
            ListTile(
              title: Text(l.settingsBedtime),
              subtitle: Text(_formatTimeOfDay(_bedtime)),
              trailing: const Icon(Icons.chevron_right),
              onTap: _pickBedtime,
            ),
          ListTile(
            title: Text(l.settingsSleepTimer(_sleepModeMinutes.round())),
            subtitle: Slider(
              min: 10,
              max: 60,
              divisions: 10,
              label: l.settingsMinutes(_sleepModeMinutes.round()),
              value: _sleepModeMinutes,
              onChanged: (value) => setState(() => _sleepModeMinutes = value),
            ),
          ),
          const Divider(height: 1),
          _SectionHeader(l.settingsSectionScreenTime),
          SwitchListTile(
            title: Text(l.settingsScreenTimeEnabled),
            value: _screenTimeEnabled,
            onChanged: (value) async {
              final ok = await _ensureParentalAuth();
              if (!ok || !mounted) {
                return;
              }
              setState(() => _screenTimeEnabled = value);
            },
          ),
          if (_screenTimeEnabled)
            ListTile(
              title: Text(l.settingsDailyLimit(_dailyLimitMinutes.round())),
              subtitle: Slider(
                min: 30,
                max: 120,
                divisions: 9,
                label: l.settingsMinutes(_dailyLimitMinutes.round()),
                value: _dailyLimitMinutes,
                onChanged: (value) =>
                    setState(() => _dailyLimitMinutes = value),
              ),
            ),
          const Divider(height: 1),
          _SectionHeader(l.settingsSectionAppInfo),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: Text(l.settingsAppVersion),
            subtitle: const Text('v$_appVersion'),
          ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: Text(l.settingsPrivacyPolicy),
            subtitle: const Text(_privacyPolicyUrl),
            onTap: () => _copyUrl(_privacyPolicyUrl),
          ),
          ListTile(
            leading: const Icon(Icons.description_outlined),
            title: Text(l.settingsTermsOfService),
            subtitle: const Text(_termsOfServiceUrl),
            onTap: () => _copyUrl(_termsOfServiceUrl),
          ),
          const Divider(height: 1),
          _SectionHeader(l.settingsSectionPrivacy),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: Text(l.settingsRevokeParentalConsent),
            onTap: _revokeConsent,
          ),
          ListTile(
            leading: const Icon(Icons.delete_forever, color: AppColors.error),
            title: Text(l.settingsDeleteAllData),
            subtitle: Text(l.settingsDeleteAllDataSubtitle),
            onTap: _isDeleting ? null : _deleteAllData,
          ),
          if (_isDeleting)
            const Padding(
              padding: EdgeInsets.all(AppSpacing.md),
              child: Center(child: CircularProgressIndicator()),
            ),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.md,
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.sm,
      ),
      child: Text(
        title,
        style: AppTextStyles.caption.copyWith(
          color: AppColors.textSecondary,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
