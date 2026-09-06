import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/parental_control_service.dart';
import '../utils/constants.dart';

/// M24: 사진 업로드 등 민감 진입점의 공용 보호자 게이트.
///
/// 세션 내 이미 검증됐으면 통과, 아니면 age gate 다이얼로그를 띄운다. 통과 시 true.
/// 두 사진 진입점(characters_screen._pickImage, character_source_sheet._usePhoto)이
/// 동일 게이트를 공유해 '게이트→JIT 동의' 이중 보호가 한쪽에만 적용되던 불일치를 없앤다.
Future<bool> ensureAgeGate(BuildContext context, WidgetRef ref) async {
  if (!context.mounted) return false;
  final parental = ref.read(parentalControlServiceProvider);
  if (parental.isAgeGateVerifiedForSession) {
    return true;
  }
  return showAgeGateDialog(context, ref);
}

Future<bool> showAgeGateDialog(BuildContext context, WidgetRef ref) async {
  if (!context.mounted) return false;
  final parentalControl = ref.read(parentalControlServiceProvider);
  final prefs = ref.read(sharedPreferencesProvider);
  final challenge = parentalControl.createChallenge();

  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _AgeGateDialog(
      parentalControl: parentalControl,
      challenge: challenge,
    ),
  );

  if (result == true && context.mounted) {
    await parentalControl.persistAgeGateSession(prefs);
    return context.mounted;
  }
  return false;
}

class _AgeGateDialog extends StatefulWidget {
  const _AgeGateDialog({
    required this.parentalControl,
    required this.challenge,
  });

  final ParentalControlService parentalControl;
  final AgeChallenge challenge;

  @override
  State<_AgeGateDialog> createState() => _AgeGateDialogState();
}

class _AgeGateDialogState extends State<_AgeGateDialog> {
  final _controller = TextEditingController();
  String? _errorText;
  bool _closing = false;

  @override
  void dispose() {
    // The dialog route can still render during its closing animation after
    // showDialog's Future resolves. Its State owns the input for that lifetime.
    _controller.dispose();
    super.dispose();
  }

  void _finish(bool verified) {
    if (_closing) return;
    _closing = true;
    Navigator.pop(context, verified);
  }

  void _submit() {
    if (_closing) return;
    if (!widget.parentalControl
        .verifyChallenge(widget.challenge, _controller.text)) {
      setState(
          () => _errorText = AppLocalizations.of(context).ageGateWrongAnswer);
      return;
    }
    _finish(true);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      scrollable: true,
      title: Text(l10n.ageGateTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l10n.ageGateDescription),
          const SizedBox(height: AppSpacing.md),
          Text(widget.challenge.prompt, style: AppTextStyles.heading3),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: _controller,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submit(),
            decoration: InputDecoration(
              hintText: l10n.ageGateAnswerHint,
              errorText: _errorText,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
            onPressed: () => _finish(false), child: Text(l10n.ageGateCancel)),
        ElevatedButton(onPressed: _submit, child: Text(l10n.ageGateConfirm)),
      ],
    );
  }
}
