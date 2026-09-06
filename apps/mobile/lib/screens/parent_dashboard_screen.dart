import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

class ParentDashboardScreen extends ConsumerStatefulWidget {
  const ParentDashboardScreen({super.key});

  @override
  ConsumerState<ParentDashboardScreen> createState() =>
      _ParentDashboardScreenState();
}

class _ParentDashboardScreenState extends ConsumerState<ParentDashboardScreen> {
  bool _isLoading = true;
  bool _isRefreshing = false;
  String? _errorMessage;
  int _requestVersion = 0;
  String _period = 'weekly';
  Map<String, dynamic> _report = const {};

  @override
  void initState() {
    super.initState();
    _loadReport();
  }

  Future<void> _loadReport({bool refreshing = false}) async {
    final requestVersion = ++_requestVersion;
    final requestedPeriod = _period;
    if (refreshing) {
      setState(() => _isRefreshing = true);
    } else {
      setState(() => _isLoading = true);
    }
    try {
      final api = ref.read(apiClientProvider);
      final response = await api.getReadingReport(period: requestedPeriod);
      if (!mounted || requestVersion != _requestVersion) {
        return;
      }
      setState(() {
        _report = response;
        _errorMessage = null;
      });
    } catch (_) {
      if (!mounted || requestVersion != _requestVersion) {
        return;
      }
      setState(() => _errorMessage =
          AppLocalizations.of(context).parentDashboardLoadError);
    } finally {
      if (mounted && requestVersion == _requestVersion) {
        setState(() {
          _isLoading = false;
          _isRefreshing = false;
        });
      }
    }
  }

  int _asInt(dynamic value, {int fallback = 0}) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value) ?? fallback;
    }
    return fallback;
  }

  double _asDouble(dynamic value, {double fallback = 0}) {
    if (value is double) {
      return value;
    }
    if (value is num) {
      return value.toDouble();
    }
    if (value is String) {
      return double.tryParse(value) ?? fallback;
    }
    return fallback;
  }

  List<Map<String, dynamic>> _dailyBreakdown() {
    final raw = _report['daily_breakdown'];
    if (raw is! List) {
      return const [];
    }
    return raw
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList(growable: false);
  }

  Map<String, dynamic> _streakMap() {
    final raw = _report['streak'];
    if (raw is Map) {
      return Map<String, dynamic>.from(raw);
    }
    return const {};
  }

  Map<String, dynamic> _learningMap() {
    final raw = _report['learning_progress'];
    if (raw is Map) {
      return Map<String, dynamic>.from(raw);
    }
    return const {};
  }

  String _periodLabel() {
    final l = AppLocalizations.of(context);
    return _period == 'monthly'
        ? l.parentDashboardReportMonthly
        : l.parentDashboardReportWeekly;
  }

  Future<void> _changePeriod(String next) async {
    if (_period == next) {
      return;
    }
    setState(() {
      _period = next;
      _report = const {};
    });
    await _loadReport();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final totalBooks = _asInt(_report['total_books_read']);
    final totalMinutes = _asInt(_report['total_reading_minutes']);
    final avgMinutes = _asDouble(_report['average_reading_minutes']);
    final preferredTheme =
        (_report['preferred_theme']?.toString() ?? '').trim();
    final streak = _streakMap();
    final learning = _learningMap();
    final daily = _dailyBreakdown();

    return Scaffold(
      appBar: AppBar(
        title: Text(l.parentDashboardTitle),
        actions: [
          IconButton(
            tooltip: l.parentDashboardRefreshTooltip,
            onPressed: _isRefreshing || _isLoading
                ? null
                : () => _loadReport(refreshing: true),
            icon: _isRefreshing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [
                SegmentedButton<String>(
                  style: SegmentedButton.styleFrom(
                      minimumSize: const Size(64, 64)),
                  segments: [
                    ButtonSegment<String>(
                      value: 'weekly',
                      label: Text(l.parentDashboardSegmentWeekly),
                    ),
                    ButtonSegment<String>(
                      value: 'monthly',
                      label: Text(l.parentDashboardSegmentMonthly),
                    ),
                  ],
                  selected: {_period},
                  onSelectionChanged: (selection) {
                    if (selection.isEmpty) {
                      return;
                    }
                    _changePeriod(selection.first);
                  },
                ),
                const SizedBox(height: AppSpacing.md),
                if (_errorMessage != null)
                  _ErrorBanner(
                      message: _errorMessage!,
                      onRetry: () =>
                          _loadReport(refreshing: _report.isNotEmpty)),
                if (_report.isNotEmpty) ...[
                  Text(_periodLabel(), style: AppTextStyles.heading3),
                  const SizedBox(height: AppSpacing.sm),
                  _SummaryGrid(
                    totalBooks: totalBooks,
                    totalMinutes: totalMinutes,
                    avgMinutes: avgMinutes,
                    preferredTheme: preferredTheme.isEmpty
                        ? l.parentDashboardThemeUnspecified
                        : preferredTheme,
                  ),
                  const SizedBox(height: AppSpacing.md),
                  _LearningCard(
                    currentStreak: _asInt(streak['current']),
                    longestStreak: _asInt(streak['longest']),
                    completionRate: _asDouble(learning['completion_rate']),
                    sessions: _asInt(learning['sessions']),
                    completedSessions: _asInt(learning['completed_sessions']),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  _DailyChart(daily: daily),
                ],
              ],
            ),
    );
  }
}

class _SummaryGrid extends StatelessWidget {
  const _SummaryGrid({
    required this.totalBooks,
    required this.totalMinutes,
    required this.avgMinutes,
    required this.preferredTheme,
  });

  final int totalBooks;
  final int totalMinutes;
  final double avgMinutes;
  final String preferredTheme;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final cards = [
      _MetricCard(
        title: l.parentDashboardMetricTotalBooksTitle,
        value: l.parentDashboardMetricTotalBooksValue(totalBooks),
        icon: Icons.menu_book_outlined,
      ),
      _MetricCard(
        title: l.parentDashboardMetricTotalMinutesTitle,
        value: l.parentDashboardMetricTotalMinutesValue(totalMinutes),
        icon: Icons.timer_outlined,
      ),
      _MetricCard(
        title: l.parentDashboardMetricAvgMinutesTitle,
        value: l.parentDashboardMetricAvgMinutesValue(
            avgMinutes.toStringAsFixed(1)),
        icon: Icons.schedule_outlined,
      ),
      _MetricCard(
        title: l.parentDashboardMetricPreferredThemeTitle,
        value: preferredTheme,
        icon: Icons.favorite_outline,
      ),
    ];
    return LayoutBuilder(builder: (context, constraints) {
      final columns = constraints.maxWidth < 360 ||
              MediaQuery.textScalerOf(context).scale(14) > 18
          ? 1
          : 2;
      final width =
          (constraints.maxWidth - AppSpacing.sm * (columns - 1)) / columns;
      return Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children:
            cards.map((card) => SizedBox(width: width, child: card)).toList(),
      );
    });
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.title,
    required this.value,
    required this.icon,
  });

  final String title;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: AppColors.primary),
          const SizedBox(height: AppSpacing.sm),
          Text(title, style: AppTextStyles.caption),
          const SizedBox(height: AppSpacing.xs),
          Text(
            value,
            style: AppTextStyles.heading3.copyWith(fontSize: 16),
          ),
        ],
      ),
    );
  }
}

