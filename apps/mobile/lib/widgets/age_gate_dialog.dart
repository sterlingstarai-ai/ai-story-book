import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

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
          return AlertDialog(
            title: const Text('부모 확인'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('구매 화면 접근 전 부모 확인이 필요해요.'),
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
                    hintText: '정답 입력',
                    errorText: errorText,
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('취소'),
              ),
              ElevatedButton(
                onPressed: () {
                  if (!parentalControl.verifyChallenge(
                      challenge, controller.text)) {
                    setState(() {
                      errorText = '정답이 아니에요.';
                    });
                    return;
                  }
                  Navigator.pop(dialogContext, true);
                },
                child: const Text('확인'),
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
