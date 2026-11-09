import 'dart:async';
import 'dart:io';

import '../widgets/age_gate_dialog.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:uuid/uuid.dart';
import '../core/api_error.dart';
import 'account_recovery_screen.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../services/book_media_store.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';

/// 서재 화면
class LibraryScreen extends ConsumerStatefulWidget {
  const LibraryScreen({super.key, this.browsingJobId});

  final String? browsingJobId;

  @override
  ConsumerState<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends ConsumerState<LibraryScreen> {
  static const _scrollThreshold = 320.0;
  static const _uuid = Uuid();
  final ScrollController _scrollController = ScrollController();
  // H18: 시리즈 생성 시도-단위 멱등키(재시도 시 재사용, 성공 시 리셋).
  // #20: 대상(시리즈/직전 권) 서명과 함께 보관한다. 서명 없이 '??='만 쓰면 실패 후
  // '다른' 시리즈의 다음 권을 만들 때 이전 키가 재사용돼 서버가 이전 잡을 그대로 돌려준다
  // (의도한 새 생성이 조용히 no-op). createBook의 _attemptSig 패턴과 동일.
  String? _seriesAttemptKey;
  String? _seriesAttemptSig;
  bool _checkingDeletions = false;
  Object? _browsingJobScope;

  Future<void> _recheckDeletions() async {
    if (_checkingDeletions) return;
    setState(() => _checkingDeletions = true);
    var waiting = true;
    final api = ref.read(apiClientProvider);
    try {
      ref.invalidate(bookMediaStoreProvider);
      await ref.read(bookMediaStoreProvider.future);
      if (!identical(api, ref.read(apiClientProvider))) {
        throw const BookDeletionUnconfirmed();
      }
      ref.invalidate(pendingBookDeletionsProvider);
      waiting = (await ref.read(
        pendingBookDeletionsProvider.future,
      )).isNotEmpty;
      ref.invalidate(libraryProvider);
      ref.invalidate(libraryBrowseProvider);
    } catch (_) {
      waiting = true;
    }
    if (!mounted) return;
    setState(() => _checkingDeletions = false);
    final l = AppLocalizations.of(context);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          waiting
              ? l.libraryDeletionReviewWaiting
              : l.libraryDeletionReviewDone,
        ),
      ),
    );
  }

  Map<String, String> _sortLabels(AppLocalizations l) => {
    'newest': l.librarySortNewest,
    'oldest': l.librarySortOldest,
    'title': l.librarySortTitle,
  };

  Map<String, String> _styleLabels(AppLocalizations l) => {
    'watercolor': l.libraryStyleWatercolor,
    'cartoon': l.libraryStyleCartoon,
    '3d': l.libraryStyle3d,
    'pixel': l.libraryStylePixel,
    'oil_painting': l.libraryStyleOilPainting,
    'claymation': l.libraryStyleClaymation,
    'realistic': l.libraryStyleRealistic,
  };

  Map<String, String> _ageLabels(AppLocalizations l) => {
    '3-5': l.libraryAge3to5,
    '5-7': l.libraryAge5to7,
    '7-9': l.libraryAge7to9,
    'adult': l.libraryAgeAdult,
  };

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_handleScroll);
    final jobId = widget.browsingJobId;
    if (jobId != null) {
      final api = ref.read(apiClientProvider);
      _browsingJobScope = api;
      ref.listenManual(jobPollingProvider(jobId), (_, next) {
        final status = next.asData?.value;
        if (status == null || (!status.isComplete && !status.isFailed)) return;
        // The progress route is disposed while the reader browses the library.
        // Keep its poll alive here and preserve the library's selected filters.
        unawaited(
          Future<void>.microtask(() async {
            if (!mounted || !identical(api, ref.read(apiClientProvider))) {
              return;
            }
            ref.invalidate(activeBookGenerationsProvider);
            if (status.isComplete && status.result != null) {
              ref.invalidate(libraryProvider);
              await _refreshBrowseAfterGeneration(api);
            }
          }),
        );
      }, fireImmediately: true);
    }
  }

  @override
  void dispose() {
    _scrollController
      ..removeListener(_handleScroll)
      ..dispose();
    super.dispose();
  }

  void _handleScroll() {
    if (!_scrollController.hasClients) {
      return;
    }
    final remaining = _scrollController.position.extentAfter;
    if (remaining < _scrollThreshold) {
      ref.read(libraryBrowseProvider.notifier).loadMore();
    }
  }

  Future<void> _showRenameDialog(LibraryBook book) async {
    final l = AppLocalizations.of(context);
    final controller = TextEditingController(text: book.title);
    try {
      final result = await showDialog<String>(
        context: context,
        builder: (context) {
          return AlertDialog(
            title: Text(l.libraryRenameDialogTitle),
            content: TextField(
              controller: controller,
              maxLength: 80,
              decoration: InputDecoration(
                labelText: l.libraryRenameFieldLabel,
                hintText: l.libraryRenameFieldHint,
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: Text(l.libraryCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, controller.text.trim()),
                child: Text(l.librarySave),
              ),
            ],
          );
        },
      );

      if (!mounted || result == null) {
        return;
      }
      if (result.isEmpty || result == book.title) {
        return;
      }

      await ref
          .read(libraryBrowseProvider.notifier)
          .renameBook(book.id, result);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.libraryRenameSuccess)));
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_friendlyErrorMessage(error))));
    } finally {
      controller.dispose();
    }
  }

  Future<void> _confirmDelete(LibraryBook book) async {
    final l = AppLocalizations.of(context);
    final confirmed =
        await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.libraryDeleteDialogTitle),
            content: Text(l.libraryDeleteDialogContent(book.title)),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.libraryCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.red.shade600,
                ),
                child: Text(l.libraryDelete),
              ),
            ],
          ),
        ) ??
        false;

    if (!confirmed || !mounted) {
      return;
    }

    try {
      final purgePending = await ref
          .read(libraryBrowseProvider.notifier)
          .deleteBook(book.id);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            purgePending ? l.libraryDeletionPending : l.libraryDeleteSuccess,
          ),
        ),
      );
    } on BookDeletionNotStarted {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.libraryDeletionNotStarted)));
    } on BookDeletionUnconfirmed {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.libraryDeletionUnconfirmed)));
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_friendlyErrorMessage(error))));
    }
  }

  String _friendlyErrorMessage(Object error) {
    final l = AppLocalizations.of(context);
    if (error is ApiError) {
      return error.localizedMessage(l);
    }
    if (error is DioException) {
      return (error.error is ApiError
              ? error.error as ApiError
              : ApiError.fromDioException(error))
          .localizedMessage(l);
    }
    final raw = error.toString().toLowerCase();
    if (raw.contains('socketexception') ||
        raw.contains('network') ||
        raw.contains('connection')) {
      return l.libraryErrorNetwork;
    }
    return l.libraryErrorGeneric;
  }

  String _sanitizeFileName(String title) {
    return title
        .replaceAll(RegExp(r'[\\\\/:*?\"<>|]'), '_')
        .replaceAll(' ', '_');
  }

  Future<void> _shareBook(LibraryBook book) async {
    if (!await ensureAgeGate(context, ref) || !mounted) return;
    final l = AppLocalizations.of(context);
    final message = l.libraryShareMessage(book.title);
    final box = context.findRenderObject() as RenderBox?;
    final origin = box != null
        ? box.localToGlobal(Offset.zero) & box.size
        : const Rect.fromLTWH(0, 0, 100, 100);

    try {
      final request = await HttpClient().getUrl(Uri.parse(book.coverImageUrl));
      final response = await request.close();
      final bytes = await consolidateHttpClientResponseBytes(response);

      if (bytes.isEmpty) {
        throw const FileSystemException('empty cover image response');
      }

      final directory = await getTemporaryDirectory();
      final fileName = '${_sanitizeFileName(book.title)}_cover.jpg';
      final file = File('${directory.path}/$fileName');
      await file.writeAsBytes(bytes, flush: true);

      await Share.shareXFiles(
        [XFile(file.path)],
        text: message,
        sharePositionOrigin: origin,
      );
      return;
    } catch (_) {
      // 표지 다운로드 실패 시 텍스트 공유로 폴백한다.
    }

    try {
      await Share.share(message, sharePositionOrigin: origin);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l.libraryShareFailed),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final libraryAsync = ref.watch(libraryBrowseProvider);
    final jobs = ref.watch(visibleActiveBookGenerationsProvider);
    final browsingJobId = widget.browsingJobId;
    final browsingPoll =
        browsingJobId != null &&
            identical(ref.watch(apiClientProvider), _browsingJobScope)
        ? ref.watch(jobPollingProvider(browsingJobId))
        : null;
    final browsingStatus = browsingPoll?.asData?.value;
    final completedBookId = browsingStatus?.isComplete == true
        ? browsingStatus?.result?.bookId
        : null;
    final browsingFailed = browsingStatus?.isFailed == true;
    final browsingUnavailable =
        browsingPoll?.hasError == true ||
        (browsingStatus?.isComplete == true && completedBookId == null);
    ref.listen(activeBookGenerationsProvider, (previous, next) {
      // The per-job listener already handles a completion for its own job.
      final separatelyTracked = browsingUnavailable ? null : browsingJobId;
      if (activeBookGenerationMayHaveFinished(
        previous,
        next,
        separatelyTrackedJob: separatelyTracked,
      )) {
        final api = ref.read(apiClientProvider);
        unawaited(
          Future<void>.microtask(() => _refreshBrowseAfterGeneration(api)),
        );
      }
    });
    final pendingDeletions =
        ref.watch(pendingBookDeletionsProvider).valueOrNull ?? const [];
    final mediaStatus = ref.watch(bookMediaStoreProvider);
    final notifier = ref.read(libraryBrowseProvider.notifier);

    final sortLabels = _sortLabels(l);
    final styleLabels = _styleLabels(l);
    final ageLabels = _ageLabels(l);

    return AppShell(
      currentIndex: 2,
      appBar: AppBar(
        backgroundColor: AppPalette.of(context).background,
        elevation: 0,
        title: Text(l.libraryTitle, style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon: Icon(
              Icons.refresh,
              color: AppPalette.of(context).textPrimary,
            ),
            tooltip: l.libraryRefresh,
            onPressed: _refresh,
          ),
        ],
      ),
      body: Column(
        children: [
          if (completedBookId != null)
            TextButton.icon(
              style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: () {
                if (!identical(
                  ref.read(apiClientProvider),
                  _browsingJobScope,
                )) {
                  return;
                }
                Navigator.pushNamed(
                  context,
                  '/viewer',
                  arguments: completedBookId,
                );
              },
              icon: const Icon(Icons.menu_book_outlined),
              label: Text(l.libraryOpenCompletedStory),
            ),
          if (browsingJobId != null && (browsingFailed || browsingUnavailable))
            TextButton.icon(
              style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: () {
                if (!identical(
                  ref.read(apiClientProvider),
                  _browsingJobScope,
                )) {
                  return;
                }
                if (browsingUnavailable) {
                  ref.invalidate(jobPollingProvider(browsingJobId));
                }
                Navigator.pushNamed(
                  context,
                  '/loading',
                  arguments: browsingJobId,
                );
              },
              icon: const Icon(Icons.info_outline),
              label: Text(
                browsingFailed
                    ? l.libraryReviewFailedGeneration
                    : l.loadingCheckStatusButton,
              ),
            ),
          if (jobs.isNotEmpty)
            TextButton.icon(
              style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: _openActiveGeneration,
              icon: const Icon(Icons.auto_stories_outlined),
              label: Text(
                jobs.any((job) => job.isRechecking)
                    ? l.loadingCheckStatusButton
                    : l.libraryActiveGenerations(jobs.length),
              ),
            ),
          if (mediaStatus.hasError &&
              mediaStatus.error is BookMediaScopeConflict)
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.sm,
              ),
              child: Row(
                children: [
                  Expanded(child: Text(l.libraryMediaScopeReview)),
                  TextButton(
                    onPressed: _checkingDeletions ? null : _recheckDeletions,
                    style: TextButton.styleFrom(
                      minimumSize: const Size(64, 64),
                    ),
                    child: Text(l.libraryDeletionReviewAction),
                  ),
                ],
              ),
            ),
          if (pendingDeletions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.sm,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(l.libraryDeletionReviewTitle),
                        Text(
                          l.libraryDeletionReviewHelp,
                          style: AppTextStyles.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  TextButton(
                    onPressed: _checkingDeletions ? null : _recheckDeletions,
                    style: TextButton.styleFrom(
                      minimumSize: const Size(64, 64),
                    ),
                    child: _checkingDeletions
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(l.libraryDeletionReviewAction),
                  ),
                ],
              ),
            ),
          Expanded(
            child: libraryAsync.when(
              data: (state) {
                final hasFilter =
                    state.style != null || state.targetAge != null;
                final hasBooks = state.books.isNotEmpty;

                return Column(
                  children: [
                    _LibraryFilterPanel(
                      sort: state.sort,
                      style: state.style,
                      targetAge: state.targetAge,
                      sortLabels: sortLabels,
                      styleLabels: styleLabels,
                      ageLabels: ageLabels,
                      onSortChanged: notifier.setSort,
                      onStyleChanged: notifier.setStyleFilter,
                      onAgeChanged: notifier.setTargetAgeFilter,
                      onResetFilters: notifier.clearFilters,
                    ),
                    if (state.isOffline)
                      _OfflineBanner(onClose: notifier.clearOfflineBanner),
                    Expanded(
                      child: hasBooks
                          ? _buildBookContent(
                              state,
                              _refresh,
                              ageLabels,
                              styleLabels,
                            )
                          : EmptyState(
                              icon: hasFilter
                                  ? Icons.filter_alt_off_outlined
                                  : Icons.auto_stories_outlined,
                              title: hasFilter
                                  ? l.libraryEmptyFilterTitle
                                  : l.libraryEmptyTitle,
                              subtitle: hasFilter
                                  ? l.libraryEmptyFilterSubtitle
                                  : l.libraryEmptySubtitle,
                              buttonText: hasFilter
                                  ? l.libraryResetFilters
                                  : l.libraryCreateNew,
                              onButtonPressed: hasFilter
                                  ? notifier.clearFilters
                                  : () =>
                                        Navigator.pushNamed(context, '/create'),
                            ),
                    ),
                  ],
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => EmptyState(
                icon: Icons.wifi_off_rounded,
                title: l.libraryLoadError,
                subtitle: _friendlyErrorMessage(error),
                buttonText: _isExpiredAccount(error)
                    ? l.recoveryTitle
                    : l.libraryRetry,
                onButtonPressed: () {
                  if (_isExpiredAccount(error)) {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) =>
                            const AccountRecoveryScreen(restoreOnly: true),
                      ),
                    );
                  } else {
                    ref.invalidate(libraryBrowseProvider);
                  }
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _refresh() async {
    ref.invalidate(activeBookGenerationsProvider);
    await ref.read(libraryBrowseProvider.notifier).refresh();
  }

  Future<void> _refreshBrowseAfterGeneration(Object api) async {
    if (!mounted || !identical(api, ref.read(apiClientProvider))) return;
    try {
      await ref.read(libraryBrowseProvider.future);
    } catch (_) {
      // The generation may have finished while the first library read failed.
    }
    if (!mounted || !identical(api, ref.read(apiClientProvider))) return;
    await ref.read(libraryBrowseProvider.notifier).refresh();
  }

  Future<void> _openActiveGeneration() async {
    final jobs = ref.read(visibleActiveBookGenerationsProvider);
    if (jobs.isEmpty) return;
    final api = ref.read(apiClientProvider);
    final l = AppLocalizations.of(context);
    final jobId = jobs.length == 1
        ? jobs.single.jobId
        : await showModalBottomSheet<String>(
            context: context,
            isScrollControlled: true,
            builder: (context) => AdaptiveModalSheet(
              title: l.libraryActiveGenerations(jobs.length),
              child: Column(
                children: [
                  for (final (index, job) in jobs.indexed)
                    ListTile(
                      minTileHeight: AppSizing.minTouchTarget,
                      title: Text(l.libraryActiveGenerationItem(index + 1)),
                      subtitle: Text(
                        job.isRechecking
                            ? l.loadingStepRecheckingStatus
                            : job.status == JobState.queued
                            ? l.loadingStepWaiting
                            : '${job.progress}%',
                      ),
                      onTap: () => Navigator.pop(context, job.jobId),
                    ),
                ],
              ),
            ),
          );
    if (!mounted ||
        jobId == null ||
        !identical(api, ref.read(apiClientProvider))) {
      return;
    }
    if (jobId == widget.browsingJobId) {
      Navigator.pop(context);
      return;
    }
    await Navigator.pushNamed(context, '/loading', arguments: jobId);
    if (mounted) ref.invalidate(activeBookGenerationsProvider);
  }

  bool _isExpiredAccount(Object error) {
    final apiError = error is ApiError
        ? error
        : error is DioException && error.error is ApiError
        ? error.error as ApiError
        : null;
    return apiError?.statusCode == 401;
  }

  String _formatDate(DateTime date) {
    final l = AppLocalizations.of(context);
    final now = DateTime.now();
    final diff = now.difference(date);

    if (diff.inDays == 0) {
      return l.libraryDateToday;
    }
    if (diff.inDays == 1) {
      return l.libraryDateYesterday;
    }
    if (diff.inDays < 7) {
      return l.libraryDateDaysAgo(diff.inDays);
    }
    return l.libraryDateMonthDay(date.month, date.day);
  }

  /// 로드된 책을 시리즈별로 묶어 가로 책장 + 단권 그리드로 렌더한다.
  /// 그룹핑은 페이지네이션과 독립적인 순수 함수(로드된 책 기준).
  Widget _buildBookContent(
    LibraryBrowseState state,
    Future<void> Function() onRefresh,
    Map<String, String> ageLabels,
    Map<String, String> styleLabels,
  ) {
    final groups = <String, List<LibraryBook>>{};
    final standalone = <LibraryBook>[];
    for (final book in state.books) {
      final sid = book.seriesId;
      if (sid != null && sid.isNotEmpty) {
        groups.putIfAbsent(sid, () => []).add(book);
      } else {
        standalone.add(book);
      }
    }
    for (final volumes in groups.values) {
      volumes.sort(
        (a, b) => (a.seriesIndex ?? 0).compareTo(b.seriesIndex ?? 0),
      );
    }

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        controller: _scrollController,
        slivers: [
          for (final volumes in groups.values)
            SliverToBoxAdapter(
              child: _SeriesShelf(
                volumes: volumes,
                onOpen: (book) =>
                    Navigator.pushNamed(context, '/viewer', arguments: book.id),
                onAddVolume: () => _createNextVolume(volumes.last),
              ),
            ),
          if (standalone.isNotEmpty)
            SliverPadding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              sliver: SliverGrid(
                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2,
                  mainAxisSpacing: AppSpacing.md,
                  crossAxisSpacing: AppSpacing.md,
                  mainAxisExtent:
                      (MediaQuery.sizeOf(context).width -
                              AppSpacing.lg * 2 -
                              AppSpacing.md) /
                          2 /
                          0.9 +
                      MediaQuery.textScalerOf(context).scale(112),
                ),
                delegate: SliverChildBuilderDelegate((context, index) {
                  final book = standalone[index];
                  return _LibraryBookCard(
                    book: book,
                    onTap: () => Navigator.pushNamed(
                      context,
                      '/viewer',
                      arguments: book.id,
                    ),
                    onRename: () => _showRenameDialog(book),
                    onDelete: () => _confirmDelete(book),
                    onShare: () => _shareBook(book),
                    ageLabel: ageLabels[book.targetAge] ?? book.targetAge,
                    styleLabel: styleLabels[book.style] ?? book.style,
                    dateLabel: _formatDate(book.createdAt),
                  );
                }, childCount: standalone.length),
              ),
            ),
          if (state.hasMore)
            const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(AppSpacing.lg),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
          const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.lg)),
        ],
      ),
    );
  }

  /// 시리즈 다음 권 생성 — 같은 캐릭터/시리즈로 새 주제를 받아 생성 후 로딩으로 이동.
  Future<void> _createNextVolume(LibraryBook latest) async {
    final l = AppLocalizations.of(context);
    final characterId = latest.characterId;
    if (characterId == null || characterId.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.libraryErrorGeneric)));
      return;
    }
    final controller = TextEditingController();
    try {
      final topic = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(l.librarySeriesAddVolume),
          content: TextField(
            controller: controller,
            maxLength: 200,
            decoration: InputDecoration(
              labelText: l.createTopicLabel,
              hintText: l.createTopicHint,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: Text(l.libraryCancel),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: Text(l.createMakeButton),
            ),
          ],
        ),
      );
      if (!mounted || topic == null || topic.isEmpty) {
        return;
      }
      final attemptSig =
          '${latest.seriesId ?? ''}|${latest.id}|$characterId|$topic';
      if (_seriesAttemptKey == null || _seriesAttemptSig != attemptSig) {
        _seriesAttemptKey = _uuid.v4();
        _seriesAttemptSig = attemptSig;
      }
      final response = await ref
          .read(apiClientProvider)
          .createSeriesBook(
            characterId: characterId,
            topic: topic,
            seriesId: latest.seriesId,
            previousBookId: latest.id,
            // H19: 원작 스타일·연령대 상속(다음 권이 watercolor/5-7로 깨지지 않게).
            style: latest.style,
            targetAge: latest.targetAge,
            idempotencyKey: _seriesAttemptKey,
          );
      _seriesAttemptKey = null; // 성공 → 다음 생성은 새 키
      _seriesAttemptSig = null;
      if (!mounted) {
        return;
      }
      ref.invalidate(activeBookGenerationsProvider);
      Navigator.pushNamed(context, '/loading', arguments: response.jobId);
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_friendlyErrorMessage(error))));
    } finally {
      controller.dispose();
    }
  }
}

