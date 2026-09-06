import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

const designCaptureKey = Key('final-design-capture');
const _captureDir = String.fromEnvironment('DESIGN_CAPTURE_DIR');

/// Optional real-font render evidence; ordinary regression runs do not write files.
Future<void> loadDesignFonts() async {
  if (_captureDir.isEmpty) return;
  final font = FontLoader('Pretendard')
    ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
    ..addFont(rootBundle.load('assets/fonts/Pretendard-Medium.otf'))
    ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'));
  await font.load();
  await (FontLoader('MaterialIcons')
        ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf')))
      .load();
}

Widget designCaptureBoundary(Widget child) =>
    RepaintBoundary(key: designCaptureKey, child: child);

Future<void> captureDesign(WidgetTester tester, String name) async {
  if (_captureDir.isEmpty) return;
  await tester.pump();
  final render =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(designCaptureKey));
  await tester.runAsync(() async {
    final image = await render.toImage(pixelRatio: 1);
    try {
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      final dir = Directory(_captureDir);
      await dir.create(recursive: true);
      await File('${dir.path}/$name.png')
          .writeAsBytes(data!.buffer.asUint8List());
    } finally {
      image.dispose();
    }
  });
}
