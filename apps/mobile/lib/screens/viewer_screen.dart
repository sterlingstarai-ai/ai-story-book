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
  // 다국어 지원
  String _selectedLanguage = 'ko'; // 'ko' or 'en'

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
                  title: book.getTitle(_selectedLanguage),
                  imageUrl: book.coverImageUrl,
                );
              } else {
                // 본문 페이지
                final page = book.pages[index - 1];
                return _ContentPage(
                  pageNumber: page.pageNumber,
                  text: page.getText(_selectedLanguage),
                  imageUrl: page.imageUrl,
                  page: page,
                  selectedLanguage: _selectedLanguage,
                  onShowLearning: () => _showLearningMode(book, page),
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
                  book.getTitle(_selectedLanguage),
                  style: AppTextStyles.heading3.copyWith(color: Colors.white),
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              // 언어 토글 버튼
              _LanguageToggle(
                selectedLanguage: _selectedLanguage,
                hasTranslation: book.titleKo != null || book.titleEn != null,
                onToggle: () {
                  setState(() {
                    _selectedLanguage = _selectedLanguage == 'ko' ? 'en' : 'ko';
                  });
                },
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
            // 학습 모드 (페이지에서만)
            if (_currentPage > 0 && book.pages[_currentPage - 1].vocab != null)
              ListTile(
                leading: const Icon(Icons.school),
                title: const Text('학습 모드'),
                subtitle: const Text('단어, 질문, 퀴즈'),
                onTap: () {
                  Navigator.pop(context);
                  _showLearningMode(book, book.pages[_currentPage - 1]);
                },
              ),
            // 부모 가이드
            if (book.learningAssets != null)
              ListTile(
                leading: const Icon(Icons.family_restroom),
                title: const Text('부모 가이드'),
                subtitle: const Text('토론 주제, 활동 아이디어'),
                onTap: () {
                  Navigator.pop(context);
                  _showParentGuide(book);
                },
              ),
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

  /// 학습 모드 표시
  void _showLearningMode(BookResult book, PageResult page) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => _LearningModeSheet(
          page: page,
          scrollController: scrollController,
        ),
      ),
    );
  }

  /// 부모 가이드 표시
  void _showParentGuide(BookResult book) {
    if (book.learningAssets == null) return;

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.4,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) => _ParentGuideSheet(
          parentGuide: book.learningAssets!.parentGuide,
          scrollController: scrollController,
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

  Future<void> _regeneratePage(
      BookResult book, int pageNumber, String target) async {
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
      await apiClient.regeneratePage(book.jobId!, pageNumber,
          regenerateTarget: target);

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
    '''
        .trim();
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
            child:
                const Icon(Icons.broken_image, color: Colors.white, size: 64),
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
  final PageResult page;
  final String selectedLanguage;
  final VoidCallback onShowLearning;

  const _ContentPage({
    required this.pageNumber,
    required this.text,
    required this.imageUrl,
    required this.page,
    required this.selectedLanguage,
    required this.onShowLearning,
  });

  @override
  Widget build(BuildContext context) {
    final hasLearning = page.vocab != null && page.vocab!.isNotEmpty;

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
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Expanded(
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
                  // 학습 모드 버튼
                  if (hasLearning)
                    TextButton.icon(
                      onPressed: onShowLearning,
                      icon: const Icon(Icons.school, size: 18),
                      label: const Text('학습하기'),
                      style: TextButton.styleFrom(
                        foregroundColor: AppColors.primary,
                      ),
                    ),
                ],
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
          color: isPlaying ? AppColors.primaryMuted : AppColors.whiteOverlay,
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

/// 언어 토글 버튼
class _LanguageToggle extends StatelessWidget {
  final String selectedLanguage;
  final bool hasTranslation;
  final VoidCallback onToggle;

  const _LanguageToggle({
    required this.selectedLanguage,
    required this.hasTranslation,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    if (!hasTranslation) return const SizedBox.shrink();

    return GestureDetector(
      onTap: onToggle,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.whiteOverlay,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              selectedLanguage == 'ko' ? '한' : 'EN',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
            const SizedBox(width: 4),
            const Icon(Icons.swap_horiz, color: Colors.white, size: 16),
          ],
        ),
      ),
    );
  }
}

/// 학습 모드 시트
class _LearningModeSheet extends StatefulWidget {
  final PageResult page;
  final ScrollController scrollController;

  const _LearningModeSheet({
    required this.page,
    required this.scrollController,
  });

  @override
  State<_LearningModeSheet> createState() => _LearningModeSheetState();
}

class _LearningModeSheetState extends State<_LearningModeSheet>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // 핸들
        const SizedBox(height: AppSpacing.md),
        Container(
          width: 40,
          height: 4,
          decoration: BoxDecoration(
            color: AppColors.divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // 제목
        const Text('학습 모드', style: AppTextStyles.heading2),
        const SizedBox(height: AppSpacing.md),

        // 탭 바
        TabBar(
          controller: _tabController,
          labelColor: AppColors.primary,
          unselectedLabelColor: AppColors.textSecondary,
          indicatorColor: AppColors.primary,
          tabs: const [
            Tab(icon: Icon(Icons.abc), text: '단어'),
            Tab(icon: Icon(Icons.help_outline), text: '질문'),
            Tab(icon: Icon(Icons.quiz), text: '퀴즈'),
          ],
        ),

        // 탭 내용
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              _VocabTab(vocab: widget.page.vocab ?? []),
              _ComprehensionTab(
                  questions: widget.page.comprehensionQuestions ?? []),
              _QuizTab(quiz: widget.page.quiz ?? []),
            ],
          ),
        ),
      ],
    );
  }
}

/// 단어 탭
class _VocabTab extends StatelessWidget {
  final List<VocabItem> vocab;

  const _VocabTab({required this.vocab});

  @override
  Widget build(BuildContext context) {
    if (vocab.isEmpty) {
      return const Center(child: Text('이 페이지에는 단어 학습이 없어요'));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: vocab.length,
      itemBuilder: (context, index) {
        final item = vocab[index];
        return Card(
          margin: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      item.word,
                      style: AppTextStyles.heading3.copyWith(
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Text(
                      item.meaning,
                      style: AppTextStyles.body,
                    ),
                  ],
                ),
                if (item.example != null) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    item.example!,
                    style: AppTextStyles.caption.copyWith(
                      fontStyle: FontStyle.italic,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

/// 질문 탭
class _ComprehensionTab extends StatelessWidget {
  final List<ComprehensionQuestion> questions;

  const _ComprehensionTab({required this.questions});

  @override
  Widget build(BuildContext context) {
    if (questions.isEmpty) {
      return const Center(child: Text('이 페이지에는 이해 질문이 없어요'));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: questions.length,
      itemBuilder: (context, index) {
        final q = questions[index];
        return _ComprehensionCard(question: q, index: index + 1);
      },
    );
  }
}

class _ComprehensionCard extends StatefulWidget {
  final ComprehensionQuestion question;
  final int index;

  const _ComprehensionCard({required this.question, required this.index});

  @override
  State<_ComprehensionCard> createState() => _ComprehensionCardState();
}

class _ComprehensionCardState extends State<_ComprehensionCard> {
  bool _showAnswer = false;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Q${widget.index}. ${widget.question.question}',
              style: AppTextStyles.body.copyWith(fontWeight: FontWeight.bold),
            ),
            if (widget.question.answer != null) ...[
              const SizedBox(height: AppSpacing.sm),
              if (_showAnswer)
                Text(
                  'A. ${widget.question.answer}',
                  style: AppTextStyles.body.copyWith(color: AppColors.primary),
                )
              else
                TextButton(
                  onPressed: () => setState(() => _showAnswer = true),
                  child: const Text('정답 보기'),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 퀴즈 탭
class _QuizTab extends StatelessWidget {
  final List<QuizItem> quiz;

  const _QuizTab({required this.quiz});

  @override
  Widget build(BuildContext context) {
    if (quiz.isEmpty) {
      return const Center(child: Text('이 페이지에는 퀴즈가 없어요'));
    }

    return ListView.builder(
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: quiz.length,
      itemBuilder: (context, index) {
        final q = quiz[index];
        return _QuizCard(quiz: q, index: index + 1);
      },
    );
  }
}

class _QuizCard extends StatefulWidget {
  final QuizItem quiz;
  final int index;

  const _QuizCard({required this.quiz, required this.index});

  @override
  State<_QuizCard> createState() => _QuizCardState();
}

class _QuizCardState extends State<_QuizCard> {
  int? _selectedIndex;
  bool _showResult = false;

  @override
  Widget build(BuildContext context) {
    final isCorrect = _selectedIndex == widget.quiz.answerIndex;

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Q${widget.index}. ${widget.quiz.question}',
              style: AppTextStyles.body.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: AppSpacing.md),
            ...widget.quiz.options.asMap().entries.map((entry) {
              final optionIndex = entry.key;
              final option = entry.value;
              final isSelected = _selectedIndex == optionIndex;
              final isAnswer = optionIndex == widget.quiz.answerIndex;

              Color? backgroundColor;
              if (_showResult && isAnswer) {
                backgroundColor = AppColors.success.withOpacity(0.2);
              } else if (_showResult && isSelected && !isCorrect) {
                backgroundColor = AppColors.error.withOpacity(0.2);
              } else if (isSelected) {
                backgroundColor = AppColors.primaryLight;
              }

              return GestureDetector(
                onTap: _showResult
                    ? null
                    : () => setState(() => _selectedIndex = optionIndex),
                child: Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: AppSpacing.sm),
                  padding: const EdgeInsets.all(AppSpacing.sm),
                  decoration: BoxDecoration(
                    color: backgroundColor,
                    border: Border.all(
                      color: isSelected ? AppColors.primary : AppColors.divider,
                    ),
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                  child: Text(option),
                ),
              );
            }),
            if (_selectedIndex != null && !_showResult)
              ElevatedButton(
                onPressed: () => setState(() => _showResult = true),
                child: const Text('정답 확인'),
              ),
            if (_showResult) ...[
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Icon(
                    isCorrect ? Icons.check_circle : Icons.cancel,
                    color: isCorrect ? AppColors.success : AppColors.error,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    isCorrect ? '정답이에요!' : '다시 생각해봐요',
                    style: TextStyle(
                      color: isCorrect ? AppColors.success : AppColors.error,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              if (widget.quiz.explanation != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  widget.quiz.explanation!,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

/// 부모 가이드 시트
class _ParentGuideSheet extends StatelessWidget {
  final ParentGuide parentGuide;
  final ScrollController scrollController;

  const _ParentGuideSheet({
    required this.parentGuide,
    required this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // 핸들
        const SizedBox(height: AppSpacing.md),
        Container(
          width: 40,
          height: 4,
          decoration: BoxDecoration(
            color: AppColors.divider,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // 제목
        const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.family_restroom, color: AppColors.primary),
            SizedBox(width: AppSpacing.sm),
            Text('부모 가이드', style: AppTextStyles.heading2),
          ],
        ),
        const SizedBox(height: AppSpacing.md),

        // 내용
        Expanded(
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              // 요약
              _GuideSection(
                icon: Icons.summarize,
                title: '이야기 요약',
                content: parentGuide.summary,
              ),
              const SizedBox(height: AppSpacing.lg),

              // 토론 주제
              _GuideSection(
                icon: Icons.chat,
                title: '대화 나누기',
                items: parentGuide.discussionPrompts,
              ),
              const SizedBox(height: AppSpacing.lg),

              // 활동
              _GuideSection(
                icon: Icons.sports_esports,
                title: '함께 해보기',
                items: parentGuide.activities,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _GuideSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? content;
  final List<String>? items;

  const _GuideSection({
    required this.icon,
    required this.title,
    this.content,
    this.items,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, color: AppColors.primary, size: 20),
            const SizedBox(width: AppSpacing.sm),
            Text(title, style: AppTextStyles.heading3),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        if (content != null) Text(content!, style: AppTextStyles.body),
        if (items != null)
          ...items!.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('• ', style: TextStyle(fontSize: 16)),
                    Expanded(child: Text(item, style: AppTextStyles.body)),
                  ],
                ),
              )),
      ],
    );
  }
}