class _LibraryFilterPanel extends StatelessWidget {
  final String sort;
  final String? style;
  final String? targetAge;
  final Map<String, String> sortLabels;
  final Map<String, String> styleLabels;
  final Map<String, String> ageLabels;
  final ValueChanged<String> onSortChanged;
  final ValueChanged<String?> onStyleChanged;
  final ValueChanged<String?> onAgeChanged;
  final VoidCallback onResetFilters;

  const _LibraryFilterPanel({
    required this.sort,
    required this.style,
    required this.targetAge,
    required this.sortLabels,
    required this.styleLabels,
    required this.ageLabels,
    required this.onSortChanged,
    required this.onStyleChanged,
    required this.onAgeChanged,
    required this.onResetFilters,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final hasFilter = style != null || targetAge != null;

    return Container(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: AppPalette.of(context).divider),
        ),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: _LabeledDropdown(
                  label: l.librarySortLabel,
                  value: sort,
                  entries: sortLabels.entries.toList(),
                  nullLabel: null,
                  onChanged: (value) {
                    if (value != null) {
                      onSortChanged(value);
                    }
                  },
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: _LabeledDropdown(
                  label: l.libraryStyleLabel,
                  value: style,
                  entries: styleLabels.entries.toList(),
                  nullLabel: l.libraryFilterAll,
                  onChanged: onStyleChanged,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Expanded(
                child: _LabeledDropdown(
                  label: l.libraryAgeLabel,
                  value: targetAge,
                  entries: ageLabels.entries.toList(),
                  nullLabel: l.libraryFilterAll,
                  onChanged: onAgeChanged,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              if (MediaQuery.sizeOf(context).width < 360 ||
                  MediaQuery.textScalerOf(context).scale(16) > 20)
                IconButton(
                  tooltip: l.libraryResetFilters,
                  onPressed: hasFilter ? onResetFilters : null,
                  icon: const Icon(Icons.filter_alt_off_outlined),
                )
              else
                SizedBox(
                  height: AppSizing.minTouchTarget,
                  child: TextButton.icon(
                    onPressed: hasFilter ? onResetFilters : null,
                    icon: const Icon(Icons.filter_alt_off_outlined),
                    label: Text(l.libraryResetFilters),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LabeledDropdown extends StatelessWidget {
  static const String _allValue = '__all__';
  final String label;
  final String? value;
  final List<MapEntry<String, String>> entries;
  final String? nullLabel;
  final ValueChanged<String?> onChanged;

  const _LabeledDropdown({
    required this.label,
    required this.value,
    required this.entries,
    required this.nullLabel,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final resolvedValue = value ?? (nullLabel != null ? _allValue : null);
    return DropdownButtonFormField<String>(
      key: ValueKey<String?>(resolvedValue),
      initialValue: resolvedValue,
      isExpanded: true,
      itemHeight: AppSizing.minTouchTarget,
      selectedItemBuilder: (context) => [
        if (nullLabel != null)
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              nullLabel!,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ...entries.map(
          (entry) => Align(
            alignment: Alignment.centerLeft,
            child: Text(
              entry.value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
      ],
      decoration: InputDecoration(
        labelText: label,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 18,
        ),
      ),
      items: [
        if (nullLabel != null)
          DropdownMenuItem<String>(value: _allValue, child: Text(nullLabel!)),
        ...entries.map(
          (entry) => DropdownMenuItem<String>(
            value: entry.key,
            child: Text(entry.value),
          ),
        ),
      ],
      onChanged: (next) {
        if (next == _allValue) {
          onChanged(null);
          return;
        }
        onChanged(next);
      },
    );
  }
}

class _OfflineBanner extends StatelessWidget {
  final VoidCallback onClose;

  const _OfflineBanner({required this.onClose});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      color: AppPalette.of(context).isDark
          ? AppColors.warning.withValues(alpha: 0.15)
          : Colors.amber.shade100,
      child: Row(
        children: [
          const Icon(Icons.wifi_off_rounded, size: 18),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(l.libraryOfflineBanner, style: AppTextStyles.caption),
          ),
          IconButton(
            onPressed: onClose,
            icon: const Icon(Icons.close, size: 18),
            tooltip: l.libraryClose,
          ),
        ],
      ),
    );
  }
}

class _LibraryBookCard extends StatelessWidget {
  final LibraryBook book;
  final String ageLabel;
  final String styleLabel;
  final String dateLabel;
  final VoidCallback onTap;
  final VoidCallback onRename;
  final VoidCallback onDelete;
  final VoidCallback onShare;

  const _LibraryBookCard({
    required this.book,
    required this.ageLabel,
    required this.styleLabel,
    required this.dateLabel,
    required this.onTap,
    required this.onRename,
    required this.onDelete,
    required this.onShare,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Stack(
      children: [
        Positioned.fill(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: BookCard(
                  bookId: book.id,
                  title: book.title,
                  imageUrl: book.coverImageUrl,
                  subtitle: dateLabel,
                  onTap: onTap,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                children: [
                  if (book.seriesIndex != null)
                    _MiniChip(
                      label: '${l.librarySeriesBadge} ${book.seriesIndex}',
                      highlighted: true,
                    ),
                  _MiniChip(label: ageLabel),
                  _MiniChip(label: styleLabel),
                ],
              ),
            ],
          ),
        ),
        Positioned(
          right: 2,
          top: 2,
          child: Material(
            color: Colors.transparent,
            shape: const CircleBorder(),
            child: PopupMenuButton<_BookCardMenuAction>(
              tooltip: l.libraryBookOptions,
              style: IconButton.styleFrom(
                minimumSize: const Size(
                  AppSizing.minTouchTarget,
                  AppSizing.minTouchTarget,
                ),
              ),
              icon: Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppColors.whiteOverlayStrong,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.divider),
                ),
                child: const Icon(
                  Icons.more_horiz,
                  color: AppColors.textPrimary,
                  size: 20,
                ),
              ),
              onSelected: (value) {
                if (value == _BookCardMenuAction.rename) {
                  onRename();
                } else if (value == _BookCardMenuAction.share) {
                  onShare();
                } else if (value == _BookCardMenuAction.delete) {
                  onDelete();
                }
              },
              itemBuilder: (context) => [
                PopupMenuItem(
                  height: AppSizing.minTouchTarget,
                  value: _BookCardMenuAction.rename,
                  child: Row(
                    children: [
                      const Icon(Icons.drive_file_rename_outline, size: 20),
                      const SizedBox(width: AppSpacing.sm),
                      Text(l.libraryMenuRename),
                    ],
                  ),
                ),
                PopupMenuItem(
                  height: AppSizing.minTouchTarget,
                  value: _BookCardMenuAction.share,
                  child: Row(
                    children: [
                      const Icon(Icons.share_outlined, size: 20),
                      const SizedBox(width: AppSpacing.sm),
                      Text(l.libraryMenuShare),
                    ],
                  ),
                ),
                PopupMenuItem(
                  height: AppSizing.minTouchTarget,
                  value: _BookCardMenuAction.delete,
                  child: Row(
                    children: [
                      const Icon(
                        Icons.delete_outline,
                        size: 20,
                        color: Colors.red,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Text(l.libraryMenuDelete),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

enum _BookCardMenuAction { rename, share, delete }

class _MiniChip extends StatelessWidget {
  final String label;
  final bool highlighted;

  const _MiniChip({required this.label, this.highlighted = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: highlighted
            ? AppColors.primaryMedium
            : AppPalette.of(context).surface,
        border: Border.all(
          color: highlighted
              ? AppPalette.of(context).primary
              : AppPalette.of(context).divider,
        ),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption.copyWith(
          color: highlighted
              ? AppPalette.of(context).primary
              : AppPalette.of(context).textSecondary,
        ),
      ),
    );
  }
}

/// 동일 시리즈 책들을 가로로 보여주는 책장. 끝에 '다음 권 만들기' 타일.
class _SeriesShelf extends StatelessWidget {
  final List<LibraryBook> volumes;
  final void Function(LibraryBook book) onOpen;
  final VoidCallback onAddVolume;

  const _SeriesShelf({
    required this.volumes,
    required this.onOpen,
    required this.onAddVolume,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.md,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Row(
            children: [
              Icon(
                Icons.collections_bookmark_outlined,
                size: 18,
                color: AppPalette.of(context).primary,
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  '${l.librarySeriesBadge} · ${volumes.length}',
                  style: AppTextStyles.heading3,
                ),
              ),
            ],
          ),
        ),
        SizedBox(
          height: 144 + MediaQuery.textScalerOf(context).scale(80),
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            itemCount: volumes.length + 1,
            separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.md),
            itemBuilder: (context, index) {
              if (index >= volumes.length) {
                return _AddVolumeTile(onTap: onAddVolume);
              }
              final book = volumes[index];
              return SizedBox(
                width: 130,
                child: BookCard(
                  bookId: book.id,
                  title: book.title,
                  imageUrl: book.coverImageUrl,
                  subtitle: '${l.librarySeriesBadge} ${book.seriesIndex ?? ''}'
                      .trim(),
                  onTap: () => onOpen(book),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// 시리즈 책장 끝의 '다음 권 만들기' 타일.
class _AddVolumeTile extends StatelessWidget {
  final VoidCallback onTap;

  const _AddVolumeTile({required this.onTap});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return SizedBox(
      width: 130,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: AppPalette.of(context).primaryLight,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.primaryMedium),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.add_circle_outline,
                color: AppPalette.of(context).primary,
                size: 32,
              ),
              const SizedBox(height: AppSpacing.sm),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Text(
                  l.librarySeriesAddVolume,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.caption.copyWith(
                    color: AppPalette.of(context).primary,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
