import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/api_client.dart';
import '../utils/constants.dart';

/// 부분 재생성(인페인트) — 페이지 이미지 위에 수정할 영역을 손가락으로 칠하고,
/// 어떻게 바꿀지 입력하면 마스크 영역만 다시 그린다.
///
/// 결과: Navigator.pop(context, true)=성공(반영됨) / false=미지원→전체 재생성 폴백 권장.
class InpaintScreen extends ConsumerStatefulWidget {
  const InpaintScreen({
    super.key,
    required this.jobId,
    required this.bookId,
    required this.pageNumber,
    required this.imageUrl,
  });

  final String jobId;
  final String bookId;
  final int pageNumber;
  final String imageUrl;

  @override
  ConsumerState<InpaintScreen> createState() => _InpaintScreenState();
}

class _InpaintScreenState extends ConsumerState<InpaintScreen> {
  static const double _brush = 36;

  final _promptController = TextEditingController();
  final GlobalKey _canvasKey = GlobalKey();
  final List<List<Offset>> _strokes = [];
  bool _isLoading = false;

  @override
  void dispose() {
    _promptController.dispose();
    super.dispose();
  }

  void _startStroke(Offset p) => setState(() => _strokes.add([p]));

  void _extendStroke(Offset p) {
    if (_strokes.isEmpty) return;
    setState(() => _strokes.last.add(p));
  }

  /// 스트로크를 흑백 마스크 PNG로 래스터화(흰색=재생성 영역, 검정=유지).
  Future<Uint8List?> _rasterizeMask(Size size) async {
    if (_strokes.isEmpty) return null;
    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF000000),
    );
    final brush = Paint()
      ..color = const Color(0xFFFFFFFF)
      ..strokeWidth = _brush
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke;
    for (final stroke in _strokes) {
      if (stroke.length == 1) {
        canvas.drawCircle(
          stroke.first,
          _brush / 2,
          Paint()..color = const Color(0xFFFFFFFF),
        );
        continue;
      }
      final path = Path()..moveTo(stroke.first.dx, stroke.first.dy);
      for (final p in stroke.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, brush);
    }
    final picture = recorder.endRecording();
    final image =
        await picture.toImage(size.width.round(), size.height.round());
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    return bytes?.buffer.asUint8List();
  }

  Future<void> _apply() async {
    final l = AppLocalizations.of(context);
    final prompt = _promptController.text.trim();
    if (_strokes.isEmpty || prompt.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.inpaintNeedRegionAndPrompt)),
      );
      return;
    }
    final box = _canvasKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return;
    final maskBytes = await _rasterizeMask(box.size);
    if (maskBytes == null) return;

    setState(() => _isLoading = true);
    try {
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/inpaint_mask_${widget.pageNumber}.png');
      await file.writeAsBytes(maskBytes, flush: true);

      final newJobId = await ref.read(apiClientProvider).inpaintPage(
            widget.jobId,
            widget.pageNumber,
            file,
            prompt,
          );
      await _waitForJob(newJobId);
      if (!mounted) return;
      ref.invalidate(bookDetailProvider(widget.bookId));
      Navigator.pop(context, true);
    } on InpaintUnsupportedException {
      if (!mounted) return;
      setState(() => _isLoading = false);
      Navigator.pop(context, false); // 호출부가 전체 재생성으로 폴백
    } catch (_) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l.inpaintFailed),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  Future<void> _waitForJob(String jobId) async {
    final api = ref.read(apiClientProvider);
    for (var i = 0; i < 40 && mounted; i++) {
      await Future.delayed(const Duration(seconds: 1));
      try {
        final js = await api.getBookStatus(jobId);
        if (js.isComplete || js.isFailed) return;
      } catch (_) {
        // 일시적 오류는 무시하고 재시도
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l.inpaintTitle)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Text(l.inpaintInstructions, style: AppTextStyles.bodySmall),
          ),
          Expanded(
            child: Center(
              child: AspectRatio(
                aspectRatio: 3 / 4,
                child: GestureDetector(
                  onPanStart: (d) => _startStroke(d.localPosition),
                  onPanUpdate: (d) => _extendStroke(d.localPosition),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    child: Stack(
                      key: _canvasKey,
                      fit: StackFit.expand,
                      children: [
                        CachedNetworkImage(
                          imageUrl: widget.imageUrl,
                          fit: BoxFit.cover,
                        ),
                        CustomPaint(painter: _MaskPainter(_strokes)),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              children: [
                TextField(
                  controller: _promptController,
                  maxLength: 200,
                  enabled: !_isLoading,
                  decoration: InputDecoration(
                    labelText: l.inpaintRegionPromptLabel,
                    hintText: l.inpaintRegionPromptHint,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  children: [
                    TextButton.icon(
                      onPressed: _isLoading
                          ? null
                          : () => setState(() => _strokes.clear()),
                      icon: const Icon(Icons.undo),
                      label: Text(l.inpaintReset),
                    ),
                    const Spacer(),
                    FilledButton(
                      onPressed: _isLoading ? null : _apply,
                      child: _isLoading
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : Text(l.inpaintApply),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 화면에 칠한 영역을 반투명 하이라이트로 표시(실제 마스크는 _rasterizeMask가 생성).
class _MaskPainter extends CustomPainter {
  const _MaskPainter(this.strokes);

  final List<List<Offset>> strokes;

  @override
  void paint(Canvas canvas, Size size) {
    final brush = Paint()
      ..color = AppColors.primary.withValues(alpha: 0.45)
      ..strokeWidth = _InpaintScreenState._brush
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..style = PaintingStyle.stroke;
    for (final stroke in strokes) {
      if (stroke.length == 1) {
        canvas.drawCircle(
          stroke.first,
          _InpaintScreenState._brush / 2,
          Paint()..color = AppColors.primary.withValues(alpha: 0.45),
        );
        continue;
      }
      final path = Path()..moveTo(stroke.first.dx, stroke.first.dy);
      for (final p in stroke.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, brush);
    }
  }

  @override
  bool shouldRepaint(_MaskPainter oldDelegate) => true;
}
