import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/screens/library_screen.dart';
import 'package:ai_story_book/screens/loading_screen.dart';
import 'package:ai_story_book/screens/credits_screen.dart';
import 'package:ai_story_book/screens/characters_screen.dart';
import 'package:ai_story_book/widgets/common_widgets.dart';

// ==================== Helpers ====================

/// Wrap a widget in MaterialApp + ProviderScope with optional provider overrides
Widget buildTestableWidget(
  Widget child, {
  List<Override> overrides = const [],
}) {
  return ProviderScope(
    overrides: overrides,
    child: MaterialApp(
      home: child,
      onGenerateRoute: (settings) {
        // Catch-all route handler to prevent navigation errors in tests
        return MaterialPageRoute(
          builder: (_) => Scaffold(body: Text('Route: ${settings.name}')),
        );
      },
    ),
  );
}

// Sample test data
final _sampleCharacters = [
  Character.fromJson({
    'id': 'char-1',
    'name': '토리',
    'master_description': '용감한 토끼',
    'appearance': {
      'age_visual': '5세',
      'face': '둥근 얼굴',
      'hair': '없음',
      'skin': '하얀 털',
      'body': '통통함',
    },
    'clothing': {
      'top': '파란 조끼',
      'bottom': '없음',
      'shoes': '없음',
      'accessories': '없음',
    },
    'personality_traits': ['용감함', '호기심'],
    'visual_style_notes': '수채화',
    'created_at': '2024-01-01T00:00:00Z',
  }),
  Character.fromJson({
    'id': 'char-2',
    'name': '하나',
    'master_description': '친절한 소녀',
    'appearance': {
      'age_visual': '7세',
      'face': '밝은 미소',
      'hair': '긴 머리',
      'skin': '밝은 피부',
      'body': '날씬함',
    },
    'clothing': {
      'top': '원피스',
      'bottom': '없음',
      'shoes': '구두',
      'accessories': '리본',
    },
    'personality_traits': ['친절함', '다정함', '씩씩함'],
    'visual_style_notes': '카툰',
    'created_at': '2024-01-02T00:00:00Z',
  }),
];

final _sampleBooks = [
  LibraryBook.fromJson({
    'id': 'book-1',
    'title': '토끼의 모험',
    'cover_image_url': 'https://example.com/cover1.jpg',
    'target_age': '5-7',
    'style': 'watercolor',
    'created_at': '2024-01-01T00:00:00Z',
  }),
  LibraryBook.fromJson({
    'id': 'book-2',
    'title': '하나의 여행',
    'cover_image_url': 'https://example.com/cover2.jpg',
    'target_age': '3-5',
    'style': 'cartoon',
    'created_at': '2024-01-02T00:00:00Z',
  }),
];

// ==================== Tests ====================

