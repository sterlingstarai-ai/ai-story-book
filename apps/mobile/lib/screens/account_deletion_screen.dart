import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../providers/providers.dart';

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
    try {
      await ref.read(accountRecoveryServiceProvider).deleteAccount();
      invalidateAccountScope(scope);
      if (!mounted) return;
      Navigator.pushNamedAndRemoveUntil(context, '/consent', (_) => false);
    } catch (_) {
      // Keep the deletion intent and credential for the next retry or launch.
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
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
                  Text(l.settingsDeleteUncertain, textAlign: TextAlign.center),
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
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
