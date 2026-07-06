import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/app_shell.dart';
import '../widgets/common_widgets.dart';

/// 서재 화면
class LibraryScreen extends ConsumerStatefulWidget {
  const LibraryScreen({super.key});

  @override
  ConsumerState<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends ConsumerState<LibraryScreen> {
  static const _scrollThreshold = 320.0;
  final ScrollController _scrollController = ScrollController();

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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.libraryRenameSuccess)),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendlyErrorMessage(error))),
      );
    } finally {
      controller.dispose();
    }
  }

  Future<void> _confirmDelete(LibraryBook book) async {
    final l = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.libraryDeleteDialogTitle),
            content: Text(
              l.libraryDeleteDialogContent(book.title),
            ),
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
      await ref.read(libraryBrowseProvider.notifier).deleteBook(book.id);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.libraryDeleteSuccess)),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendlyErrorMessage(error))),
      );
    }
  }

  String _friendlyErrorMessage(Object error) {
    final l = AppLocalizations.of(context);
    if (error is ApiError) {
      return error.userMessage;
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
      await Share.share(
        message,
        sharePositionOrigin: origin,
      );
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
    final notifier = ref.read(libraryBrowseProvider.notifier);

    final sortLabels = _sortLabels(l);
    final styleLabels = _styleLabels(l);
    final ageLabels = _ageLabels(l);

    return AppShell(
      currentIndex: 2,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        title: Text(l.libraryTitle, style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: AppColors.textPrimary),
            tooltip: l.libraryRefresh,
            onPressed: () => notifier.refresh(),
          ),
        ],
      ),
      body: libraryAsync.when(
        data: (state) {
          final hasFilter = state.style != null || state.targetAge != null;
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
                _OfflineBanner(
                  onClose: notifier.clearOfflineBanner,
                ),
              Expanded(
                child: hasBooks
                    ? _buildBookContent(
                        state, notifier.refresh, ageLabels, styleLabels)
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
                            : () => Navigator.pushNamed(context, '/create'),
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
          buttonText: l.libraryRetry,
          onButtonPressed: () => ref.invalidate(libraryBrowseProvider),
        ),
      ),
    );
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
      volumes
          .sort((a, b) => (a.seriesIndex ?? 0).compareTo(b.seriesIndex ?? 0));
    }

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: CustomScrollView(
        controller: _scrollController,
        slivers: [
          for (final volumes in groups.values)
            SliverToBoxAdapter(
              child: _SeriesShelf(
                volumes: volumes,
                onOpen: (book) => Navigator.pushNamed(
                  context,
                  '/viewer',
                  arguments: book.id,
                ),
                onAddVolume: () => _createNextVolume(volumes.last),
              ),
            ),
          if (standalone.isNotEmpty)
            SliverPadding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              sliver: SliverGrid(
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2,
                  mainAxisSpacing: AppSpacing.md,
                  crossAxisSpacing: AppSpacing.md,
                  childAspectRatio: 0.62,
                ),
                delegate: SliverChildBuilderDelegate(
                  (context, index) {
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
                  },
                  childCount: standalone.length,
                ),
              ),
            ),
          if (state.hasMore)
            const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(AppSpacing.lg),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
          const SliverToBoxAdapter(
            child: SizedBox(height: AppSpacing.lg),
          ),
        ],
      ),
    );
  }

  /// 시리즈 다음 권 생성 — 같은 캐릭터/시리즈로 새 주제를 받아 생성 후 로딩으로 이동.
  Future<void> _createNextVolume(LibraryBook latest) async {
    final l = AppLocalizations.of(context);
    final characterId = latest.characterId;
    if (characterId == null || characterId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l.libraryErrorGeneric)),
      );
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
      final response = await ref.read(apiClientProvider).createSeriesBook(
            characterId: characterId,
            topic: topic,
            seriesId: latest.seriesId,
            previousBookId: latest.id,
          );
      if (!mounted) {
        return;
      }
      Navigator.pushNamed(context, '/loading', arguments: response.jobId);
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendlyErrorMessage(error))),
      );
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
      decoration: const BoxDecoration(
        border: Border(
          bottom: BorderSide(color: AppColors.divider),
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
      decoration: InputDecoration(
        labelText: label,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 18,
        ),
      ),
      items: [
        if (nullLabel != null)
          DropdownMenuItem<String>(
            value: _allValue,
            child: Text(nullLabel!),
          ),
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
      color: Colors.amber.shade100,
      child: Row(
        children: [
          const Icon(Icons.wifi_off_rounded, size: 18),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              l.libraryOfflineBanner,
              style: AppTextStyles.caption,
            ),
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
            color: AppColors.blackOverlay,
            shape: const CircleBorder(),
            child: PopupMenuButton<_BookCardMenuAction>(
              tooltip: l.libraryBookOptions,
              icon: const Icon(Icons.more_horiz, color: Colors.white, size: 20),
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
                  value: _BookCardMenuAction.delete,
                  child: Row(
                    children: [
                      const Icon(Icons.delete_outline,
                          size: 20, color: Colors.red),
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

enum _BookCardMenuAction {
  rename,
  share,
  delete,
}

class _MiniChip extends StatelessWidget {
  final String label;
  final bool highlighted;

  const _MiniChip({required this.label, this.highlighted = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: highlighted ? AppColors.primaryMedium : AppColors.surface,
        border: Border.all(
          color: highlighted ? AppColors.primary : AppColors.divider,
        ),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption.copyWith(
          color: highlighted ? AppColors.primary : null,
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
              AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.sm),
          child: Row(
            children: [
              const Icon(Icons.collections_bookmark_outlined,
                  size: 18, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Text(
                '${l.librarySeriesBadge} · ${volumes.length}',
                style: AppTextStyles.heading3,
              ),
            ],
          ),
        ),
        SizedBox(
          height: 210,
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
            color: AppColors.primaryLight,
            borderRadius: BorderRadius.circular(AppRadius.md),
            border: Border.all(color: AppColors.primaryMedium),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.add_circle_outline,
                  color: AppColors.primary, size: 32),
              const SizedBox(height: AppSpacing.sm),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Text(
                  l.librarySeriesAddVolume,
                  textAlign: TextAlign.center,
                  style:
                      AppTextStyles.caption.copyWith(color: AppColors.primary),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