void main() {
  // ==================== CreateScreen Tests ====================

  group('CreateScreen', () {
    List<Override> createOverrides([List<Character>? chars]) => [
          charactersProvider
              .overrideWith(() => _MockCharactersNotifier(chars ?? _sampleCharacters)),
        ];

    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('새 동화책 만들기'), findsOneWidget);
    });

    testWidgets('renders topic input field', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('어떤 이야기를 만들까요?'), findsOneWidget);
      expect(find.byType(TextFormField), findsOneWidget);
    });

    testWidgets('renders age selection chips', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('아이 연령대'), findsOneWidget);
      for (final age in TargetAge.values) {
        expect(find.text(age.label), findsOneWidget);
      }
    });

    testWidgets('renders style selection chips', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('그림 스타일'), findsOneWidget);
      for (final style in BookStyle.values) {
        expect(find.text(style.label), findsOneWidget);
      }
    });

    testWidgets('renders theme section (offstage accessible)', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      // Theme section may be below the fold; use skipOffstage: false
      expect(find.text('테마 (선택)', skipOffstage: false), findsOneWidget);
      expect(find.text('없음', skipOffstage: false), findsOneWidget);
    });

    testWidgets('renders character section with characters', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      // Character section may be below the fold
      expect(find.text('주인공 캐릭터', skipOffstage: false), findsOneWidget);
      expect(find.text('AI가 새 캐릭터 생성', skipOffstage: false), findsOneWidget);
      expect(find.text('토리', skipOffstage: false), findsOneWidget);
      expect(find.text('하나', skipOffstage: false), findsOneWidget);
    });

    testWidgets('renders character section with empty list', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('주인공 캐릭터', skipOffstage: false), findsOneWidget);
      expect(find.text('AI가 새 캐릭터 생성', skipOffstage: false), findsOneWidget);
      expect(
        find.text('캐릭터를 추가하면 같은 캐릭터로 시리즈를 만들 수 있어요!', skipOffstage: false),
        findsOneWidget,
      );
    });

    testWidgets('renders submit button', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('동화책 만들기'), findsOneWidget);
    });

    testWidgets('validates empty topic on submit', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      // Tap submit without entering topic
      await tester.tap(find.text('동화책 만들기'));
      await tester.pumpAndSettle();

      expect(find.text('이야기 주제를 입력해주세요'), findsOneWidget);
    });

    testWidgets('validates short topic on submit', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextFormField), '토끼');
      await tester.tap(find.text('동화책 만들기'));
      await tester.pumpAndSettle();

      expect(find.text('조금 더 자세히 입력해주세요'), findsOneWidget);
    });

    testWidgets('shows loading indicator for characters', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: [
          charactersProvider
              .overrideWith(() => _MockLoadingCharactersNotifier()),
        ],
      ));
      // Only pump once - loading state won't settle
      await tester.pump();

      // CircularProgressIndicator may be below the fold
      expect(
        find.byType(CircularProgressIndicator, skipOffstage: false),
        findsOneWidget,
      );
    });
  });

  // ==================== LibraryScreen Tests ====================

  group('LibraryScreen', () {
    List<Override> libraryOverrides([List<LibraryBook>? books]) => [
          libraryProvider
              .overrideWith(() => _MockLibraryNotifier(books ?? _sampleBooks)),
        ];

    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(),
      ));
      // Use pump + short delay instead of pumpAndSettle to avoid RefreshIndicator issues
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('내 서재'), findsOneWidget);
    });

    testWidgets('renders refresh button', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byIcon(Icons.refresh), findsOneWidget);
    });

    testWidgets('renders book grid when data available', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byType(GridView), findsOneWidget);
      expect(find.text('토끼의 모험'), findsOneWidget);
      expect(find.text('하나의 여행'), findsOneWidget);
    });

    testWidgets('shows empty state when no books', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides([]),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('아직 만든 책이 없어요'), findsOneWidget);
      expect(find.text('첫 번째 동화책을 만들어보세요!'), findsOneWidget);
      expect(find.text('새 책 만들기'), findsOneWidget);
    });

    testWidgets('shows loading indicator', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: [
          libraryProvider.overrideWith(() => _MockLoadingLibraryNotifier()),
        ],
      ));
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows error state', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: [
          libraryProvider.overrideWith(() => _MockErrorLibraryNotifier()),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('책을 불러올 수 없어요'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
    });

    testWidgets('renders bottom navigation bar', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('홈'), findsOneWidget);
      expect(find.text('만들기'), findsOneWidget);
      expect(find.text('서재'), findsOneWidget);
      expect(find.text('캐릭터'), findsOneWidget);
    });
  });

  // ==================== LoadingScreen Tests ====================

  group('LoadingScreen', () {
    testWidgets('shows progress content with queued status', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-1'),
        overrides: [
          jobPollingProvider('test-job-1').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-1',
              status: JobState.queued,
              progress: 0,
              currentStep: '대기 중...',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('동화책을 만들고 있어요'), findsOneWidget);
    });

    testWidgets('shows progress indicator during generation', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-2'),
        overrides: [
          jobPollingProvider('test-job-2').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-2',
              status: JobState.running,
              progress: 50,
              currentStep: 'generate_story',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byType(ProgressIndicatorBar), findsOneWidget);
      expect(find.text('50%'), findsOneWidget);
    });

    testWidgets('shows step description for each step', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-3'),
        overrides: [
          jobPollingProvider('test-job-3').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-3',
              status: JobState.running,
              progress: 30,
              currentStep: 'generate_story',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('이야기를 만들고 있어요'), findsOneWidget);
    });

    testWidgets('shows error content on failure', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-err'),
        overrides: [
          jobPollingProvider('test-job-err').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-err',
              status: JobState.failed,
              progress: 30,
              errorMessage: 'LLM 타임아웃',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('문제가 발생했어요'), findsOneWidget);
      expect(find.text('LLM 타임아웃'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
      expect(find.text('홈으로 돌아가기'), findsOneWidget);
    });

    testWidgets('shows error icon on failure', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-err2'),
        overrides: [
          jobPollingProvider('test-job-err2').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-err2',
              status: JobState.failed,
              progress: 0,
              errorMessage: '알 수 없는 오류',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });

    testWidgets('shows tip during progress', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LoadingScreen(jobId: 'test-job-tip'),
        overrides: [
          jobPollingProvider('test-job-tip').overrideWith(
            (ref) => Stream.value(JobStatus(
              jobId: 'test-job-tip',
              status: JobState.running,
              progress: 20,
              currentStep: 'normalize',
            )),
          ),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byIcon(Icons.lightbulb_outline), findsOneWidget);
    });
  });

  // ==================== CharactersScreen Tests ====================

  group('CharactersScreen', () {
    List<Override> charOverrides([List<Character>? chars]) => [
          charactersProvider
              .overrideWith(() => _MockCharactersNotifier(chars ?? _sampleCharacters)),
        ];

    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('내 캐릭터'), findsOneWidget);
    });

    testWidgets('renders character list when data available', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('토리'), findsOneWidget);
      expect(find.text('하나'), findsOneWidget);
    });

    testWidgets('shows character descriptions', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('용감한 토끼'), findsOneWidget);
      expect(find.text('친절한 소녀'), findsOneWidget);
    });

    testWidgets('shows personality traits as chips', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('용감함'), findsOneWidget);
      expect(find.text('호기심'), findsOneWidget);
      expect(find.text('친절함'), findsOneWidget);
    });

    testWidgets('shows empty state when no characters', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('아직 캐릭터가 없어요'), findsOneWidget);
      expect(find.text('사진으로 캐릭터를 만들어보세요!'), findsOneWidget);
      expect(find.text('사진으로 캐릭터 만들기'), findsOneWidget);
    });

    testWidgets('shows loading indicator', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: [
          charactersProvider
              .overrideWith(() => _MockLoadingCharactersNotifier()),
        ],
      ));
      // Only pump once (loading state never settles)
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsAtLeastNWidgets(1));
    });

    testWidgets('shows error state', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: [
          charactersProvider
              .overrideWith(() => _MockErrorCharactersNotifier()),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('캐릭터를 불러올 수 없어요'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
    });

    testWidgets('renders add character card in list', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('새 캐릭터 추가'), findsOneWidget);
      expect(find.text('사진으로 나만의 캐릭터를 만들어보세요'), findsOneWidget);
    });

    testWidgets('renders FAB button', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.byType(FloatingActionButton), findsOneWidget);
      expect(find.text('사진으로 만들기'), findsOneWidget);
    });

    testWidgets('renders bottom navigation bar', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('홈'), findsOneWidget);
      expect(find.text('만들기'), findsOneWidget);
      expect(find.text('서재'), findsOneWidget);
      expect(find.text('캐릭터'), findsOneWidget);
    });
  });

  // ==================== CreditsScreen Tests ====================

  group('CreditsScreen', () {
    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(_MockApiClient()),
        ],
      ));
      // Pump once to build, then let the async initState start
      await tester.pump();

      expect(find.text('크레딧'), findsOneWidget);

      // Pump to let the _MockApiClient futures complete (100ms delay)
      await tester.pump(const Duration(milliseconds: 200));
    });

    testWidgets('shows loading indicator initially', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(_MockApiClient()),
        ],
      ));
      // First pump: widget builds with _isLoading = true
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      // Let the mock futures complete so timers are cleaned up
      await tester.pump(const Duration(milliseconds: 200));
    });

    testWidgets('subscription start button tap does not throw', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(_MockApiClient()),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      final startButton = find.text('구독 시작하기');
      expect(startButton, findsOneWidget);

      await tester.tap(startButton);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });

    testWidgets('credit purchase button shows subscription guidance dialog',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(_MockApiClient()),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      final purchaseButton = find.text('크레딧 구매');
      expect(purchaseButton, findsOneWidget);

      await tester.tap(purchaseButton);
      await tester.pumpAndSettle();

      expect(find.text('크레딧 팩 구매 준비 중'), findsOneWidget);
      expect(find.text('구독 플랜 보기'), findsOneWidget);

      await tester.tap(find.text('구독 플랜 보기'));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });
  });
}

