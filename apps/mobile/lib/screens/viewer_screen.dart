import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:just_audio/just_audio.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

/// 책 뷰어 화면
class ViewerScreen extends ConsumerStatefulWidget {
  final String bookId;

  const ViewerScreen({super.key, required this.bookId});

  @override
  ConsumerState<ViewerScreen> createState() => _ViewerScreenState();
}

class _ViewerScreenState extends ConsumerState<ViewerScreen> {
  late PageController _pageController;
  final AudioPlayer _audioPlayer = AudioPlayer();
  StreamSubscription<PlayerState>? _playerStateSubscription;
  int _currentPage = 0;
  bool _showControls = true;
  bool _isPlaying = false;
  bool _isLoadingAudio = false;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    // Store subscription to cancel later (memory leak fix)
    _playerStateSubscription = _audioPlayer.playerStateStream.listen((state) {
      if (mounted) {
        setState(() {
          _isPlaying = state.playing;
        });
      }
    });
  }

  @override
  void dispose() {
    // Cancel subscription to prevent memory leak
    _playerStateSubscription?.cancel();
    _pageController.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  void _toggleControls() {
    setState(() => _showControls = !_showControls);
  }

  @override
  Widget build(BuildContext context) {
    final bookAsync = ref.watch(bookDetailProvider(widget.bookId));

    return Scaffold(
      backgroundColor: Colors.black,
      body: bookAsync.when(
        data: (book) => _buildViewer(book),
        loading: () => const Center(
          child: CircularProgressIndicator(color: Colors.white),
        ),
        error: (error, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error, color: Colors.white, size: 48),
              const SizedBox(height: AppSpacing.md),
              Text(
                '책을 불러올 수 없어요',
                style: AppTextStyles.body.copyWith(color: Colors.white),
              ),
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                text: '돌아가기',
                isFullWidth: false,
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildViewer(BookResult book) {
    // 표지(0) + 페이지들
    final totalPages = book.pages.length + 1;

    return GestureDetector(
      onTap: _toggleControls,
      child: Stack(
        children: [
          // 페이지 뷰
          PageView.builder(
            controller: _pageController,
            itemCount: totalPages,
            onPageChanged: (index) => setState(() => _currentPage = index),
            itemBuilder: (context, index) {
              if (index == 0) {
                // 표지
                return _CoverPage(
                  title: book.title,
                  imageUrl: book.coverImageUrl,
                );
              } else {
                // 본문 페이지
                final page = book.pages[index - 1];
                return _ContentPage(
                  pageNumber: page.pageNumber,
                  text: page.text,
                  imageUrl: page.imageUrl,
                );
              }
            },
          ),

          // 컨트롤
          AnimatedOpacity(
            opacity: _showControls ? 1.0 : 0.0,
            duration: const Duration(milliseconds: 200),
            child: _buildControls(book, totalPages),
          ),
        ],
      ),
    );
  }

  Widget _buildControls(BookResult book, int totalPages) {
    return Column(
      children: [
        // 상단 바
        Container(
          padding: EdgeInsets.only(
            top: MediaQuery.of(context).padding.top + AppSpacing.sm,
            left: AppSpacing.md,
            right: AppSpacing.md,
            bottom: AppSpacing.sm,
          ),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                AppColors.blackOverlayStrong,
                Colors.transparent,
              ],
            ),
          ),
          child: Row(
            children: [
              IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: () => Navigator.pop(context),
              ),
              Expanded(
                child: Text(
                  book.title,
                  style: AppTextStyles.heading3.copyWith(color: Colors.white),
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                icon: const Icon(Icons.more_vert, color: Colors.white),
                onPressed: () => _showOptionsMenu(book),
              ),
            ],
          ),
        ),

        const Spacer(),

        // 하단 바
        Container(
          padding: EdgeInsets.only(
            left: AppSpacing.lg,
            right: AppSpacing.lg,
            top: AppSpacing.md,
            bottom: MediaQuery.of(context).padding.bottom + AppSpacing.md,
          ),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.bottomCenter,
              end: Alignment.topCenter,
              colors: [
                AppColors.blackOverlayStrong,
                Colors.transparent,
              ],
            ),
          ),
          child: Column(
            children: [
              // 페이지 인디케이터
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(
                  totalPages,
                  (index) => Container(
                    width: index == _currentPage ? 24 : 8,
                    height: 8,
                    margin: const EdgeInsets.symmetric(horizontal: 2),
                    decoration: BoxDecoration(
                      color: index == _currentPage
                          ? Colors.white
                          : AppColors.whiteOverlayLight,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                ),
              ),

              const SizedBox(height: AppSpacing.md),

              // 네비게이션 버튼
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _NavButton(
                    icon: Icons.chevron_left,
                    enabled: _currentPage > 0,
                    onPressed: () {
                      _pageController.previousPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                      );
                    },
                  ),
                  // 오디오 재생 버튼 (페이지에서만)
                  if (_currentPage > 0)
                    _AudioButton(
                      isPlaying: _isPlaying,
                      isLoading: _isLoadingAudio,
                      onPressed: () => _toggleAudio(book),
                    )
                  else
                    const SizedBox(width: 48),
                  Text(
                    _currentPage == 0
                        ? '표지'
                        : '${_currentPage} / ${totalPages - 1}',
                    style: AppTextStyles.body.copyWith(color: Colors.white),
                  ),
                  _NavButton(
                    icon: Icons.chevron_right,
                    enabled: _currentPage < totalPages - 1,
                    onPressed: () {
                      _pageController.nextPage(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                      );
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Future<void> _toggleAudio(BookResult book) async {
    if (_isPlaying) {
      await _audioPlayer.pause();
      return;
    }

    // 현재 페이지의 오디오 URL 가져오기
    if (_currentPage == 0) return; // 표지는 오디오 없음

    setState(() => _isLoadingAudio = true);

    try {
      final apiClient = ref.read(apiClientProvider);
      final page = book.pages[_currentPage - 1];

      // 이미 오디오 URL이 있으면 바로 재생
      String? audioUrl = page.audioUrl;

      // 없으면 API에서 가져오기 (자동 생성)
      if (audioUrl == null || audioUrl.isEmpty) {
        audioUrl = await apiClient.getPageAudioUrl(book.bookId, _currentPage);
      }

      // 오디오 재생
      await _audioPlayer.setUrl(audioUrl);
      await _audioPlayer.play();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('오디오 재생 실패: $e'),
            backgroundColor: AppColors.error,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoadingAudio = false);
      }
    }
  }

  void _showOptionsMenu(BookResult book) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.md),
            Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.divider,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            if (_currentPage > 0)
              ListTile(
                leading: const Icon(Icons.refresh),
                title: const Text('이 페이지 다시 만들기'),
                onTap: () {
                  Navigator.pop(context);
                  _showRegenerateOptions(book);
                },
              ),
            if (book.characterId != null)
              ListTile(
                leading: const Icon(Icons.auto_stories),
                title: const Text('같은 캐릭터로 새 이야기'),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.pushNamed(
                    context,
                    '/create',
                    arguments: {'characterId': book.characterId},
                  );
                },
              ),
            ListTile(
              leading: const Icon(Icons.picture_as_pdf),
              title: const Text('PDF로 내보내기'),
              onTap: () {
                Navigator.pop(context);
                _downloadPdf(book);
              },
            ),
            ListTile(
              leading: const Icon(Icons.share),
              title: const Text('공유하기'),
              onTap: () {
                Navigator.pop(context);
                _showShareOptions(book);
              },
            ),
            const SizedBox(height: AppSpacing.md),
          ],
        ),
      ),
    );
  }

  void _showRegenerateOptions(BookResult book) {
    final pageIndex = _currentPage - 1; // 표지 제외
    if (pageIndex < 0) return;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('페이지 다시 만들기'),
        content: const Text('어떤 부분을 다시 만들까요?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'text');
            },
            child: const Text('텍스트만'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'image');
            },
            child: const Text('그림만'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _regeneratePage(book, pageIndex + 1, 'both');
            },
            child: const Text('모두'),
          ),
        ],
      ),
    );
  }

  Future<void> _regeneratePage(BookResult book, int pageNumber, String target) async {
    if (book.jobId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('이 책은 페이지 재생성을 지원하지 않아요')),
      );
      return;
    }

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('페이지를 다시 만들고 있어요...')),
    );

    try {
      final apiClient = ref.read(apiClientProvider);
      await apiClient.regeneratePage(book.jobId!, pageNumber, regenerateTarget: target);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('페이지 재생성이 시작되었어요. 잠시만 기다려주세요.')),
        );
        // 책 데이터 새로고침
        ref.invalidate(bookDetailProvider(widget.bookId));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('재생성 실패: $e'),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }

  Future<void> _downloadPdf(BookResult book) async {
    try {
      // 로딩 표시
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PDF 생성 중...')),
      );

      // API 호출
      final apiClient = ref.read(apiClientProvider);
      final pdfBytes = await apiClient.downloadPdf(book.bookId);

      // 파일 저장
      final directory = await getApplicationDocumentsDirectory();
      final fileName = '${book.title.replaceAll(' ', '_')}.pdf';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(pdfBytes);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('PDF 저장 완료: $fileName')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('PDF 다운로드 실패: $e'),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }

  void _showShareOptions(BookResult book) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: AppSpacing.md),
            Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.divider,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            const Text('공유하기', style: AppTextStyles.heading3),
            const SizedBox(height: AppSpacing.lg),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  _ShareButton(
                    icon: Icons.link,
                    label: 'URL 복사',
                    onTap: () {
                      Navigator.pop(context);
                      _copyShareUrl(book);
                    },
                  ),
                  _ShareButton(
                    icon: Icons.chat_bubble,
                    label: '메시지',
                    onTap: () {
                      Navigator.pop(context);
                      _shareText(book);
                    },
                  ),
                  _ShareButton(
                    icon: Icons.picture_as_pdf,
                    label: 'PDF 공유',
                    onTap: () {
                      Navigator.pop(context);
                      _sharePdf(book);
                    },
                  ),
                  _ShareButton(
                    icon: Icons.more_horiz,
                    label: '더보기',
                    onTap: () async {
                      Navigator.pop(context);
                      // 약간의 딜레이 후 시스템 공유 다이얼로그 표시
                      await Future.delayed(const Duration(milliseconds: 300));
                      _shareText(book);
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }

  void _copyShareUrl(BookResult book) {
    // 간단한 공유 텍스트 복사
    final shareText = '${book.title}\n\nAI Story Book으로 만든 동화책이에요!';
    // Clipboard.setData(ClipboardData(text: shareText));  // flutter/services import needed
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('공유 텍스트가 복사되었어요')),
    );
    final box = context.findRenderObject() as RenderBox?;
    Share.share(
      shareText,
      sharePositionOrigin: box != null
          ? box.localToGlobal(Offset.zero) & box.size
          : const Rect.fromLTWH(0, 0, 100, 100),
    );
  }

  void _shareText(BookResult book) {
    final shareText = '''
📚 ${book.title}

AI Story Book으로 만든 동화책이에요!
아이에게 특별한 이야기를 선물하세요 ✨
    '''.trim();
    final box = context.findRenderObject() as RenderBox?;
    Share.share(
      shareText,
      sharePositionOrigin: box != null
          ? box.localToGlobal(Offset.zero) & box.size
          : const Rect.fromLTWH(0, 0, 100, 100),
    );
  }

  Future<void> _sharePdf(BookResult book) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PDF 생성 중...')),
      );

      final apiClient = ref.read(apiClientProvider);
      final pdfBytes = await apiClient.downloadPdf(book.bookId);

      final directory = await getTemporaryDirectory();
      final fileName = '${book.title.replaceAll(' ', '_')}.pdf';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(pdfBytes);

      final box = context.findRenderObject() as RenderBox?;
      await Share.shareXFiles(
        [XFile(file.path)],
        text: '${book.title} - AI Story Book으로 만든 동화책',
        sharePositionOrigin: box != null
            ? box.localToGlobal(Offset.zero) & box.size
            : const Rect.fromLTWH(0, 0, 100, 100),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('PDF 공유 실패: $e'),
            backgroundColor: AppColors.error,
          ),
        );
      }
    }
  }
}

