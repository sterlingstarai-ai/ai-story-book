import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';
import '../widgets/scoped_book_image.dart';

class BranchStoryScreen extends ConsumerStatefulWidget {
  const BranchStoryScreen({super.key, required this.bookId});

  final String bookId;

  @override
  ConsumerState<BranchStoryScreen> createState() => _BranchStoryScreenState();
}

class _BranchStoryScreenState extends ConsumerState<BranchStoryScreen> {
  late final Object _branchSessionApi;
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

  @override
  void initState() {
    super.initState();
    _branchSessionApi = ref.read(apiClientProvider);
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
      final l = AppLocalizations.of(context);
      setState(() {
        _errorMessage = l.branchStoryLoadError;
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
    if (!mounted || !identical(ref.read(apiClientProvider), _branchSessionApi)) return;
    final initialNode = _currentNode;
    String? savedNodeKey;
    try {
      final progress = await ref.read(readingProgressProvider(widget.bookId).future);
      savedNodeKey = await progress.branch();
    } catch (_) {
      return;
    }
    final restoredNode = _findNodeByKey(savedNodeKey);
    if (restoredNode == null || !mounted ||
        !identical(_currentNode, initialNode) || _history.isNotEmpty) {
      return;
    }
    final l = AppLocalizations.of(context);
    final restoredKey = restoredNode['node_key']?.toString();
    setState(() {
      _currentNode = restoredNode;
      _currentOptions = _optionsFor(restoredKey);
      _statusLabel = l.branchStoryResumeStatus;
    });
  }

  Future<void> _saveProgressNode(String? nodeKey) async {
    if (!mounted || !identical(ref.read(apiClientProvider), _branchSessionApi)) return;
    try {
      final progress = await ref.read(readingProgressProvider(widget.bookId).future);
      if (nodeKey == null || nodeKey.isEmpty) {
        await progress.clearBranch();
      } else {
        await progress.saveBranch(nodeKey);
      }
    } catch (_) {
      // Progress is optional and must not stop reading.
    }
  }

  List<Map<String, dynamic>> _optionsFor(String? nodeKey) {
    if (nodeKey == null || nodeKey.isEmpty) {
      return const [];
    }
    return _edges
        .where((edge) => edge['from_node_key']?.toString() == nodeKey)
        .map(
          (edge) => {
            'option_text': edge['option_text']?.toString() ?? '',
            'to_node_key': edge['to_node_key']?.toString() ?? '',
          },
        )
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

      final l = AppLocalizations.of(context);

      if (nextNode is! Map) {
        setState(() {
          _currentOptions = const [];
          _statusLabel = status == 'end'
              ? l.branchStoryEndingReached
              : l.branchStoryChoiceApplied;
        });
        return;
      }

      final mappedNode = Map<String, dynamic>.from(nextNode);
      final nextOptions = _asMapList(result['next_options']);
      setState(() {
        _currentNode = mappedNode;
        _currentOptions = nextOptions;
        _statusLabel = nextOptions.isEmpty
            ? l.branchStoryEndingArrived(selectedOption ?? '').trim()
            : l.branchStorySelected(selectedOption ?? '').trim();
      });
      await _saveProgressNode(mappedNode['node_key']?.toString());
    } catch (_) {
      if (!mounted) {
        return;
      }
      final l = AppLocalizations.of(context);
      setState(() {
        if (_history.isNotEmpty) {
          _history.removeLast();
        }
        _statusLabel = l.branchStoryChoiceFailed;
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
    final l = AppLocalizations.of(context);
    setState(() => _isCreatingSample = true);
    try {
      final api = ref.read(apiClientProvider);
      final book = await api.getBook(widget.bookId);
      final first = book.pages.isNotEmpty
          ? book.pages[0].text
          : l.branchStorySampleText1;
      final second = book.pages.length > 1
          ? book.pages[1].text
          : l.branchStorySampleText2;
      final third = book.pages.length > 2
          ? book.pages[2].text
          : l.branchStorySampleText3;

      await api.initializeBranchStory(
        widget.bookId,
        // The empty view can become stale if another device creates a graph.
        // Never replace existing story data from this convenience action.
        overwrite: false,
        nodes: [
          {
            'node_key': 'start',
            'page_number': 1,
            'text': first,
            'options': [
              {
                'option_text': l.branchStorySampleOptionLeft,
                'to_node_key': 'left_end',
              },
              {
                'option_text': l.branchStorySampleOptionRight,
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
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.branchStorySampleCreated)));
    } catch (_) {
      if (!mounted) {
        return;
      }
      // The graph may have been created on another device since this screen
      // loaded. Refresh before offering another attempt.
      await _loadGraph(showLoading: false);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l.branchStorySampleCreateFailed)));
    } finally {
      if (mounted) {
        setState(() => _isCreatingSample = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final node = _currentNode;
    final imageUrl = node?['image_url']?.toString() ?? '';
    final pageNumber = node?['page_number']?.toString() ?? '-';
    final nodeText = node?['text']?.toString() ?? '';

    return Scaffold(
      appBar: AppBar(
        title: Text(l.branchStoryTitle),
        actions: [
          IconButton(
            onPressed: _isLoading || _isSubmitting || _isCreatingSample
                ? null
                : () => _loadGraph(showLoading: false),
            icon: const Icon(Icons.refresh),
            tooltip: l.branchStoryRefreshTooltip,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _errorMessage != null
          ? _ErrorPanel(message: _errorMessage!, onRetry: _loadGraph)
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
                    margin: const EdgeInsets.only(bottom: AppSpacing.md),
                    padding: const EdgeInsets.all(AppSpacing.sm),
                    decoration: BoxDecoration(
                      color: AppPalette.of(context).primaryLight,
                      borderRadius: BorderRadius.circular(AppRadius.md),
                    ),
                    child: Text(_statusLabel!, style: AppTextStyles.bodySmall),
                  ),
                Container(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: AppPalette.of(context).surface,
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    border: Border.all(color: AppPalette.of(context).divider),
                  ),
                  child: Text(
                    l.branchStoryPageLabel(pageNumber),
                    style: AppTextStyles.heading3,
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                if (imageUrl.isNotEmpty)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    child: AspectRatio(
                      aspectRatio: 4 / 3,
                      child: Semantics(
                        label: l.branchStoryImageSemantics,
                        image: true,
                        child: ScopedBookImage(
                          bookId: widget.bookId,
                          imageUrl: imageUrl,
                          fit: BoxFit.cover,
                          placeholder: const Center(
                            child: CircularProgressIndicator(),
                          ),
                          error: const Icon(Icons.broken_image),
                        ),
                      ),
                    ),
                  ),
                if (imageUrl.isNotEmpty) const SizedBox(height: AppSpacing.md),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: AppPalette.of(context).surface,
                    borderRadius: BorderRadius.circular(AppRadius.md),
                    border: Border.all(color: AppPalette.of(context).divider),
                  ),
                  child: Text(nodeText, style: AppTextStyles.body),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text(
                  l.branchStoryOptionsHeading,
                  style: AppTextStyles.heading3,
                ),
                const SizedBox(height: AppSpacing.sm),
                if (_currentOptions.isEmpty)
                  Text(l.branchStoryNoOptions, style: AppTextStyles.bodySmall)
                else
                  ..._currentOptions.map((option) {
                    final text = option['option_text']?.toString() ?? '';
                    return Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 64),
                          padding: const EdgeInsets.all(AppSpacing.md),
                        ),
                        onPressed: _isSubmitting
                            ? null
                            : () => _chooseOption(option),
                        child: Text(text, textAlign: TextAlign.center),
                      ),
                    );
                  }),
                const SizedBox(height: AppSpacing.md),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(64, 64),
                  ),
                  onPressed: _isSubmitting || _history.isEmpty
                      ? null
                      : _goBackStep,
                  icon: const Icon(Icons.undo),
                  label: Text(
                    l.branchStoryPreviousChoice,
                    textAlign: TextAlign.center,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(64, 64),
                  ),
                  onPressed: _isSubmitting ? null : _restartFromStart,
                  icon: const Icon(Icons.restart_alt),
                  label: Text(
                    l.branchStoryRestart,
                    textAlign: TextAlign.center,
                  ),
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
  const _ErrorPanel({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function({bool showLoading}) onRetry;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return EmptyState(
      icon: Icons.error_outline,
      title: message,
      buttonText: l.branchStoryRetry,
      onButtonPressed: () => onRetry(showLoading: true),
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
    final l = AppLocalizations.of(context);
    return EmptyState(
      icon: Icons.alt_route,
      title: l.branchStoryEmptyTitle,
      subtitle: l.branchStoryEmptySubtitle,
      buttonText: isCreatingSample
          ? l.branchStorySampleCreating
          : l.branchStoryCreateSample,
      onButtonPressed: isCreatingSample ? null : onCreateSample,
    );
  }
}
