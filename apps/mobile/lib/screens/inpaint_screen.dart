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
import '../widgets/common_widgets.dart';

/// 부분 재생성(인페인트) — 페이지 이미지 위에 수정할 영역을 손가락으로 칠하고,
/// 어떻게 바꿀지 입력하면 마스크 영역만 다시 그린다.
///
/// 결과: Navigator.pop(context, true)=성공(반영됨) / false=미지원→전체 재생성 폴백 권장.
/// M25: 인페인트 잡의 최종 결과 — 실패/타임아웃을 성공으로 삼키지 않기 위한 구분.
enum _InpaintOutcome { completed, failed, timeout }

class InpaintScreen extends ConsumerStatefulWidget {
  const InpaintScreen({
    super.key,
    required this.jobId,
    required this.bookId,
    required this.pageNumber,
    required this.imageUrl,
    this.imageProvider,
  });

  final String jobId;
  final String bookId;
  final int pageNumber;
  final String imageUrl;

  /// Reuse an image already loaded by the host, or inject an in-memory image
  /// when testing the editor without native cache/storage plugins.
  final ImageProvider? imageProvider;

  @override
  ConsumerState<InpaintScreen> createState() => _InpaintScreenState();
}

class _InpaintScreenState extends ConsumerState<InpaintScreen> {
  static const double _brush = 36;