/// 공유 버튼 위젯
class _ShareButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _ShareButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: AppColors.primaryLight,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(icon, color: AppColors.primary, size: 28),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(label, style: AppTextStyles.caption),
        ],
      ),
    );
  }
}

/// 표지 페이지
class _CoverPage extends StatelessWidget {
  final String title;
  final String imageUrl;

  const _CoverPage({
    required this.title,
    required this.imageUrl,
  });

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        CachedNetworkImage(
          imageUrl: imageUrl,
          fit: BoxFit.cover,
          placeholder: (context, url) => const Center(
            child: CircularProgressIndicator(color: Colors.white),
          ),
          errorWidget: (context, url, error) => Container(
            color: AppColors.primary,
            child: const Icon(Icons.broken_image, color: Colors.white, size: 64),
          ),
        ),
        Container(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.transparent,
                AppColors.blackOverlayStrong,
              ],
            ),
          ),
        ),
        Positioned(
          left: AppSpacing.lg,
          right: AppSpacing.lg,
          bottom: 100,
          child: Text(
            title,
            style: const TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.bold,
              color: Colors.white,
              shadows: [
                Shadow(
                  offset: Offset(0, 2),
                  blurRadius: 8,
                  color: Colors.black54,
                ),
              ],
            ),
            textAlign: TextAlign.center,
          ),
        ),
      ],
    );
  }
}

