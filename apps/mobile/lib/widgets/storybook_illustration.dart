import 'package:flutter/material.dart';

import '../utils/constants.dart';

class StorybookIllustration extends StatelessWidget {
  const StorybookIllustration({super.key, this.width = 180});

  final double width;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: CustomPaint(
        size: Size(width, width * .8),
        painter: _StorybookPainter(AppPalette.of(context)),
      ),
    );
  }
}

class _StorybookPainter extends CustomPainter {
  _StorybookPainter(this.palette);

  final AppPalette palette;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 180, size.height / 144);
    final ink = Paint();
    canvas.drawCircle(
      const Offset(90, 70),
      60,
      ink..color = palette.primaryLight,
    );
    canvas.drawOval(
      const Rect.fromLTWH(37, 117, 106, 13),
      ink..color = palette.primary.withValues(alpha: .14),
    );

    final cover = Path()
      ..moveTo(25, 67)
      ..quadraticBezierTo(63, 59, 90, 80)
      ..quadraticBezierTo(117, 59, 155, 67)
      ..lineTo(155, 117)
      ..quadraticBezierTo(118, 108, 90, 126)
      ..quadraticBezierTo(62, 108, 25, 117)
      ..close();
    canvas.drawPath(cover, ink..color = palette.primary);

    final pages = Path()
      ..moveTo(32, 60)
      ..quadraticBezierTo(67, 56, 90, 75)
      ..quadraticBezierTo(113, 56, 148, 60)
      ..lineTo(148, 108)
      ..quadraticBezierTo(112, 104, 90, 120)
      ..quadraticBezierTo(68, 104, 32, 108)
      ..close();
    canvas.drawPath(pages, ink..color = palette.surface);

    final rules = Paint()
      ..color = palette.primary.withValues(alpha: .38)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(const Offset(90, 76), const Offset(90, 117), rules);
    for (final y in [75.0, 84.0, 93.0]) {
      canvas.drawPath(
        Path()
          ..moveTo(43, y)
          ..quadraticBezierTo(62, y - 1, 78, y + 7)
          ..moveTo(102, y + 7)
          ..quadraticBezierTo(118, y - 1, 137, y),
        rules,
      );
    }
    for (final (x, y, r) in [
      (87.0, 34.0, 12.0),
      (119.0, 44.0, 6.0),
      (62.0, 47.0, 5.0),
    ]) {
      canvas.drawPath(
        Path()
          ..moveTo(x, y - r)
          ..quadraticBezierTo(x + 1, y - 1, x + r, y)
          ..quadraticBezierTo(x + 1, y + 1, x, y + r)
          ..quadraticBezierTo(x - 1, y + 1, x - r, y)
          ..quadraticBezierTo(x - 1, y - 1, x, y - r)
          ..close(),
        ink..color = palette.primary,
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_StorybookPainter oldDelegate) =>
      palette.isDark != oldDelegate.palette.isDark;
}
