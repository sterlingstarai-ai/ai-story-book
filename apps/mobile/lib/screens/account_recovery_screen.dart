import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/user_service.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';

Future<bool> openAccountRecovery(
  BuildContext context,
  WidgetRef ref, {
  bool restoreOnly = false,
}) async {
  if (!await ensureAgeGate(context, ref) || !context.mounted) return false;
  final recovered = await Navigator.of(context).push<bool>(
    MaterialPageRoute(
      builder: (_) => AccountRecoveryScreen(restoreOnly: restoreOnly),
    ),
  );
  return recovered == true;
}

/// The displayed recovery code is independent of the device credential. A parent
/// must save and confirm it; neither credential is written to local preferences.
class AccountRecoveryScreen extends ConsumerStatefulWidget {
  const AccountRecoveryScreen({super.key, this.restoreOnly = false});
  final bool restoreOnly;

  @override
  ConsumerState<AccountRecoveryScreen> createState() =>
      _AccountRecoveryScreenState();
}

class _AccountRecoveryScreenState extends ConsumerState<AccountRecoveryScreen> {
  final _input = TextEditingController();
  final _confirmation = TextEditingController();
  bool _busy = false;
  bool _loading = true;
  bool _enabled = false;
  bool _restore = false;
  bool _recovered = false;
  bool _saved = false;
  bool _uncertain = false;
  String? _code;
  String? _error;

  @override
  void initState() {
    super.initState();
    _restore = widget.restoreOnly;
    if (_restore) {
      _loading = false;
    } else {
      _load();
    }
  }

