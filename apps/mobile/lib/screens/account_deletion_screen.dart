import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/local_media_cleanup.dart';
import '../services/user_service.dart';

final legacyCleanupProvider = Provider((ref) => clearUnattributedLegacyData);

/// A lost deletion response must not return the user to a stale account scope.
class AccountDeletionScreen extends ConsumerStatefulWidget {
  const AccountDeletionScreen({super.key});
  @override
  ConsumerState<AccountDeletionScreen> createState() =>
      _AccountDeletionScreenState();
}

class _AccountDeletionScreenState extends ConsumerState<AccountDeletionScreen> {
  bool _busy = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _retry();
    });
  }

  Future<void> _retry() async {
    if (_busy) return;
    setState(() => _busy = true);
    final scope = ProviderScope.containerOf(context, listen: false);
    final recovery = ref.read(accountRecoveryServiceProvider);
    final screenTime = ref.read(screenTimeStateProvider.notifier);
    final parental = ref.read(parentalControlServiceProvider);
    final preferences = ref.read(sharedPreferencesProvider);
    try {
      await recovery.deleteAccount();
      await screenTime.syncSettings(enabled: false, dailyLimitMinutes: 60);
      await parental.setConsent(preferences, false);
      invalidateAccountScope(scope);
      if (!mounted) return;
      Navigator.pushNamedAndRemoveUntil(context, '/consent', (_) => false);
    } catch (_) {
      // Keep the deletion intent and credential for the next retry or launch.
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _clearSharedData() async {
    if (_busy) return;
    final l = AppLocalizations.of(context);
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.legacyCleanupTitle),
        content: Text(l.legacyCleanupWarning),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(l.legacyCleanupCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(l.legacyCleanupConfirm),
          ),
        ],
      ),
    );
    if (!mounted || approved != true) return;
    setState(() => _busy = true);
    try {
      await ref.read(legacyCleanupProvider)(
        ref.read(sharedPreferencesProvider),
      );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(l.legacyCleanupFailed)));
      }
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (mounted) await _retry();
  }

  Future<void> _clearAccountMedia() async {
    if (_busy) return;
    final l = AppLocalizations.of(context);
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(l.legacyAccountCleanupTitle),
        content: Text(l.legacyAccountCleanupWarning),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(l.legacyCleanupCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(l.legacyCleanupConfirm),
          ),
        ],
      ),
    );
    if (!mounted || approved != true) return;
    setState(() => _busy = true);
    try {
      await ref.read(clearLegacyAccountMediaProvider)();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(l.legacyCleanupFailed)));
      }
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (mounted) await _retry();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final preferences = ref.watch(sharedPreferencesProvider);
    final historicalDataUnresolved =
        preferences.getBool(UserService.deletionCommittedKey) == true &&
        preferences.getBool(localMediaCleanupPendingKey) == true;
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.settingsDeleteAllTitle),
          automaticallyImplyLeading: false,
        ),
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    historicalDataUnresolved
                        ? l.settingsDeleteLegacyUnresolved
                        : l.settingsDeleteUncertain,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  if (_busy)
                    const CircularProgressIndicator()
                  else
                    FilledButton(
                      onPressed: _retry,
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(160, 64),
                      ),
                      child: Text(l.accountRetry),
                    ),
                  if (!_busy && historicalDataUnresolved) ...[
                    const SizedBox(height: 16),
                    OutlinedButton(
                      onPressed: _clearAccountMedia,
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(160, 64),
                      ),
                      child: Text(l.legacyAccountCleanupAction),
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton(
                      onPressed: _clearSharedData,
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(160, 64),
                      ),
                      child: Text(l.legacyCleanupAction),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
