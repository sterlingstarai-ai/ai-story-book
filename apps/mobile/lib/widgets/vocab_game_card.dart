import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../utils/constants.dart';

/// 어휘 맞추기 게임 카드 — "단어의 뜻은?" 4지선다, 즉시 피드백.
///
/// 자체완결형(item·allMeanings·onAnswered만 받음)이라 단위 위젯 테스트가 가능하다.
/// 뷰어 학습모드(viewer_screen)에서 사용. 정답 1회 채점 후 잠금, 정답 시 햅틱+별 보상.
class VocabGameCard extends StatefulWidget {
  final VocabItem item;
  final List<String> allMeanings;
  final void Function(bool correct)? onAnswered;

  const VocabGameCard({
    super.key,
    required this.item,
    required this.allMeanings,
    this.onAnswered,
  });

  @override
  State<VocabGameCard> createState() => _VocabGameCardState();
}

class _VocabGameCardState extends State<VocabGameCard> {
  late final List<String> _choices;
  String? _selected;

  @override
  void initState() {
    super.initState();
    final correct = widget.item.meaning;
    final distractors = widget.allMeanings.where((m) => m != correct).toList()
      ..shuffle();
    _choices = <String>{correct, ...distractors.take(3)}.toList()..shuffle();
  }

  void _pick(String meaning) {
    if (_selected != null) {
      return; // 한 번만 채점
    }
    final isCorrect = meaning == widget.item.meaning;
    // 즉각적·감각적 보상 — 아이의 반복 동기(정답 시 햅틱 + 별 튀어오름 애니).
    if (isCorrect) {
      HapticFeedback.mediumImpact();
    } else {
      HapticFeedback.selectionClick();
    }
    setState(() => _selected = meaning);
    widget.onAnswered?.call(isCorrect);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final answered = _selected != null;
    final correct = _selected == widget.item.meaning;
    return Card(
      key: const Key('vocab_game_card'),
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.vocabGameQuestion(widget.item.word),
              style: AppTextStyles.heading3,
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final choice in _choices) _choiceTile(context, choice),
            if (answered) ...[
              const SizedBox(height: AppSpacing.sm),
              correct
                  ? TweenAnimationBuilder<double>(
                      tween: Tween(begin: 0.6, end: 1.0),
                      duration: const Duration(milliseconds: 320),
                      curve: Curves.elasticOut,
                      builder: (context, scale, child) => Transform.scale(
                        scale: scale,
                        alignment: Alignment.centerLeft,
                        child: child,
                      ),
                      child: Text(
                        l10n.vocabGameCorrectFeedback,
                        style: AppTextStyles.body.copyWith(
                          color: AppColors.success,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    )
                  : Text(
                      l10n.vocabGameIncorrectFeedback(widget.item.meaning),
                      style: AppTextStyles.bodySmall.copyWith(
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _choiceTile(BuildContext context, String choice) {
    final l10n = AppLocalizations.of(context);
    final answered = _selected != null;
    final isCorrect = choice == widget.item.meaning;
    final isPicked = choice == _selected;
    Color border = AppColors.divider;
    Color? bg;
    if (answered && isCorrect) {
      border = AppColors.success;
      bg = AppColors.successLight;
    } else if (answered && isPicked && !isCorrect) {
      border = AppColors.error;
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Semantics(
        button: !answered,
        selected: isPicked,
        label: l10n.vocabGameChoiceLabel(choice),
        child: InkWell(
          onTap: answered ? null : () => _pick(choice),
          borderRadius: BorderRadius.circular(AppRadius.md),
          child: Container(
            width: double.infinity,
            constraints: const BoxConstraints(minHeight: 48),
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.md, vertical: AppSpacing.sm),
            decoration: BoxDecoration(
              color: bg,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: border, width: 1.5),
            ),
            child: Row(
              children: [
                Expanded(child: Text(choice, style: AppTextStyles.body)),
                if (answered && isCorrect)
                  const Icon(Icons.check_circle,
                      color: AppColors.success, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
