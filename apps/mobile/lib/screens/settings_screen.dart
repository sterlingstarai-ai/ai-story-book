import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
        _errorMessage = '설정을 불러오지 못했어요.';
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
        const SnackBar(content: Text('설정이 저장되었습니다.')),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('설정 저장에 실패했어요. 잠시 후 다시 시도해주세요.')),
      );
    } finally {
      if (mounted) {
        setState(() => _isSaving = false);
      }
    }
  }

  /// 취침 알림 토글/시간을 실제 로컬 알림 스케줄에 반영한다(실패는 저장 흐름을 막지 않음).
  Future<void> _applyBedtimeSchedule() async {
    final scheduler = ref.read(notificationSchedulerProvider);
    try {
      if (_bedtimeNotificationEnabled) {
        await scheduler.requestPermissions();
        await scheduler.scheduleDailyBedtime(
          hour: _bedtime.hour,
          minute: _bedtime.minute,
          title: '오늘의 동화 읽을 시간이에요',
          body: '잠들기 전 오늘의 동화를 함께 읽어요',
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
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('동의 철회'),
            content: const Text('동의를 철회하면 앱 이용이 제한되며, 데이터 삭제를 진행할 수 있습니다.'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('철회'),
              ),
            ],
          ),
        ) ??
        false;

    if (!confirmed) {
      return;
    }

    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.setConsent(prefs, false);

    if (!mounted) {
      return;
    }

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('동의가 철회되었습니다.')),
    );
    Navigator.pushNamedAndRemoveUntil(context, '/consent', (_) => false);
  }

  Future<void> _deleteAllData() async {
    final firstConfirm = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('내 데이터 모두 삭제'),
            content: const Text('이 작업은 되돌릴 수 없습니다. 계속할까요?'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('계속'),
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
            title: const Text('최종 확인'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('삭제를 진행하려면 아래에 "삭제"를 입력하세요.'),
                const SizedBox(height: AppSpacing.sm),
                TextField(
                  controller: textController,
                  decoration: const InputDecoration(hintText: '삭제'),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              TextButton(
                onPressed: () =>
                    Navigator.pop(context, textController.text.trim() == '삭제'),
                child: const Text('삭제'),
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
        const SnackBar(content: Text('확인 텍스트가 일치하지 않습니다.')),
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
        const SnackBar(content: Text('데이터 삭제에 실패했어요. 잠시 후 다시 시도해주세요.')),
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
      const SnackBar(content: Text('링크를 복사했어요.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Scaffold(
        appBar: AppBar(title: const Text('설정')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('설정'),
        actions: [
          TextButton(
            onPressed: _isSaving ? null : _saveSettings,
            child: _isSaving
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('저장'),
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
          const _SectionHeader('계정'),
          ListTile(
            leading: const Icon(Icons.person_outline),
            title: const Text('아이 프로필'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/profiles'),
          ),
          ListTile(
            leading: const Icon(Icons.analytics_outlined),
            title: const Text('부모 대시보드'),
            subtitle: const Text('주간/월간 읽기 리포트'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/parent-dashboard'),
          ),
          ListTile(
            leading: const Icon(Icons.mic_outlined),
            title: const Text('가족 목소리'),
            subtitle: const Text('녹음 샘플과 동의 상태 관리'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/voice-profiles'),
          ),
          ListTile(
            leading: const Icon(Icons.credit_card),
            title: const Text('크레딧/구독'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pushNamed(context, '/credits'),
          ),
          const Divider(height: 1),
          const _SectionHeader('앱 설정'),
          ListTile(
            title: const Text('언어'),
            trailing: DropdownButton<String>(
              value: _language,
              items: const [
                DropdownMenuItem(value: 'ko', child: Text('한국어')),
                DropdownMenuItem(value: 'en', child: Text('English')),
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
            title: const Text('다크 모드'),
            subtitle: const Text('앱 전체 테마를 어둡게 변경합니다.'),
            value: _darkMode,
            onChanged: (value) async {
              setState(() => _darkMode = value);
              await ref.read(appThemeModeProvider.notifier).setDarkMode(value);
            },
          ),
          SwitchListTile(
            title: const Text('카카오톡 카드 공유'),
            subtitle: const Text('공유 메뉴에서 카카오톡 공유를 표시합니다.'),
            value: _allowKakaoShare,
            onChanged: (value) => setState(() => _allowKakaoShare = value),
          ),
          const Divider(height: 1),
          const _SectionHeader('수면 모드'),
          SwitchListTile(
            title: const Text('취침 알림'),
            value: _bedtimeNotificationEnabled,
            onChanged: (value) =>
                setState(() => _bedtimeNotificationEnabled = value),
          ),
          if (_bedtimeNotificationEnabled)
            ListTile(
              title: const Text('취침 시간'),
              subtitle: Text(_formatTimeOfDay(_bedtime)),
              trailing: const Icon(Icons.chevron_right),
              onTap: _pickBedtime,
            ),
          ListTile(
            title: Text('기본 수면 타이머: ${_sleepModeMinutes.round()}분'),
            subtitle: Slider(
              min: 10,
              max: 60,
              divisions: 10,
              label: '${_sleepModeMinutes.round()}분',
              value: _sleepModeMinutes,
              onChanged: (value) => setState(() => _sleepModeMinutes = value),
            ),
          ),
          const Divider(height: 1),
          const _SectionHeader('화면 시간 제한'),
          SwitchListTile(
            title: const Text('화면 시간 제한 사용'),
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
              title: Text('일일 제한: ${_dailyLimitMinutes.round()}분'),
              subtitle: Slider(
                min: 30,
                max: 120,
                divisions: 9,
                label: '${_dailyLimitMinutes.round()}분',
                value: _dailyLimitMinutes,
                onChanged: (value) =>
                    setState(() => _dailyLimitMinutes = value),
              ),
            ),
          const Divider(height: 1),
          const _SectionHeader('앱 정보'),
          const ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('앱 버전'),
            subtitle: Text('v$_appVersion'),
          ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('개인정보처리방침'),
            subtitle: const Text(_privacyPolicyUrl),
            onTap: () => _copyUrl(_privacyPolicyUrl),
          ),
          ListTile(
            leading: const Icon(Icons.description_outlined),
            title: const Text('이용약관'),
            subtitle: const Text(_termsOfServiceUrl),
            onTap: () => _copyUrl(_termsOfServiceUrl),
          ),
          const Divider(height: 1),
          const _SectionHeader('개인정보'),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('부모 동의 철회'),
            onTap: _revokeConsent,
          ),
          ListTile(
            leading: const Icon(Icons.delete_forever, color: AppColors.error),
            title: const Text('내 데이터 모두 삭제'),
            subtitle: const Text('책, 캐릭터, 읽기 기록 등 모든 데이터가 삭제됩니다.'),
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
