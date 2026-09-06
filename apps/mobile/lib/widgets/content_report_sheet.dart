import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../models/content_report.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import 'age_gate_dialog.dart';
import 'common_widgets.dart';

/// Reporting stays in the reader and reuses the existing parent session gate.
Future<void> showContentReportSheet(
  BuildContext context,
  WidgetRef ref, {
  required String bookId,
  required int pageNumber,
}) async {
  if (!await ensureAgeGate(context, ref) || !context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (context) => ContentReportSheet(
      bookId: bookId,
      pageNumber: pageNumber,
    ),
  );
}

class ContentReportSheet extends ConsumerStatefulWidget {
  final String bookId;
  final int pageNumber;

  const ContentReportSheet({
    super.key,
    required this.bookId,
    required this.pageNumber,
  });

  @override
  ConsumerState<ContentReportSheet> createState() => _ContentReportSheetState();
}

class _ContentReportSheetState extends ConsumerState<ContentReportSheet> {
  ContentReportReason? _reason;
  bool _sending = false;
  bool _failed = false;
  ContentReportReceipt? _receipt;

  Future<void> _submit() async {
    final reason = _reason;
    if (_sending || reason == null) return;
    setState(() {
      _sending = true;
      _failed = false;
    });
    try {
      final receipt = await ref.read(apiClientProvider).reportBookContent(
            widget.bookId,
            pageNumber: widget.pageNumber,
            reason: reason,
          );
      if (!mounted) return;
      setState(() => _receipt = receipt);
    } catch (_) {
      if (!mounted) return;
      setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  String _label(ContentReportReason reason, AppLocalizations l) =>
      switch (reason) {
        ContentReportReason.harmfulContent => l.reportContentHarmful,
        ContentReportReason.sexualContent => l.reportContentSexual,
        ContentReportReason.hateOrBullying => l.reportContentHate,
        ContentReportReason.personalInformation => l.reportContentPersonal,
        ContentReportReason.imageProblem => l.reportContentImage,
        ContentReportReason.other => l.reportContentOther,
      };

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final receipt = _receipt;
    return PopScope(
      canPop: !_sending,
      child: AdaptiveModalSheet(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.reportContentTitle, style: AppTextStyles.heading2),
              const SizedBox(height: AppSpacing.sm),
              if (receipt != null) ...[
                Text({'resolved', 'dismissed'}.contains(receipt.status)
                    ? l.reportContentAlreadyReviewed
                    : l.reportContentReceived),
                const SizedBox(height: AppSpacing.lg),
                FilledButton(
                  style:
                      FilledButton.styleFrom(minimumSize: const Size(64, 64)),
                  onPressed: () => Navigator.pop(context),
                  child: Text(l.reportContentClose),
                ),
              ] else ...[
                Text(widget.pageNumber == 0
                    ? l.reportContentCover
                    : l.reportContentPage(widget.pageNumber)),
                const SizedBox(height: AppSpacing.sm),
                Text(l.reportContentHint),
                const SizedBox(height: AppSpacing.sm),
                RadioGroup<ContentReportReason>(
                  groupValue: _reason,
                  onChanged: (value) {
                    if (!_sending) setState(() => _reason = value);
                  },
                  child: Column(
                    children: [
                      for (final reason in ContentReportReason.values)
                        RadioListTile<ContentReportReason>(
                          contentPadding: EdgeInsets.zero,
                          visualDensity: const VisualDensity(vertical: 4),
                          value: reason,
                          enabled: !_sending,
                          title: Text(_label(reason, l)),
                        ),
                    ],
                  ),
                ),
                if (_failed)
                  Semantics(
                    liveRegion: true,
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.md),
                      child: Text(l.reportContentFailed,
                          style: const TextStyle(color: AppColors.error)),
                    ),
                  ),
                FilledButton(
                  key: const Key('content-report-submit'),
                  style:
                      FilledButton.styleFrom(minimumSize: const Size(64, 64)),
                  onPressed: _sending || _reason == null ? null : _submit,
                  child: Text(_sending
                      ? l.reportContentSending
                      : l.reportContentSubmit),
                ),
                TextButton(
                  style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
                  onPressed: _sending ? null : () => Navigator.pop(context),
                  child: Text(l.reportContentCancel),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
