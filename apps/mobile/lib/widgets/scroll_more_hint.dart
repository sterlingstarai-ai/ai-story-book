import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';

/// A hint for an adjacent scroll area, visible only while content remains below.
class ScrollMoreHint extends StatefulWidget {
  const ScrollMoreHint({super.key, required this.controller});
  final ScrollController controller;
  @override
  State<ScrollMoreHint> createState() => _ScrollMoreHintState();
}

class _ScrollMoreHintState extends State<ScrollMoreHint> {
  bool _more = false;
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_update);
  }

  @override
  void didUpdateWidget(ScrollMoreHint oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_update);
      widget.controller.addListener(_update);
    }
  }

  void _update() {
    if (!mounted || !widget.controller.hasClients) return;
    final more = widget.controller.position.extentAfter > 1;
    if (more != _more) setState(() => _more = more);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_update);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    WidgetsBinding.instance.addPostFrameCallback((_) => _update());
    // Reserve a line so showing the hint cannot itself create overflow.
    return Visibility(
      visible: _more,
      maintainSize: true,
      maintainAnimation: true,
      maintainState: true,
      child: Text(AppLocalizations.of(context).consentScrollHint,
          style: Theme.of(context).textTheme.bodySmall),
    );
  }
}
