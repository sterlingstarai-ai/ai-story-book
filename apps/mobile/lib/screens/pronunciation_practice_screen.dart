import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

class PronunciationPracticeScreen extends ConsumerStatefulWidget {
  const PronunciationPracticeScreen({
    super.key,
    required this.bookId,
    required this.pageNumber,
    required this.expectedText,
    this.language = 'ko',
  });

  final String bookId;
  final int pageNumber;
  final String expectedText;
  final String language;

  @override
  ConsumerState<PronunciationPracticeScreen> createState() =>
      _PronunciationPracticeScreenState();
}

class _PronunciationPracticeScreenState
    extends ConsumerState<PronunciationPracticeScreen> {
  late final TextEditingController _expectedController;
  final TextEditingController _transcriptController = TextEditingController();

  bool _isSubmitting = false;
  String? _errorMessage;
  double? _score;
  String? _feedback;

  @override
  void initState() {
    super.initState();
    _expectedController = TextEditingController(text: widget.expectedText);
  }

  @override
  void dispose() {
    _expectedController.dispose();
    _transcriptController.dispose();
    super.dispose();
  }

  Future<void> _evaluate() async {
    final l = AppLocalizations.of(context);
    final expected = _expectedController.text.trim();
    final transcript = _transcriptController.text.trim();

    if (expected.isEmpty || transcript.isEmpty) {
      setState(() => _errorMessage = l.pronunciationErrorBothRequired);
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final api = ref.read(apiClientProvider);
      final result = await api.evaluatePronunciation(
        bookId: widget.bookId,
        pageNumber: widget.pageNumber,
        transcript: transcript,
        expectedText: expected,
      );

      if (!mounted) {
        return;
      }
      setState(() {
        final scoreRaw = result['score'];
        if (scoreRaw is num) {
          _score = scoreRaw.toDouble();
        } else {
          _score = null;
        }
        _feedback = result['feedback']?.toString();
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() => _errorMessage = l.pronunciationErrorEvaluateFailed);
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _evaluateFromAudio() async {
    final l = AppLocalizations.of(context);
    final expected = _expectedController.text.trim();
    if (expected.isEmpty) {
      setState(() => _errorMessage = l.pronunciationErrorExpectedRequired);
      return;
    }

    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowMultiple: false,
      allowedExtensions: const ['m4a', 'mp3', 'wav', 'aac', 'ogg', 'webm'],
    );
    if (picked == null ||
        picked.files.isEmpty ||
        picked.files.first.path == null) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final audioFile = File(picked.files.first.path!);
      final api = ref.read(apiClientProvider);
      final result = await api.evaluatePronunciationAudio(
        audioFile: audioFile,
        expectedText: expected,
        bookId: widget.bookId,
        pageNumber: widget.pageNumber,
        language: widget.language, // H3: 책 언어로 발음 평가
      );
      if (!mounted) {
        return;
      }
      setState(() {
        final scoreRaw = result['score'];
        if (scoreRaw is num) {
          _score = scoreRaw.toDouble();
        } else {
          _score = null;
        }
        final transcript = result['transcript']?.toString();
        if (transcript != null && transcript.isNotEmpty) {
          _transcriptController.text = transcript;
        }
        _feedback = result['feedback']?.toString();
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() => _errorMessage = l.pronunciationErrorAudioEvaluateFailed);
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final score = _score;

    return Scaffold(
      appBar: AppBar(
        title: Text(l.pronunciationTitle),
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.divider),
            ),
            child: Text(
              l.pronunciationIntro(widget.pageNumber),
              style: AppTextStyles.bodySmall,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _expectedController,
            minLines: 2,
            maxLines: 4,
            decoration: InputDecoration(
              labelText: l.pronunciationExpectedLabel,
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _transcriptController,
            minLines: 3,
            maxLines: 6,
            decoration: InputDecoration(
              labelText: l.pronunciationTranscriptLabel,
              hintText: l.pronunciationTranscriptHint,
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          ElevatedButton.icon(
            onPressed: _isSubmitting ? null : _evaluate,
            icon: _isSubmitting
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.record_voice_over_outlined),
            label: Text(_isSubmitting
                ? l.pronunciationEvaluating
                : l.pronunciationEvaluateButton),
          ),
          const SizedBox(height: AppSpacing.sm),
          OutlinedButton.icon(
            onPressed: _isSubmitting ? null : _evaluateFromAudio,
            icon: const Icon(Icons.upload_file),
            label: Text(l.pronunciationEvaluateAudioButton),
          ),
          if (_errorMessage != null) ...[
            const SizedBox(height: AppSpacing.md),
            Text(
              _errorMessage!,
              style: AppTextStyles.bodySmall.copyWith(color: AppColors.error),
            ),
          ],
          if (score != null) ...[
            const SizedBox(height: AppSpacing.lg),
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadius.md),
                border: Border.all(color: AppColors.divider),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    l.pronunciationScore(score.toStringAsFixed(1)),
                    style: AppTextStyles.heading3,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  LinearProgressIndicator(
                    value: (score / 100).clamp(0.0, 1.0),
                    minHeight: 10,
                    borderRadius: BorderRadius.circular(99),
                    backgroundColor: AppColors.blackOverlayLight,
                    color: score >= 80
                        ? AppColors.success
                        : (score >= 60 ? AppColors.primary : AppColors.error),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    _feedback ?? l.pronunciationNoFeedback,
                    style: AppTextStyles.bodySmall,
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