  @override
  void dispose() {
    _input.dispose();
    _confirmation.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final enabled = await ref.read(apiClientProvider).hasAccountRecovery();
      if (mounted) setState(() => _enabled = enabled);
    } catch (_) {
      if (mounted) {
        setState(() => _error = AppLocalizations.of(context).recoveryLoadError);
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _issue() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      // Set before requesting: an interrupted response can invalidate the old code.
      await ref
          .read(sharedPreferencesProvider)
          .setBool(UserService.recoveryBackupNeededKey, true);
      final code = await ref
          .read(apiClientProvider)
          .createAccountRecoveryCode();
      if (!mounted) return;
      setState(() {
        _code = code;
        _saved = false;
        _enabled = true;
      });
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = AppLocalizations.of(context).recoveryIssueError,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _recover() async {
    if (_busy) return;
    final code = _input.text.trim();
    final l = AppLocalizations.of(context);
    if (!RegExp(r'^ASB-R1-[A-Za-z0-9_-]{43}$').hasMatch(code)) {
      setState(() => _error = l.recoveryInvalidCode);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final replacement = await ref
          .read(accountRecoveryServiceProvider)
          .recover(code);
      if (!mounted) return;
      invalidateRecoveredAccount(ref);
      _input.clear();
      setState(() {
        _code = replacement;
        _recovered = true;
        _uncertain = false;
        _saved = false;
      });
    } catch (_) {
      var pending = true;
      try {
        pending =
            await ref.read(userServiceProvider).pendingRecoveryKey() != null;
      } catch (_) {
        /* Keep the recovery screen when storage cannot be read. */
      }
      if (!mounted) return;
      setState(() {
        _uncertain = pending;
        _error = l.recoveryFailed;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmSaved() async {
    final code = _code;
    if (_busy ||
        code == null ||
        !_saved ||
        _confirmation.text != code.substring(code.length - 6)) {
      return;
    }
    setState(() => _busy = true);
    try {
      await ref
          .read(sharedPreferencesProvider)
          .setBool(UserService.recoveryBackupNeededKey, false);
      if (!mounted) return;
      if (_recovered) {
        Navigator.pop(context, true);
      } else {
        _confirmation.clear();
        setState(() {
          _code = null;
          _saved = false;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final code = _code;
    final currentAccountBackedUp =
        _enabled &&
        ref
                .read(sharedPreferencesProvider)
                .getBool(UserService.recoveryBackupNeededKey) !=
            true;
    final canConfirm =
        code != null &&
        _saved &&
        _confirmation.text == code.substring(code.length - 6);
    return PopScope(
      canPop: !_busy && !_uncertain && !_recovered && code == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && code != null) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(l.recoveryFinishBackupFirst)));
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(l.recoveryTitle),
          automaticallyImplyLeading:
              code == null && !_busy && !_uncertain && !_recovered,
        ),
        body: SafeArea(
          // Keep the submit target stable while the keyboard animates away.
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 600),
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_loading)
                      const Center(child: CircularProgressIndicator())
                    else if (code != null) ...[
                      Text(
                        _recovered ? l.recoverySucceeded : l.recoverySaveTitle,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 16),
                      Text(l.recoverySaveMessage),
                      const SizedBox(height: 20),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Theme.of(
                            context,
                          ).colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: SelectableText(
                          code,
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 18,
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(64, 64),
                        ),
                        onPressed: () async {
                          await Clipboard.setData(ClipboardData(text: code));
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(l.recoveryCopied)),
                          );
                        },
                        icon: const Icon(Icons.copy),
                        label: Text(l.recoveryCopy),
                      ),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        value: _saved,
                        title: Text(l.recoverySavedCheck),
                        onChanged: _busy
                            ? null
                            : (value) =>
                                  setState(() => _saved = value ?? false),
                      ),
                      TextField(
                        controller: _confirmation,
                        enabled: !_busy,
                        textInputAction: TextInputAction.done,
                        onSubmitted: (_) => _confirmSaved(),
                        autocorrect: false,
                        enableSuggestions: false,
                        enableIMEPersonalizedLearning: false,
                        maxLength: 6,
                        decoration: InputDecoration(
                          labelText: l.recoveryConfirmSuffix,
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                      const SizedBox(height: 16),
                      _button(
                        l.recoveryConfirmSaved,
                        canConfirm && !_busy ? _confirmSaved : null,
                      ),
                    ] else if (_recovered) ...[
                      Text(
                        l.recoverySucceeded,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 16),
                      Text(l.recoveryBackupPending),
                      const SizedBox(height: 24),
                      _button(
                        l.recoveryContinue,
                        () => Navigator.pop(context, true),
                      ),
                    ] else if (_restore) ...[
                      Text(
                        l.recoveryRestoreTitle,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 16),
                      Text(l.recoveryRestoreMessage),
                      const SizedBox(height: 24),
                      TextField(
                        key: const ValueKey('recovery-code-input'),
                        controller: _input,
                        textInputAction: TextInputAction.done,
                        onSubmitted: (_) => _recover(),
                        obscureText: true,
                        autocorrect: false,
                        enableSuggestions: false,
                        enableIMEPersonalizedLearning: false,
                        enabled: !_busy,
                        decoration: InputDecoration(
                          labelText: l.recoveryCodeLabel,
                        ),
                      ),
                      const SizedBox(height: 24),
                      _button(l.recoveryRestoreButton, _busy ? null : _recover),
                    ] else ...[
                      Text(
                        _enabled ? l.recoveryEnabled : l.recoveryNotEnabled,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 16),
                      Text(l.recoveryDescription),
                      if (ref
                              .read(sharedPreferencesProvider)
                              .getBool(UserService.recoveryBackupNeededKey) ==
                          true) ...[
                        const SizedBox(height: 16),
                        Text(l.recoveryBackupPending),
                      ],
                      const SizedBox(height: 24),
                      if (_error == null)
                        _button(
                          _enabled
                              ? l.recoveryReplaceCode
                              : l.recoveryCreateCode,
                          _busy ? null : _issue,
                        )
                      else
                        _button(l.accountRetry, _busy ? null : _load),
                      const SizedBox(height: 16),
                      if (!currentAccountBackedUp) ...[
                        Text(l.recoverySwitchNeedsBackup),
                        const SizedBox(height: 16),
                      ],
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(64, 64),
                        ),
                        onPressed: _busy || !currentAccountBackedUp
                            ? null
                            : () => setState(() {
                                _restore = true;
                                _error = null;
                              }),
                        child: Text(l.recoveryRestoreTitle),
                      ),
                    ],
                    if (_busy)
                      const Padding(
                        padding: EdgeInsets.all(16),
                        child: Center(child: CircularProgressIndicator()),
                      ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: Text(
                          _error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _button(String text, VoidCallback? onPressed) => FilledButton(
    style: FilledButton.styleFrom(minimumSize: const Size(64, 64)),
    onPressed: onPressed,
    child: Text(text),
  );
}
