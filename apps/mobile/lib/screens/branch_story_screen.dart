import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

class BranchStoryScreen extends ConsumerStatefulWidget {
  const BranchStoryScreen({
    super.key,
    required this.bookId,
  });

  final String bookId;

  @override
  ConsumerState<BranchStoryScreen> createState() => _BranchStoryScreenState();
}

class _BranchStoryScreenState extends ConsumerState<BranchStoryScreen> {
  bool _isLoading = true;
  bool _isSubmitting = false;
  bool _isCreatingSample = false;
  String? _errorMessage;
  String? _statusLabel;

  List<Map<String, dynamic>> _nodes = const [];
  List<Map<String, dynamic>> _edges = const [];
  Map<String, dynamic>? _currentNode;
  List<Map<String, dynamic>> _currentOptions = const [];
  final List<_BranchSnapshot> _history = [];

  String get _progressStorageKey =>
      'branch_story_progress_${widget.bookId}_v1';

  @override
  void initState() {
    super.initState();
    _loadGraph();
  }

  Future<void> _loadGraph({bool showLoading = true}) async {
    if (showLoading) {
      setState(() => _isLoading = true);
    }
    try {
      final api = ref.read(apiClientProvider);
      final data = await api.getBranchStoryGraph(widget.bookId);
      final nodes = _asMapList(data['nodes']);
      final edges = _asMapList(data['edges']);

      if (!mounted) {
        return;
      }

      setState(() {
        _nodes = nodes;
        _edges = edges;
        _errorMessage = null;
        _statusLabel = null;
        _history.clear();
        _setInitialNode();
        _isLoading = false;
      });
      await _restoreProgressFromStorage();
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '분기형 스토리 정보를 불러오지 못했어요.';
        _isLoading = false;
      });
    }
  }

  void _setInitialNode() {
    if (_nodes.isEmpty) {
      _currentNode = null;
      _currentOptions = const [];
      return;
    }
    Map<String, dynamic>? node;
    for (final item in _nodes) {
      if (item['node_key']?.toString() == 'start') {
        node = item;
        break;
      }
    }
    node ??= _nodes.first;
    final key = node['node_key']?.toString();
    _currentNode = node;
    _currentOptions = _optionsFor(key);
  }

  Map<String, dynamic>? _findNodeByKey(String? nodeKey) {
    if (nodeKey == null || nodeKey.isEmpty) {
      return null;
    }
    for (final node in _nodes) {
      if (node['node_key']?.toString() == nodeKey) {
        return node;
      }
    }
    return null;
  }

  Future<void> _restoreProgressFromStorage() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final savedNodeKey = prefs.getString(_progressStorageKey);
    final restoredNode = _findNodeByKey(savedNodeKey);
    if (restoredNode == null || !mounted) {
      return;
    }
    final restoredKey = restoredNode['node_key']?.toString();
    setState(() {
      _currentNode = restoredNode;
      _currentOptions = _optionsFor(restoredKey);
      _statusLabel = '이전 진행 지점에서 이어서 읽고 있어요.';
    });
  }

  Future<void> _saveProgressNode(String? nodeKey) async {
    final prefs = ref.read(sharedPreferencesProvider);
    if (nodeKey == null || nodeKey.isEmpty) {
      await prefs.remove(_progressStorageKey);
      return;
    }
    await prefs.setString(_progressStorageKey, nodeKey);
  }

  List<Map<String, dynamic>> _optionsFor(String? nodeKey) {
    if (nodeKey == null || nodeKey.isEmpty) {
      return const [];
    }
    return _edges
        .where((edge) => edge['from_node_key']?.toString() == nodeKey)
        .map((edge) => {
              'option_text': edge['option_text']?.toString() ?? '',
              'to_node_key': edge['to_node_key']?.toString() ?? '',
            })
        .where((edge) => (edge['option_text'] as String).isNotEmpty)
        .toList(growable: false);
  }

  List<Map<String, dynamic>> _asMapList(dynamic value) {
    if (value is! List) {
      return const [];
    }
    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList(growable: false);
  }

  Future<void> _chooseOption(Map<String, dynamic> option) async {
    final current = _currentNode;
    if (_isSubmitting || current == null) {
      return;
    }

    final currentNodeKey = current['node_key']?.toString();
    final optionText = option['option_text']?.toString();
    if (currentNodeKey == null || optionText == null || optionText.isEmpty) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _history.add(
        _BranchSnapshot(
          node: current,
          options: _currentOptions,
          statusLabel: _statusLabel,
        ),
      );
    });

    try {
      final api = ref.read(apiClientProvider);
      final result = await api.chooseBranchStoryOption(
        widget.bookId,
        currentNodeKey: currentNodeKey,
        optionText: optionText,
      );
      final nextNode = result['next_node'];
      final status = result['status']?.toString() ?? 'ok';
      final selectedOption = result['selected_option']?.toString();

      if (!mounted) {
        return;
      }

      if (nextNode is! Map) {
        setState(() {
          _currentOptions = const [];
          _statusLabel = status == 'end' ? '이 분기의 엔딩에 도착했어요.' : '선택을 적용했어요.';
        });
        return;
      }

      final mappedNode = Map<String, dynamic>.from(nextNode);
      final nextOptions = _asMapList(result['next_options']);
      setState(() {
        _currentNode = mappedNode;
        _currentOptions = nextOptions;
        _statusLabel = nextOptions.isEmpty
            ? '엔딩 도착: ${selectedOption ?? ''}'.trim()
            : '선택: ${selectedOption ?? ''}'.trim();
      });
      await _saveProgressNode(mappedNode['node_key']?.toString());
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        if (_history.isNotEmpty) {
          _history.removeLast();
        }
        _statusLabel = '선택 적용에 실패했어요. 다시 시도해주세요.';
      });
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  void _goBackStep() {
    if (_history.isEmpty) {
      return;
    }
    final last = _history.removeLast();
    setState(() {
      _currentNode = last.node;
      _currentOptions = last.options;
      _statusLabel = last.statusLabel;
    });
    unawaited(_saveProgressNode(_currentNode?['node_key']?.toString()));
  }

  void _restartFromStart() {
    setState(() {
      _history.clear();
      _statusLabel = null;
      _setInitialNode();
    });
    unawaited(_saveProgressNode(_currentNode?['node_key']?.toString()));
  }

  Future<void> _createSampleBranch() async {
    if (_isCreatingSample) {
      return;
    }
    setState(() => _isCreatingSample = true);
    try {
      final api = ref.read(apiClientProvider);
      final book = await api.getBook(widget.bookId);
      final first =
          book.pages.isNotEmpty ? book.pages[0].text : '토끼는 갈림길에 섰어요.';
      final second =
          book.pages.length > 1 ? book.pages[1].text : '왼쪽 길에서 새로운 친구를 만났어요.';
      final third =
          book.pages.length > 2 ? book.pages[2].text : '오른쪽 길에서 보물을 발견했어요.';

      await api.initializeBranchStory(
        widget.bookId,
        overwrite: true,
        nodes: [
          {
            'node_key': 'start',
            'page_number': 1,
            'text': first,
            'options': [
              {
                'option_text': '왼쪽 길로 간다',
                'to_node_key': 'left_end',
              },
              {
                'option_text': '오른쪽 길로 간다',
                'to_node_key': 'right_end',
              },
            ],
          },
          {
            'node_key': 'left_end',
            'page_number': 2,
            'text': second,
            'options': const [],
          },
          {
            'node_key': 'right_end',
            'page_number': 2,
            'text': third,
            'options': const [],
          },
        ],
      );

      await _loadGraph(showLoading: false);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('샘플 분기 스토리를 생성했어요.')),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('샘플 분기 생성에 실패했어요.')),
      );
    } finally {
      if (mounted) {
        setState(() => _isCreatingSample = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final node = _currentNode;
    final imageUrl = node?['image_url']?.toString() ?? '';
    final pageNumber = node?['page_number']?.toString() ?? '-';
    final nodeText = node?['text']?.toString() ?? '';
    final nodeKey = node?['node_key']?.toString() ?? '-';

    return Scaffold(
      appBar: AppBar(
        title: const Text('분기형 스토리'),
        actions: [
          IconButton(
            onPressed: _isLoading ? null : () => _loadGraph(showLoading: false),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _errorMessage != null
              ? _ErrorPanel(
                  message: _errorMessage!,
                  onRetry: _loadGraph,
                )
              : _nodes.isEmpty
                  ? _EmptyPanel(
                      isCreatingSample: _isCreatingSample,
                      onCreateSample: _createSampleBranch,
                    )
                  : ListView(
                      padding: const EdgeInsets.all(AppSpacing.md),
                      children: [
                        if (_statusLabel != null)
                          Container(
                            margin:
                                const EdgeInsets.only(bottom: AppSpacing.md),
                            padding: const EdgeInsets.all(AppSpacing.sm),
                            decoration: BoxDecoration(
                              color: AppColors.primaryLight,
                              borderRadius: BorderRadius.circular(AppRadius.md),
                            ),
                            child: Text(_statusLabel!,
                                style: AppTextStyles.bodySmall),
                          ),
                        Container(
                          padding: const EdgeInsets.all(AppSpacing.md),
                          decoration: BoxDecoration(
                            color: AppColors.surface,
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(color: AppColors.divider),
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '노드: $nodeKey',
                                  style: AppTextStyles.heading3,
                                ),
                              ),
                              Text(
                                '페이지 $pageNumber',
                                style: AppTextStyles.caption,
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        if (imageUrl.isNotEmpty)
                          ClipRRect(
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            child: AspectRatio(
                              aspectRatio: 4 / 3,
                              child: CachedNetworkImage(
                                imageUrl: imageUrl,
                                fit: BoxFit.cover,
                                placeholder: (_, __) => const Center(
                                  child: CircularProgressIndicator(),
                                ),
                                errorWidget: (_, __, ___) =>
                                    const Icon(Icons.broken_image),
                              ),
                            ),
                          ),
                        if (imageUrl.isNotEmpty)
                          const SizedBox(height: AppSpacing.md),
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(AppSpacing.md),
                          decoration: BoxDecoration(
                            color: AppColors.surface,
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(color: AppColors.divider),
                          ),
                          child: Text(
                            nodeText,
                            style: AppTextStyles.body,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.lg),
                        const Text('선택지', style: AppTextStyles.heading3),
                        const SizedBox(height: AppSpacing.sm),
                        if (_currentOptions.isEmpty)
                          const Text(
                            '더 이상 선택지가 없어요. 이 분기의 엔딩입니다.',
                            style: AppTextStyles.bodySmall,
                          )
                        else
                          ..._currentOptions.map((option) {
                            final text =
                                option['option_text']?.toString() ?? '';
                            return Padding(
                              padding:
                                  const EdgeInsets.only(bottom: AppSpacing.sm),
                              child: ElevatedButton(
                                onPressed: _isSubmitting
                                    ? null
                                    : () => _chooseOption(option),
                                child: Text(text),
                              ),
                            );
                          }),
                        const SizedBox(height: AppSpacing.md),
                        Row(
                          children: [
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed:
                                    _history.isEmpty ? null : _goBackStep,
                                icon: const Icon(Icons.undo),
                                label: const Text('이전 선택'),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: _restartFromStart,
                                icon: const Icon(Icons.restart_alt),
                                label: const Text('처음부터'),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
    );
  }
}

class _BranchSnapshot {
  const _BranchSnapshot({
    required this.node,
    required this.options,
    required this.statusLabel,
  });

  final Map<String, dynamic> node;
  final List<Map<String, dynamic>> options;
  final String? statusLabel;
}

class _ErrorPanel extends StatelessWidget {
  const _ErrorPanel({
    required this.message,
    required this.onRetry,
  });

  final String message;
  final Future<void> Function({bool showLoading}) onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 40, color: AppColors.error),
            const SizedBox(height: AppSpacing.sm),
            Text(message,
                style: AppTextStyles.bodySmall, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.md),
            FilledButton(
              onPressed: () => onRetry(showLoading: true),
              child: const Text('다시 시도'),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyPanel extends StatelessWidget {
  const _EmptyPanel({
    required this.isCreatingSample,
    required this.onCreateSample,
  });

  final bool isCreatingSample;
  final Future<void> Function() onCreateSample;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.alt_route, size: 40, color: AppColors.primary),
            const SizedBox(height: AppSpacing.sm),
            const Text(
              '아직 분기형 스토리가 없어요.',
              style: AppTextStyles.heading3,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.xs),
            const Text(
              '샘플 분기를 생성해서 인터랙티브 스토리를 바로 체험할 수 있어요.',
              style: AppTextStyles.bodySmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.md),
            FilledButton.icon(
              onPressed: isCreatingSample ? null : onCreateSample,
              icon: isCreatingSample
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.auto_awesome),
              label: Text(isCreatingSample ? '생성 중...' : '샘플 분기 생성'),
            ),
          ],
        ),
      ),
    );
  }
}
