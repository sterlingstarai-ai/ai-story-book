import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:ai_story_book/core/api_error.dart';
import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/screens/create_screen.dart';
import 'package:ai_story_book/screens/home_screen.dart';
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
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
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

const _sampleStreak = HomeStreakSnapshot(
  currentStreak: 3,
  longestStreak: 7,
  totalDays: 12,
  readToday: true,
  todayThemeName: '우정',
  todayTopic: '숲속 친구들과 협력하는 모험',
  todayBookId: 'book-1',
  readDates: {
    '2026-02-14',
    '2026-02-15',
    '2026-02-16',
    '2026-02-17',
    '2026-02-18',
    '2026-02-19',
    '2026-02-20',
  },
);

// ==================== Tests ====================

void main() {
  // ==================== CreateScreen Tests ====================

  group('CreateScreen', () {
    List<Override> createOverrides([List<Character>? chars]) => [
          charactersProvider.overrideWith(
              () => _MockCharactersNotifier(chars ?? _sampleCharacters)),
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

    testWidgets('shows live per-band age helper that updates on selection',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      // 기본 연령(5-7세) 안내가 표시된다.
      expect(find.text('익숙한 단어, 2~3문장, 감정과 간단한 대화'), findsOneWidget);

      // 다른 연령대(3-5세)를 선택하면 안내가 라이브로 갱신된다.
      await tester.tap(find.text('3-5세'));
      await tester.pumpAndSettle();
      expect(find.text('쉬운 단어, 1~2개의 짧은 문장, 반복과 의성어'), findsOneWidget);
      expect(find.text('익숙한 단어, 2~3문장, 감정과 간단한 대화'), findsNothing);
    });

    testWidgets('tapping a quick-start template prefills topic and theme',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      expect(find.text('추천으로 시작하기'), findsOneWidget);

      await tester.tap(find.text('동물 친구'));
      await tester.pumpAndSettle();
      expect(find.text('용감한 아기 동물이 숲에서 새 친구를 사귀는 이야기'),
          findsOneWidget);
    });

    testWidgets('shows relationship selector when 2+ characters selected',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(), // 샘플 캐릭터 2명(토리, 하나)
      ));
      await tester.pumpAndSettle();

      // 관계 섹션은 처음엔 없다(캐릭터 미선택 = AI 자동).
      expect(find.text('관계 (선택)'), findsNothing);

      final listView = find.byType(ListView).first;
      Future<void> scrollToText(String text) async {
        for (var i = 0;
            i < 25 && find.text(text).evaluate().isEmpty;
            i++) {
          await tester.drag(listView, const Offset(0, -250));
          await tester.pumpAndSettle();
        }
        await tester.ensureVisible(find.text(text));
        await tester.pumpAndSettle();
      }

      // 두 캐릭터를 선택한다.
      await scrollToText('토리');
      await tester.tap(find.text('토리'));
      await tester.pump();
      await scrollToText('하나');
      await tester.tap(find.text('하나'));
      await tester.pump();

      // 관계 선택 섹션이 나타난다.
      await scrollToText('관계 (선택)');
      expect(find.text('관계 (선택)'), findsOneWidget);
      expect(find.text('남매'), findsOneWidget);
    });

    testWidgets('shows forbidden-elements selector and toggles a chip',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      final listView = find.byType(ListView).first;
      for (var i = 0;
          i < 25 && find.text('빼고 싶은 요소 (선택)').evaluate().isEmpty;
          i++) {
        await tester.drag(listView, const Offset(0, -250));
        await tester.pumpAndSettle();
      }
      expect(find.text('빼고 싶은 요소 (선택)'), findsOneWidget);
      expect(find.text('폭력'), findsOneWidget);

      await tester.ensureVisible(find.text('폭력'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('폭력'));
      await tester.pump();
      // 토글 후에도 예외 없이 유지된다.
      expect(find.text('폭력'), findsOneWidget);
    });

    testWidgets('renders style selection chips', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      await tester.drag(find.byType(ListView).first, const Offset(0, -220));
      await tester.pumpAndSettle();

      expect(find.text('그림 스타일', skipOffstage: false), findsOneWidget);
      for (final style in BookStyle.values) {
        expect(find.text(style.label, skipOffstage: false), findsOneWidget);
      }
    });

    testWidgets('renders theme section (offstage accessible)', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      // 템플릿 행이 추가되어 테마 섹션이 더 아래로 밀렸으므로, lazy ListView가
      // 해당 위젯을 빌드하도록 먼저 스크롤한다(스타일 섹션 테스트와 동일한 패턴).
      await tester.drag(find.byType(ListView).first, const Offset(0, -500));
      await tester.pumpAndSettle();

      expect(find.text('테마 (선택)', skipOffstage: false), findsOneWidget);
      expect(find.text('없음', skipOffstage: false), findsOneWidget);
    });

    testWidgets('renders character section with characters', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: createOverrides(),
      ));
      await tester.pumpAndSettle();

      await tester.drag(find.byType(ListView).first, const Offset(0, -560));
      await tester.pumpAndSettle();

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

      await tester.drag(find.byType(ListView).first, const Offset(0, -560));
      await tester.pumpAndSettle();

      expect(find.text('주인공 캐릭터', skipOffstage: false), findsOneWidget);
      expect(find.text('AI가 새 캐릭터 생성', skipOffstage: false), findsOneWidget);
      expect(
        find.text(
          '캐릭터를 추가하면 같은 캐릭터로 시리즈를 만들 수 있어요!',
          skipOffstage: false,
        ),
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
      await tester.drag(find.byType(ListView).first, const Offset(0, -560));
      await tester.pump();

      // CircularProgressIndicator may be below the fold
      expect(
        find.byType(CircularProgressIndicator, skipOffstage: false),
        findsAtLeastNWidgets(1),
      );
    });

    testWidgets('shows upgrade modal when create returns payment required',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreateScreen(),
        overrides: [
          ...createOverrides(),
          apiClientProvider.overrideWithValue(
            _MockApiClient(creditsBalance: 3),
          ),
          bookCreationProvider
              .overrideWith(() => _MockPaymentRequiredBookCreationNotifier()),
        ],
      ));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextFormField), '충분히 긴 테스트 주제입니다');
      await tester.tap(find.text('동화책 만들기'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(milliseconds: 400));

      expect(find.text('플랜 업그레이드가 필요해요'), findsOneWidget);
      expect(find.textContaining('watercolor/cartoon'), findsOneWidget);
    });
  });

  // ==================== HomeScreen Tests ====================

  group('HomeScreen', () {
    List<Override> homeOverrides({
      HomeStreakSnapshot streak = _sampleStreak,
      List<LibraryBook>? books,
      List<Character>? characters,
    }) =>
        [
          libraryProvider
              .overrideWith(() => _MockLibraryNotifier(books ?? _sampleBooks)),
          homeStreakProvider.overrideWith((ref) async => streak),
          charactersProvider.overrideWith(
              () => _MockCharactersNotifier(characters ?? const [])),
        ];

    testWidgets('renders streak card with current streak and today topic',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const HomeScreen(),
        overrides: homeOverrides(books: const []),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('3일 연속 읽기'), findsOneWidget);
      expect(find.text('숲속 친구들과 협력하는 모험'), findsOneWidget);
      expect(find.text('이어 읽기'), findsOneWidget);
    });

    testWidgets('shows create CTA when no today book exists', (tester) async {
      const noBookStreak = HomeStreakSnapshot(
        currentStreak: 1,
        longestStreak: 1,
        totalDays: 1,
        readToday: false,
        todayThemeName: '모험',
        todayTopic: '하늘을 나는 토끼',
        todayBookId: null,
        readDates: {'2026-02-20'},
      );

      await tester.pumpWidget(buildTestableWidget(
        const HomeScreen(),
        overrides: homeOverrides(streak: noBookStreak, books: const []),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('오늘 동화 만들기'), findsOneWidget);
    });

    testWidgets('shows streak error card when provider fails', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const HomeScreen(),
        overrides: [
          libraryProvider.overrideWith(() => _MockLibraryNotifier(const [])),
          homeStreakProvider.overrideWith((ref) async {
            throw Exception('network');
          }),
          charactersProvider
              .overrideWith(() => _MockCharactersNotifier(const [])),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('스트릭 카드 오류'), findsOneWidget);
      expect(find.text('다시 시도'), findsOneWidget);
    });

    testWidgets('shows character-first quick-start row when characters exist',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const HomeScreen(),
        overrides: homeOverrides(books: const [], characters: _sampleCharacters),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('내 캐릭터로 바로 만들기'), findsOneWidget);
      expect(find.text('토리'), findsOneWidget);
    });
  });

  // ==================== LibraryScreen Tests ====================

  group('LibraryScreen', () {
    List<Override> libraryOverrides([LibraryBrowseState? state]) => [
          libraryBrowseProvider.overrideWith(
            () => _MockLibraryBrowseNotifier(
              state ??
                  LibraryBrowseState(
                    books: _sampleBooks,
                    total: _sampleBooks.length,
                    nextCursor: null,
                    hasMore: false,
                    isLoadingMore: false,
                    isOffline: false,
                    sort: 'newest',
                    style: null,
                    targetAge: null,
                  ),
            ),
          ),
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

      // 본문이 CustomScrollView(SliverGrid)로 바뀜 — 단권 책들은 그리드에 렌더된다.
      expect(find.byType(CustomScrollView), findsOneWidget);
      expect(find.text('토끼의 모험'), findsOneWidget);
      expect(find.text('하나의 여행'), findsOneWidget);
    });

    testWidgets('groups series books into a shelf with an add-volume tile',
        (tester) async {
      final seriesBook = LibraryBook.fromJson({
        'book_id': 'sbook-1',
        'title': '시리즈 1권',
        'cover_image_url': 'https://example.com/s1.jpg',
        'target_age': '5-7',
        'style': 'watercolor',
        'created_at': '2026-01-01T00:00:00Z',
        'series_id': 'series-x',
        'series_index': 1,
        'character_id': 'char-x',
      });
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(
          LibraryBrowseState(
            books: [seriesBook],
            total: 1,
            nextCursor: null,
            hasMore: false,
            isLoadingMore: false,
            isOffline: false,
            sort: 'newest',
            style: null,
            targetAge: null,
          ),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 시리즈 책장 헤더 + '다음 권 만들기' 타일이 렌더된다.
      expect(find.text('시리즈 · 1'), findsOneWidget);
      expect(find.text('다음 권 만들기'), findsOneWidget);
    });

    testWidgets('shows empty state when no books', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: libraryOverrides(
          const LibraryBrowseState(
            books: [],
            total: 0,
            nextCursor: null,
            hasMore: false,
            isLoadingMore: false,
            isOffline: false,
            sort: 'newest',
            style: null,
            targetAge: null,
          ),
        ),
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
          libraryBrowseProvider
              .overrideWith(() => _MockLoadingLibraryBrowseNotifier()),
        ],
      ));
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows error state', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const LibraryScreen(),
        overrides: [
          libraryBrowseProvider
              .overrideWith(() => _MockErrorLibraryBrowseNotifier()),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('서재를 불러올 수 없어요'), findsOneWidget);
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
          charactersProvider.overrideWith(
              () => _MockCharactersNotifier(chars ?? _sampleCharacters)),
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
          charactersProvider.overrideWith(() => _MockErrorCharactersNotifier()),
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

    testWidgets('shows drawing conversion option in creation sheet',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CharactersScreen(),
        overrides: charOverrides(),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byType(FloatingActionButton));
      await tester.pumpAndSettle();

      expect(find.text('아이 그림에서 변환'), findsOneWidget);
      expect(find.text('그림 사진을 캐릭터+시트로 변환'), findsOneWidget);
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

    testWidgets('exposes 구매 복원 button (Apple 3.1.1)', (tester) async {
      // 구독/비소모성 상품 앱은 '구매 복원' UI 필수 — 없으면 자동 리젝. 회귀 가드.
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(_MockApiClient()),
        ],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.byKey(const Key('restore_purchases_btn')), findsOneWidget);
      expect(find.text('구매 복원'), findsOneWidget);
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

    testWidgets('credit purchase button scrolls to plan section',
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

      expect(find.text('구독 플랜', skipOffstage: false), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders transactions when amount is string without throwing',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(
            _MockApiClient(
              transactions: [
                {
                  'id': 1,
                  'amount': '5',
                  'balance_after': 15,
                  'transaction_type': 'purchase',
                  'description': null,
                  'created_at': '2026-01-01T12:30:00Z',
                },
              ],
            ),
          ),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('거래 내역'), findsOneWidget);
      expect(find.text('purchase'), findsOneWidget);
      expect(find.text('+5'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('handles malformed credits status payload without crashing',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(
            _MockApiClient(
              creditsStatus: {
                'credits': 'unexpected',
                'subscription': {
                  'plan_name': 123,
                  'credits_per_month': '10',
                  'current_period_end': '2026-02-20T00:00:00Z',
                  'features': 'not-a-list',
                },
                'available_plans': 'not-a-list',
              },
            ),
          ),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('123 구독'), findsOneWidget);
      expect(find.text('월간 크레딧'), findsOneWidget);
      expect(find.text('구독 플랜'), findsOneWidget);
      expect(find.text('현재 이용 가능한 구독 플랜이 없습니다.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('handles non-string map keys in plan payload', (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(
            _MockApiClient(
              creditsStatus: {
                'credits': {
                  'credits': 2,
                  'total_purchased': 0,
                  'total_used': 1
                },
                'subscription': null,
                'available_plans': [
                  {1: 'invalid-key-map'},
                ],
              },
            ),
          ),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('구독 플랜'), findsOneWidget);
      expect(find.text('플랜'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('shows scheduled-cancel badge for cancelled subscription',
        (tester) async {
      await tester.pumpWidget(buildTestableWidget(
        const CreditsScreen(),
        overrides: [
          apiClientProvider.overrideWithValue(
            _MockApiClient(
              creditsStatus: {
                'credits': {'credits': 8, 'total_purchased': 10, 'total_used': 2},
                'subscription': {
                  'plan': 'basic',
                  'plan_name': '베이직',
                  'status': 'cancelled',
                  'credits_per_month': 10,
                  'current_period_end': '2026-03-20T00:00:00Z',
                  'features': ['모든 스타일'],
                },
                'available_plans': [],
              },
            ),
          ),
        ],
      ));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('해지 예정'), findsOneWidget);
      expect(find.text('현재 결제 주기가 끝나면 무료 플랜으로 전환됩니다.'), findsOneWidget);
      expect(find.text('구독 취소'), findsNothing);
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

class _MockLibraryBrowseNotifier extends LibraryBrowseNotifier {
  final LibraryBrowseState _state;

  _MockLibraryBrowseNotifier(this._state);

  @override
  Future<LibraryBrowseState> build() async => _state;
}

class _MockLoadingLibraryBrowseNotifier extends LibraryBrowseNotifier {
  @override
  Future<LibraryBrowseState> build() {
    return _neverComplete<LibraryBrowseState>();
  }
}

class _MockErrorLibraryBrowseNotifier extends LibraryBrowseNotifier {
  @override
  Future<LibraryBrowseState> build() async {
    throw Exception('Network error');
  }
}

/// Minimal mock API client that avoids actual HTTP calls
class _MockApiClient extends ApiClient {
  final Map<String, dynamic> creditsStatus;
  final List<dynamic> transactions;
  final int creditsBalance;

  _MockApiClient({
    this.creditsStatus = const {
      'credits': {'credits': 10, 'total_purchased': 0, 'total_used': 5},
      'subscription': null,
      'available_plans': [],
    },
    this.transactions = const [],
    this.creditsBalance = 10,
  }) : super(
          baseUrl: 'http://localhost',
          userKey: 'test-key',
          enableLogging: false,
        );

  @override
  Future<Map<String, dynamic>> getCreditsStatus() async {
    await Future.delayed(const Duration(milliseconds: 50));
    return creditsStatus;
  }

  @override
  Future<List<dynamic>> getTransactions(
      {int limit = 20, int offset = 0}) async {
    await Future.delayed(const Duration(milliseconds: 50));
    return transactions;
  }

  @override
  Future<int> getCreditsBalance() async {
    return creditsBalance;
  }
}

class _MockPaymentRequiredBookCreationNotifier extends BookCreationNotifier {
  @override
  Future<void> build() async {}

  @override
  Future<String> createBook(BookSpec spec) {
    throw ApiError(
      code: 'PAYMENT_REQUIRED',
      message: '무료 플랜은 watercolor/cartoon 스타일만 지원합니다. 베이직 이상으로 업그레이드해주세요.',
      statusCode: 402,
    );
  }
}

/// Returns a Future that never completes, without using a Timer.
/// This avoids the "Timer is still pending" error in Flutter tests.
Future<T> _neverComplete<T>() {
  final completer = Completer<T>();
  return completer.future;
}