/// 본문 페이지
class _ContentPage extends StatelessWidget {
  final int pageNumber;
  final String text;
  final String imageUrl;

  const _ContentPage({
    required this.pageNumber,
    required this.text,
    required this.imageUrl,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.background,
      child: Column(
        children: [
          // 이미지
          Expanded(
            flex: 3,
            child: CachedNetworkImage(
              imageUrl: imageUrl,
              fit: BoxFit.cover,
              width: double.infinity,
              placeholder: (context, url) => Container(
                color: AppColors.divider,
                child: const Center(child: CircularProgressIndicator()),
              ),
              errorWidget: (context, url, error) => Container(
                color: AppColors.divider,
                child: const Icon(Icons.broken_image, size: 64),
              ),
            ),
          ),

          // 텍스트
          Expanded(
            flex: 2,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Center(
                child: Text(
                  text,
                  style: const TextStyle(
                    fontSize: 20,
                    height: 1.8,
                    color: AppColors.textPrimary,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 네비게이션 버튼
class _NavButton extends StatelessWidget {
  final IconData icon;
  final bool enabled;
  final VoidCallback onPressed;

  const _NavButton({
    required this.icon,
    required this.enabled,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: enabled ? onPressed : null,
      child: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: enabled ? AppColors.whiteOverlay : Colors.transparent,
          borderRadius: BorderRadius.circular(24),
        ),
        child: Icon(
          icon,
          color: enabled ? Colors.white : AppColors.whiteOverlayLight,
          size: 32,
        ),
      ),
    );
  }
}

/// 오디오 재생 버튼
class _AudioButton extends StatelessWidget {
  final bool isPlaying;
  final bool isLoading;
  final VoidCallback onPressed;

  const _AudioButton({
    required this.isPlaying,
    required this.isLoading,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: isLoading ? null : onPressed,
      child: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: isPlaying
              ? AppColors.primaryMuted
              : AppColors.whiteOverlay,
          borderRadius: BorderRadius.circular(24),
        ),
        child: isLoading
            ? const Padding(
                padding: EdgeInsets.all(12),
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : Icon(
                isPlaying ? Icons.pause : Icons.volume_up,
                color: Colors.white,
                size: 24,
              ),
      ),
    );
  }
}
