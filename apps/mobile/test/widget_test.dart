import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/widgets/common_widgets.dart';
import 'package:ai_story_book/utils/constants.dart';

void main() {
  group('PrimaryButton', () {
    testWidgets('displays text correctly', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: PrimaryButton(text: 'Test Button'),
          ),
        ),
      );

      expect(find.text('Test Button'), findsOneWidget);
    });

    testWidgets('shows loading indicator when isLoading is true',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: PrimaryButton(
              text: 'Test Button',
              isLoading: true,
            ),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Test Button'), findsNothing);
    });

    testWidgets('calls onPressed when tapped', (WidgetTester tester) async {
      bool pressed = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PrimaryButton(
              text: 'Test Button',
              onPressed: () => pressed = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(ElevatedButton));
      expect(pressed, isTrue);
    });

    testWidgets('does not call onPressed when loading',
        (WidgetTester tester) async {
      bool pressed = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PrimaryButton(
              text: 'Test Button',
              isLoading: true,
              onPressed: () => pressed = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(ElevatedButton));
      expect(pressed, isFalse);
    });
  });

  group('SecondaryButton', () {
    testWidgets('displays text correctly', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SecondaryButton(text: 'Secondary'),
          ),
        ),
      );

      expect(find.text('Secondary'), findsOneWidget);
    });

    testWidgets('uses OutlinedButton style', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SecondaryButton(text: 'Secondary'),
          ),
        ),
      );

      expect(find.byType(OutlinedButton), findsOneWidget);
    });
  });

  group('EmptyState', () {
    testWidgets('displays icon and title', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EmptyState(
              icon: Icons.book,
              title: 'No books',
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.book), findsOneWidget);
      expect(find.text('No books'), findsOneWidget);
    });

    testWidgets('displays subtitle when provided', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: EmptyState(
              icon: Icons.book,
              title: 'No books',
              subtitle: 'Create your first book',
            ),
          ),
        ),
      );

      expect(find.text('Create your first book'), findsOneWidget);
    });

    testWidgets('displays button when provided', (WidgetTester tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: EmptyState(
              icon: Icons.book,
              title: 'No books',
              buttonText: 'Create Book',
              onButtonPressed: () {},
            ),
          ),
        ),
      );

      expect(find.text('Create Book'), findsOneWidget);
    });
  });

  group('ProgressIndicatorBar', () {
    testWidgets('displays progress percentage', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: ProgressIndicatorBar(progress: 50),
          ),
        ),
      );

      expect(find.text('50%'), findsOneWidget);
    });

    testWidgets('displays current step when provided',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: ProgressIndicatorBar(
              progress: 50,
              currentStep: 'Generating story',
            ),
          ),
        ),
      );

      expect(find.text('Generating story'), findsOneWidget);
    });

    testWidgets('shows LinearProgressIndicator', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: ProgressIndicatorBar(progress: 75),
          ),
        ),
      );

      expect(find.byType(LinearProgressIndicator), findsOneWidget);
    });
  });

  group('CharacterCard', () {
    testWidgets('displays name and description', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CharacterCard(
              name: 'Tori',
              description: 'A cute rabbit',
            ),
          ),
        ),
      );

      expect(find.text('Tori'), findsOneWidget);
      expect(find.text('A cute rabbit'), findsOneWidget);
    });

    testWidgets('shows check icon when selected', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CharacterCard(
              name: 'Tori',
              description: 'A cute rabbit',
              isSelected: true,
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.check_circle), findsOneWidget);
    });

    testWidgets('does not show check icon when not selected',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CharacterCard(
              name: 'Tori',
              description: 'A cute rabbit',
              isSelected: false,
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.check_circle), findsNothing);
    });

    testWidgets('calls onTap when tapped', (WidgetTester tester) async {
      bool tapped = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CharacterCard(
              name: 'Tori',
              description: 'A cute rabbit',
              onTap: () => tapped = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(CharacterCard));
      expect(tapped, isTrue);
    });
  });

  group('LoadingOverlay', () {
    testWidgets('shows CircularProgressIndicator',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: LoadingOverlay(),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows message when provided', (WidgetTester tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: LoadingOverlay(message: 'Loading...'),
          ),
        ),
      );

      expect(find.text('Loading...'), findsOneWidget);
    });
  });

  group('AppColors', () {
    test('primary color is defined', () {
      expect(AppColors.primary, isNotNull);
    });

    test('secondary color is defined', () {
      expect(AppColors.secondary, isNotNull);
    });

    test('background color is defined', () {
      expect(AppColors.background, isNotNull);
    });
  });

  group('AppTextStyles', () {
    test('heading1 is defined', () {
      expect(AppTextStyles.heading1, isNotNull);
      expect(AppTextStyles.heading1.fontSize, equals(28));
    });

    test('body is defined', () {
      expect(AppTextStyles.body, isNotNull);
      expect(AppTextStyles.body.fontSize, equals(16));
    });
  });

  group('AppSpacing', () {
    test('spacing values are defined', () {
      expect(AppSpacing.xs, equals(4.0));
      expect(AppSpacing.sm, equals(8.0));
      expect(AppSpacing.md, equals(16.0));
      expect(AppSpacing.lg, equals(24.0));
      expect(AppSpacing.xl, equals(32.0));
    });
  });
}
