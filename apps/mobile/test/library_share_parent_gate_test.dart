import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/library_book.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/library_screen.dart';
import 'package:ai_story_book/services/book_media_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Books extends LibraryBrowseNotifier {
  @override
  Future<LibraryBrowseState> build() async =>
      LibraryBrowseState.initial().copyWith(
        books: [
          LibraryBook(
            id: 'synthetic',
            title: 'Synthetic story',
            coverImageUrl: '',
            targetAge: '5-7',
            style: 'watercolor',
            createdAt: DateTime(2026),
          ),
        ],
        total: 1,
      );
}

class _PendingBooks extends _Books {
  @override
  Future<bool> deleteBook(String bookId) async => true;
}

class _UnconfirmedBooks extends _Books {
  @override
  Future<bool> deleteBook(String bookId) async => throw const BookDeletionUnconfirmed();
}

void main() {
  testWidgets('library reports an unconfirmed deletion separately', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          libraryBrowseProvider.overrideWith(_UnconfirmedBooks.new),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: LibraryScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final l = AppLocalizations.of(tester.element(find.byType(LibraryScreen)));
    await tester.tap(find.byTooltip(l.libraryBookOptions));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.libraryMenuDelete));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.libraryDelete).last);
    await tester.pumpAndSettle();
    expect(find.text(l.libraryDeletionUnconfirmed), findsOneWidget);
    expect(find.text(l.libraryDeleteSuccess), findsNothing);
  });

  testWidgets('library explains when stored book files are still being deleted',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          libraryBrowseProvider.overrideWith(_PendingBooks.new),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: LibraryScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final l = AppLocalizations.of(tester.element(find.byType(LibraryScreen)));
    await tester.tap(find.byTooltip(l.libraryBookOptions));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.libraryMenuDelete));
    await tester.pumpAndSettle();
    await tester.tap(find.text(l.libraryDelete).last);
    await tester.pumpAndSettle();
    expect(find.text(l.libraryDeletionPending), findsOneWidget);
    expect(find.text(l.libraryDeleteSuccess), findsNothing);
  });

  testWidgets(
    'library export requires parent approval and cancellation stays in library',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            libraryBrowseProvider.overrideWith(_Books.new),
          ],
          child: const MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: LibraryScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final l = AppLocalizations.of(tester.element(find.byType(LibraryScreen)));
      await tester.tap(find.byTooltip(l.libraryBookOptions));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.libraryMenuShare));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      Navigator.of(tester.element(find.byType(AlertDialog))).pop(false);
      await tester.pumpAndSettle();
      expect(find.byType(LibraryScreen), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
