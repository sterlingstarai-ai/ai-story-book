import 'package:ai_story_book/main.dart';
import 'package:ai_story_book/screens/screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('buildAppRoute', () {
    testWidgets('builds LoadingScreen for valid /loading arguments',
        (tester) async {
      final route = buildAppRoute(
          const RouteSettings(name: '/loading', arguments: 'job-1'));
      final materialRoute = route as MaterialPageRoute<dynamic>;
      late Widget builtWidget;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              builtWidget = materialRoute.builder(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      expect(builtWidget, isA<LoadingScreen>());
      expect((builtWidget as LoadingScreen).jobId, 'job-1');
    });

    testWidgets('falls back to HomeScreen for malformed /loading arguments',
        (tester) async {
      final route =
          buildAppRoute(const RouteSettings(name: '/loading', arguments: 123));
      final materialRoute = route as MaterialPageRoute<dynamic>;
      late Widget builtWidget;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              builtWidget = materialRoute.builder(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      expect(builtWidget, isA<HomeScreen>());
    });

    testWidgets('builds ViewerScreen for valid /viewer arguments',
        (tester) async {
      final route = buildAppRoute(
        const RouteSettings(name: '/viewer', arguments: 'book-1'),
      );
      final materialRoute = route as MaterialPageRoute<dynamic>;
      late Widget builtWidget;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              builtWidget = materialRoute.builder(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      expect(builtWidget, isA<ViewerScreen>());
      expect((builtWidget as ViewerScreen).bookId, 'book-1');
    });

    testWidgets('falls back to HomeScreen for unknown routes', (tester) async {
      final route = buildAppRoute(const RouteSettings(name: '/unknown'));
      final materialRoute = route as MaterialPageRoute<dynamic>;
      late Widget builtWidget;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              builtWidget = materialRoute.builder(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      expect(builtWidget, isA<HomeScreen>());
    });
  });
}