class _LearningCard extends StatelessWidget {
  const _LearningCard({
    required this.currentStreak,
    required this.longestStreak,
    required this.completionRate,
    required this.sessions,
    required this.completedSessions,
  });

  final int currentStreak;
  final int longestStreak;
  final double completionRate;
  final int sessions;
  final int completedSessions;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.parentDashboardLearningTitle, style: AppTextStyles.heading3),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l.parentDashboardLearningStreakLine(currentStreak, longestStreak),
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            l.parentDashboardLearningSessionLine(completedSessions, sessions),
            style: AppTextStyles.bodySmall,
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            l.parentDashboardLearningCompletionLine(
                completionRate.toStringAsFixed(1)),
            style: AppTextStyles.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _DailyChart extends StatelessWidget {
  const _DailyChart({required this.daily});

  final List<Map<String, dynamic>> daily;

  int _asInt(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value) ?? 0;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final maxMinutes = daily.fold<int>(
      1,
      (maxValue, item) => _asInt(item['minutes']) > maxValue
          ? _asInt(item['minutes'])
          : maxValue,
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppPalette.of(context).surface,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppPalette.of(context).divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l.parentDashboardDailyChartTitle, style: AppTextStyles.heading3),
          const SizedBox(height: AppSpacing.md),
          if (daily.isEmpty ||
              daily.every((day) => _asInt(day['minutes']) == 0))
            Text(l.parentDashboardEmptyReading, style: AppTextStyles.bodySmall),
          if (daily.isNotEmpty)
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: daily.map((item) {
                  final minutes = _asInt(item['minutes']);
                  final dateText = item['date']?.toString() ?? '';
                  final short = dateText.length >= 5
                      ? dateText.substring(dateText.length - 5)
                      : dateText;
                  final heightFactor = (minutes / maxMinutes).clamp(0.0, 1.0);
                  final barHeight = 16 + (72 * heightFactor);

                  return SizedBox(
                    width: 52,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 2),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '$minutes',
                            style: AppTextStyles.caption,
                          ),
                          const SizedBox(height: AppSpacing.xs),
                          Container(
                            height: barHeight.toDouble(),
                            decoration: BoxDecoration(
                              color: minutes > 0
                                  ? AppColors.primary
                                  : AppColors.blackOverlayLight,
                              borderRadius: BorderRadius.circular(6),
                            ),
                          ),
                          const SizedBox(height: AppSpacing.xs),
                          Text(
                            short,
                            style: AppTextStyles.caption,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                  );
                }).toList(),
              ),
            ),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});

  final VoidCallback onRetry;

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.error.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(message,
            style: AppTextStyles.bodySmall.copyWith(color: AppColors.error)),
        const SizedBox(height: AppSpacing.sm),
        OutlinedButton(
            onPressed: onRetry,
            style: OutlinedButton.styleFrom(minimumSize: const Size(64, 64)),
            child: Text(AppLocalizations.of(context).retry)),
      ]),
    );
  }
}