// ==================== Mock Notifiers ====================

class _MockCharactersNotifier extends CharactersNotifier {
  final List<Character> _characters;

  _MockCharactersNotifier(this._characters);

  @override
  Future<List<Character>> build() async => _characters;
}

class _MockLoadingCharactersNotifier extends CharactersNotifier {
  @override
  Future<List<Character>> build() {
    // Return a Completer that never completes to stay in loading state
    // without creating a Timer
    return _neverComplete<List<Character>>();
  }
}

class _MockErrorCharactersNotifier extends CharactersNotifier {
  @override
  Future<List<Character>> build() async {
    throw Exception('Network error');
  }
}

class _MockLibraryNotifier extends LibraryNotifier {
  final List<LibraryBook> _books;

  _MockLibraryNotifier(this._books);

  @override
  Future<List<LibraryBook>> build() async => _books;
}

class _MockLoadingLibraryNotifier extends LibraryNotifier {
  @override
  Future<List<LibraryBook>> build() {
    return _neverComplete<List<LibraryBook>>();
  }
}

class _MockErrorLibraryNotifier extends LibraryNotifier {
  @override
  Future<List<LibraryBook>> build() async {
    throw Exception('Network error');
  }
}

/// Minimal mock API client that avoids actual HTTP calls
class _MockApiClient extends ApiClient {
  _MockApiClient() : super(baseUrl: 'http://localhost', userKey: 'test-key');

  @override
  Future<Map<String, dynamic>> getCreditsStatus() async {
    await Future.delayed(const Duration(milliseconds: 50));
    return {
      'credits': {'credits': 10, 'total_purchased': 0, 'total_used': 5},
      'subscription': null,
      'available_plans': [],
    };
  }

  @override
  Future<List<dynamic>> getTransactions({int limit = 20, int offset = 0}) async {
    await Future.delayed(const Duration(milliseconds: 50));
    return [];
  }
}

/// Returns a Future that never completes, without using a Timer.
/// This avoids the "Timer is still pending" error in Flutter tests.
Future<T> _neverComplete<T>() {
  final completer = Completer<T>();
  return completer.future;
}
