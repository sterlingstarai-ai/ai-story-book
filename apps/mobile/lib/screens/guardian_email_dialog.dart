import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';

class GuardianEmailDialog extends StatefulWidget {
  const GuardianEmailDialog({
    super.key,
    required this.checkStatus,
    required this.send,
    required this.pending,
  });

  final Future<String> Function() checkStatus;
  final Future<String> Function(String) send;
  final bool pending;

  @override
  State<GuardianEmailDialog> createState() => _GuardianEmailDialogState();
}

class _GuardianEmailDialogState extends State<GuardianEmailDialog> {
  final _email = TextEditingController();
  late bool _pending = widget.pending;
  bool _busy = false;
  bool _error = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _run(Future<String> Function() operation) async {
    setState(() {
      _busy = true;
      _error = false;
    });
    try {
      final status = await operation();
      if (!mounted) return;
      if (status == 'approved' || status == 'not_required') {
        Navigator.of(context).pop(true);
        return;
      }
      setState(() {
        _pending = status == 'pending';
        _busy = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return AlertDialog(
      scrollable: true,
      title: Text(l.guardianEmailTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(_pending ? l.guardianEmailPending : l.guardianEmailIntro),
          if (!_pending)
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              enableSuggestions: false,
              enabled: !_busy,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(labelText: l.guardianEmailAddress),
            ),
          if (_error) Text(l.guardianEmailError),
        ],
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: Text(l.settingsCancel),
        ),
        if (_pending)
          TextButton(
            onPressed: _busy ? null : () => setState(() => _pending = false),
            child: Text(l.guardianEmailChange),
          ),
        FilledButton(
          onPressed: _busy || (!_pending && !_email.text.trim().contains('@'))
              ? null
              : () => _run(
                  _pending
                      ? widget.checkStatus
                      : () => widget.send(_email.text.trim()),
                ),
          child: Text(_pending ? l.guardianEmailCheck : l.guardianEmailSend),
        ),
      ],
    );
  }
}