  final _promptController = TextEditingController();
  final GlobalKey _canvasKey = GlobalKey();
  final List<List<Offset>> _strokes = [];
  bool _isLoading = false;
  bool _imageReady = false;
  int _imageAttempt = 0;

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
    final image = await picture.toImage(
      size.width.round(),
      size.height.round(),
    );
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    picture.dispose();
    return bytes?.buffer.asUint8List();
  }

  Future<void> _apply() async {
    if (_isLoading || !_imageReady) return;
    final l = AppLocalizations.of(context);
    final api = ref.read(apiClientProvider);
    final prompt = _promptController.text.trim();
    if (_strokes.isEmpty || prompt.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.inpaintNeedRegionAndPrompt)));
      return;
    }
    final box = _canvasKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return;
    setState(() => _isLoading = true);
    File? temporaryMask;
    try {
      final maskBytes = await _rasterizeMask(box.size);
      if (maskBytes == null || !mounted) return;
      final dir = await getTemporaryDirectory();
      final file = File(
        '${dir.path}/inpaint_mask_${widget.pageNumber}_${DateTime.now().microsecondsSinceEpoch}.png',
      );
      temporaryMask = file;
      await file.writeAsBytes(maskBytes, flush: true);

      final newJobId = await api.inpaintPage(
        widget.jobId,
        widget.pageNumber,
        file,
        prompt,
      );
      // M25: 실패/타임아웃을 성공으로 오분류하지 않는다.
      if (!mounted) return;
      final outcome = await _waitForJob(newJobId);
      if (!mounted) return;
      switch (outcome) {
        case _InpaintOutcome.completed:
          ref.invalidate(bookDetailProvider(widget.bookId));
          Navigator.pop(context, true);
          break;
        case _InpaintOutcome.failed:
          setState(() => _isLoading = false);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(l.inpaintFailed),
              backgroundColor: AppColors.error,
            ),
          );
          break;
        case _InpaintOutcome.timeout:
          setState(() => _isLoading = false);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(l.inpaintApplyingRefreshLater)),
          );
          break;
      }
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
    } finally {
      if (mounted) setState(() => _isLoading = false);
      if (temporaryMask != null) {
        try {
          await temporaryMask.delete();
        } catch (_) {
          // The OS may already have removed a temporary file.
        }
      }
    }
  }

  Future<_InpaintOutcome> _waitForJob(String jobId) async {
    final api = ref.read(apiClientProvider);
    // M25: 예산을 이미지 타임아웃 스펙(90초×재시도)에 맞춰 확대(느린 성공 오분류 방지).
    final startedAt = DateTime.now();
    const budget = Duration(minutes: 3);
    while (mounted && DateTime.now().difference(startedAt) < budget) {
      await Future.delayed(const Duration(seconds: 1));
      try {
        final js = await api.getBookStatus(jobId);
        if (js.isComplete) return _InpaintOutcome.completed;
        if (js.isFailed) return _InpaintOutcome.failed;
      } catch (_) {
        // 일시적 오류는 무시하고 재시도
      }
    }
    return _InpaintOutcome.timeout;
  }

  void _markImageReady() {
    if (_imageReady) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !_imageReady) setState(() => _imageReady = true);
    });
  }

  Widget _imageError(BuildContext context) {
    final l = AppLocalizations.of(context);
    return ColoredBox(
      color: AppPalette.of(context).surface,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.image_not_supported_outlined, size: 40),
              const SizedBox(height: AppSpacing.sm),
              Text(l.inpaintImageLoadFailed, textAlign: TextAlign.center),
              TextButton.icon(
                style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
                onPressed: () => setState(() => _imageAttempt++),
                icon: const Icon(Icons.refresh),
                label: Text(l.retry),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _illustration() {
    final supplied = widget.imageProvider;
    if (supplied != null) {
      return Image(
        key: ValueKey(_imageAttempt),
        image: supplied,
        fit: BoxFit.cover,
        frameBuilder: (context, child, frame, synchronouslyLoaded) {
          if (frame != null || synchronouslyLoaded) _markImageReady();
          return child;
        },
        errorBuilder: (context, _, __) => _imageError(context),
      );
    }
    if (ref.watch(bookMediaBlockedProvider(widget.bookId))) {
      return _imageError(context);
    }
    final scope = ref.watch(bookMediaStoreProvider);
    if (scope.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (scope.hasError) return _imageError(context);
    final media = scope.valueOrNull;
    if (media == null) return _imageError(context);
    return CachedNetworkImage(
      key: ValueKey(_imageAttempt),
      imageUrl: widget.imageUrl,
      cacheManager: ref.watch(
        bookIllustrationCacheProvider((
          store: media.store,
          bookId: widget.bookId,
        )),
      ),
      fit: BoxFit.cover,
      imageBuilder: (context, provider) {
        _markImageReady();
        return Image(image: provider, fit: BoxFit.cover);
      },
      placeholder: (_, __) => const Center(child: CircularProgressIndicator()),
      errorWidget: (context, _, __) => _imageError(context),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l.inpaintTitle)),
      body: SafeArea(
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l.inpaintInstructions, style: AppTextStyles.bodySmall),
              const SizedBox(height: AppSpacing.md),
              Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 420),
                  child: AspectRatio(
                    aspectRatio: 3 / 4,
                    child: GestureDetector(
                      onTapUp: _isLoading || !_imageReady
                          ? null
                          : (d) => _startStroke(d.localPosition),
                      onPanStart: _isLoading || !_imageReady
                          ? null
                          : (d) => _startStroke(d.localPosition),
                      onPanUpdate: _isLoading || !_imageReady
                          ? null
                          : (d) => _extendStroke(d.localPosition),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        child: Stack(
                          key: _canvasKey,
                          fit: StackFit.expand,
                          children: [
                            _illustration(),
                            IgnorePointer(
                              child: CustomPaint(
                                painter: _MaskPainter(_strokes),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              TextButton.icon(
                style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
                onPressed: _isLoading || _strokes.isEmpty
                    ? null
                    : () => setState(() => _strokes.clear()),
                icon: const Icon(Icons.undo),
                label: Text(l.inpaintReset),
              ),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _promptController,
                maxLength: 200,
                minLines: 2,
                maxLines: 4,
                enabled: !_isLoading,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  labelText: l.inpaintRegionPromptLabel,
                  hintText: l.inpaintRegionPromptHint,
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              PrimaryButton(
                text: l.inpaintApply,
                isLoading: _isLoading,
                onPressed:
                    !_imageReady ||
                        _strokes.isEmpty ||
                        _promptController.text.trim().isEmpty
                    ? null
                    : _apply,
              ),
            ],
          ),
        ),
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
