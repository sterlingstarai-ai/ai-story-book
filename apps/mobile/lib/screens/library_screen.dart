import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../core/api_error.dart';
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

  static const Map<String, String> _sortLabels = {
    'newest': '최신순',
    'oldest': '오래된순',
    'title': '제목순',
  };

  static const Map<String, String> _styleLabels = {
    'watercolor': '수채화',
    'cartoon': '카툰',
    '3d': '3D',
    'pixel': '픽셀',
    'oil_painting': '유화',
    'claymation': '클레이',
    'realistic': '실사',
  };

  static const Map<String, String> _ageLabels = {
    '3-5': '3-5세',
    '5-7': '5-7세',
    '7-9': '7-9세',
    'adult': '성인',
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
    final controller = TextEditingController(text: book.title);
    try {
      final result = await showDialog<String>(
        context: context,
        builder: (context) {
          return AlertDialog(
            title: const Text('책 이름 바꾸기'),
            content: TextField(
              controller: controller,
              maxLength: 80,
              decoration: const InputDecoration(
                labelText: '제목',
                hintText: '책 제목을 입력해주세요',
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, controller.text.trim()),
                child: const Text('저장'),
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
        const SnackBar(content: Text('책 이름을 수정했어요.')),
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
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('책 삭제'),
            content: Text(
              '"${book.title}"을(를) 삭제할까요?\n삭제한 책은 복구할 수 없어요.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.red.shade600,
                ),
                child: const Text('삭제'),
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
        const SnackBar(content: Text('책을 삭제했어요.')),
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
    if (error is ApiError) {
      return error.userMessage;
    }
    final raw = error.toString().toLowerCase();
    if (raw.contains('socketexception') ||
        raw.contains('network') ||
        raw.contains('connection')) {
      return '인터넷 연결을 확인한 뒤 다시 시도해주세요.';
    }
    return '요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.';
  }

  String _sanitizeFileName(String title) {
    return title
        .replaceAll(RegExp(r'[\\\\/:*?\"<>|]'), '_')
        .replaceAll(' ', '_');
  }

  Future<void> _shareBook(LibraryBook book) async {
    final message = '''
📚 ${book.title}

AI Story Book으로 만든 동화책이에요.
아이에게 특별한 이야기를 들려주세요!
'''
        .trim();
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
        const SnackBar(
          content: Text('공유에 실패했어요. 잠시 후 다시 시도해주세요.'),
          backgroundColor: AppColors.error,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final libraryAsync = ref.watch(libraryBrowseProvider);
    final notifier = ref.read(libraryBrowseProvider.notifier);

    return AppShell(
      currentIndex: 2,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        title: const Text('내 서재', style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: AppColors.textPrimary),
            tooltip: '새로고침',
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
                sortLabels: _sortLabels,
                styleLabels: _styleLabels,
                ageLabels: _ageLabels,
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
                    ? RefreshIndicator(
                        onRefresh: notifier.refresh,
                        child: GridView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.all(AppSpacing.lg),
                          gridDelegate:
                              const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 2,
                            mainAxisSpacing: AppSpacing.md,
                            crossAxisSpacing: AppSpacing.md,
                            childAspectRatio: 0.62,
                          ),
                          itemCount:
                              state.books.length + (state.hasMore ? 1 : 0),
                          itemBuilder: (context, index) {
                            if (index >= state.books.length) {
                              return const Center(
                                child: CircularProgressIndicator(),
                              );
                            }

                            final book = state.books[index];
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
                              ageLabel:
                                  _ageLabels[book.targetAge] ?? book.targetAge,
                              styleLabel:
                                  _styleLabels[book.style] ?? book.style,
                              dateLabel: _formatDate(book.createdAt),
                            );
                          },
                        ),
                      )
                    : EmptyState(
                        icon: hasFilter
                            ? Icons.filter_alt_off_outlined
                            : Icons.auto_stories_outlined,
                        title: hasFilter ? '조건에 맞는 책이 없어요' : '아직 만든 책이 없어요',
                        subtitle: hasFilter
                            ? '필터를 해제하고 전체 서재를 확인해보세요.'
                            : '첫 번째 동화책을 만들어보세요!',
                        buttonText: hasFilter ? '필터 초기화' : '새 책 만들기',
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
          title: '서재를 불러올 수 없어요',
          subtitle: _friendlyErrorMessage(error),
          buttonText: '다시 시도',
          onButtonPressed: () => ref.invalidate(libraryBrowseProvider),
        ),
      ),
    );
  }

  String _formatDate(DateTime date) {
    final now = DateTime.now();
    final diff = now.difference(date);

    if (diff.inDays == 0) {
      return '오늘';
    }
    if (diff.inDays == 1) {
      return '어제';
    }
    if (diff.inDays < 7) {
      return '${diff.inDays}일 전';
    }
    return '${date.month}월 ${date.day}일';
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
                  label: '정렬',
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
                  label: '스타일',
                  value: style,
                  entries: styleLabels.entries.toList(),
                  nullLabel: '전체',
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
                  label: '연령',
                  value: targetAge,
                  entries: ageLabels.entries.toList(),
                  nullLabel: '전체',
                  onChanged: onAgeChanged,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              SizedBox(
                height: AppSizing.minTouchTarget,
                child: TextButton.icon(
                  onPressed: hasFilter ? onResetFilters : null,
                  icon: const Icon(Icons.filter_alt_off_outlined),
                  label: const Text('필터 초기화'),
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
          const Expanded(
            child: Text(
              '오프라인 상태예요. 최근 불러온 책을 보여주고 있어요.',
              style: AppTextStyles.caption,
            ),
          ),
          IconButton(
            onPressed: onClose,
            icon: const Icon(Icons.close, size: 18),
            tooltip: '닫기',
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
                children: [
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
              tooltip: '책 옵션',
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
              itemBuilder: (context) => const [
                PopupMenuItem(
                  value: _BookCardMenuAction.rename,
                  child: Row(
                    children: [
                      Icon(Icons.drive_file_rename_outline, size: 20),
                      SizedBox(width: AppSpacing.sm),
                      Text('이름 바꾸기'),
                    ],
                  ),
                ),
                PopupMenuItem(
                  value: _BookCardMenuAction.share,
                  child: Row(
                    children: [
                      Icon(Icons.share_outlined, size: 20),
                      SizedBox(width: AppSpacing.sm),
                      Text('공유하기'),
                    ],
                  ),
                ),
                PopupMenuItem(
                  value: _BookCardMenuAction.delete,
                  child: Row(
                    children: [
                      Icon(Icons.delete_outline, size: 20, color: Colors.red),
                      SizedBox(width: AppSpacing.sm),
                      Text('삭제'),
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

  const _MiniChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.divider),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption,
      ),
    );
  }
}
