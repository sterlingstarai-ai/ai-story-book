import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

/// M24: 사진 업로드 등 민감 진입점의 공용 보호자 게이트.
///
/// 세션 내 이미 검증됐으면 통과, 아니면 age gate 다이얼로그를 띄운다. 통과 시 true.
/// 두 사진 진입점(characters_screen._pickImage, character_source_sheet._usePhoto)이
/// 동일 게이트를 공유해 '게이트→JIT 동의' 이중 보호가 한쪽에만 적용되던 불일치를 없앤다.
Future<bool> ensureAgeGate(BuildContext context, WidgetRef ref) async {
  final parental = ref.read(parentalControlServiceProvider);
  if (parental.isAgeGateVerifiedForSession) {
    return true;
  }
  return showAgeGateDialog(context, ref);
}

Future<bool> showAgeGateDialog(BuildContext context, WidgetRef ref) async {
  final parentalControl = ref.read(parentalControlServiceProvider);
  final challenge = parentalControl.createChallenge();
  final controller = TextEditingController();
  String? errorText;

  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (context, setState) {
          final l10n = AppLocalizations.of(context);
          return AlertDialog(
            title: Text(l10n.ageGateTitle),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l10n.ageGateDescription),
                const SizedBox(height: AppSpacing.md),
                Text(
                  challenge.prompt,
                  style: AppTextStyles.heading3,
                ),
                const SizedBox(height: AppSpacing.sm),
                TextField(
                  controller: controller,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    hintText: l10n.ageGateAnswerHint,
                    errorText: errorText,
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(l10n.ageGateCancel),
              ),
              ElevatedButton(
                onPressed: () {
                  if (!parentalControl.verifyChallenge(
                      challenge, controller.text)) {
                    setState(() {
                      errorText = l10n.ageGateWrongAnswer;
                    });
                    return;
                  }
                  Navigator.pop(dialogContext, true);
                },
                child: Text(l10n.ageGateConfirm),
              ),
            ],
          );
        },
      );
    },
  );

  controller.dispose();

  if (result == true) {
    final prefs = ref.read(sharedPreferencesProvider);
    await parentalControl.persistAgeGateSession(prefs);
    return true;
  }
  return false;
}
