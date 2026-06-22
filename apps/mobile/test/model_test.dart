import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/models/models.dart';

void main() {
  group('LibraryBook', () {
    test('fromJson parses series and character metadata', () {
      final book = LibraryBook.fromJson({
        'book_id': 'book-1',
        'title': '또또의 모험 2권',
        'cover_image_url': 'https://example.com/c.jpg',
        'target_age': '5-7',
        'style': 'watercolor',
        'created_at': '2026-01-01T00:00:00Z',
        'series_id': 'series-1',
        'series_index': 2,
        'character_id': 'char-1',
      });

      expect(book.seriesId, 'series-1');
      expect(book.seriesIndex, 2);
      expect(book.characterId, 'char-1');
    });

    test('fromJson leaves series fields null when absent', () {
      final book = LibraryBook.fromJson({
        'book_id': 'book-2',
        'title': '단권 동화',
        'cover_image_url': 'https://example.com/c2.jpg',
        'target_age': '3-5',
        'style': 'cartoon',
        'created_at': '2026-01-02T00:00:00Z',
      });

      expect(book.seriesId, isNull);
      expect(book.seriesIndex, isNull);
      expect(book.characterId, isNull);
    });
  });

  group('BookSpec', () {
    test('creates instance with required fields', () {
      final spec = BookSpec(
        topic: '토끼 이야기',
        targetAge: '5-7',
        style: 'watercolor',
      );

      expect(spec.topic, equals('토끼 이야기'));
      expect(spec.targetAge, equals('5-7'));
      expect(spec.style, equals('watercolor'));
      expect(spec.language, equals('ko')); // default
      expect(spec.pageCount, equals(8)); // default
    });

    test('toJson includes all fields', () {
      final spec = BookSpec(
        topic: '토끼 이야기',
        targetAge: '5-7',
        style: 'watercolor',
        theme: '우정',
        characterId: 'char-123',
        forbiddenElements: ['폭력'],
      );

      final json = spec.toJson();

      expect(json['topic'], equals('토끼 이야기'));
      expect(json['target_age'], equals('5-7'));
      expect(json['style'], equals('watercolor'));
      expect(json['theme'], equals('우정'));
      expect(json['character_id'], equals('char-123'));
      expect(json['forbidden_elements'], equals(['폭력']));
    });

    test('toJson excludes null optional fields', () {
      final spec = BookSpec(
        topic: '토끼 이야기',
        targetAge: '5-7',
        style: 'watercolor',
      );

      final json = spec.toJson();

      expect(json.containsKey('theme'), isFalse);
      expect(json.containsKey('character_id'), isFalse);
      expect(json.containsKey('forbidden_elements'), isFalse);
    });
  });

  group('TargetAge', () {
    test('has correct values', () {
      expect(TargetAge.age3to5.value, equals('3-5'));
      expect(TargetAge.age5to7.value, equals('5-7'));
      expect(TargetAge.age7to9.value, equals('7-9'));
      expect(TargetAge.adult.value, equals('adult'));
    });

    test('has correct labels', () {
      expect(TargetAge.age3to5.label, equals('3-5세'));
      expect(TargetAge.age5to7.label, equals('5-7세'));
      expect(TargetAge.age7to9.label, equals('7-9세'));
      expect(TargetAge.adult.label, equals('성인'));
    });
  });

  group('BookStyle', () {
    test('has all styles', () {
      expect(BookStyle.values.length, equals(7));
      expect(BookStyle.watercolor.value, equals('watercolor'));
      expect(BookStyle.cartoon.value, equals('cartoon'));
      expect(BookStyle.threeD.value, equals('3d'));
      expect(BookStyle.pixel.value, equals('pixel'));
      expect(BookStyle.oilPainting.value, equals('oil_painting'));
      expect(BookStyle.claymation.value, equals('claymation'));
      expect(BookStyle.realistic.value, equals('realistic'));
    });
  });

  group('JobStatus', () {
    test('fromJson parses correctly', () {
      final json = {
        'job_id': 'job-123',
        'status': 'running',
        'progress': 50,
        'current_step': 'generating_story',
      };

      final status = JobStatus.fromJson(json);

      expect(status.jobId, equals('job-123'));
      expect(status.status, equals(JobState.running));
      expect(status.progress, equals(50));
      expect(status.currentStep, equals('generating_story'));
    });

    test('fromJson coerces mixed scalar types', () {
      final json = {
        'job_id': 12345,
        'status': 'running',
        'progress': '75',
      };

      final status = JobStatus.fromJson(json);

      expect(status.jobId, equals('12345'));
      expect(status.status, equals(JobState.running));
      expect(status.progress, equals(75));
    });

    test('isComplete returns true for done status', () {
      final status = JobStatus(
        jobId: 'job-123',
        status: JobState.done,
        progress: 100,
      );

      expect(status.isComplete, isTrue);
      expect(status.isFailed, isFalse);
      expect(status.isRunning, isFalse);
    });

    test('isFailed returns true for failed status', () {
      final status = JobStatus(
        jobId: 'job-123',
        status: JobState.failed,
        progress: 50,
        errorCode: 'LLM_TIMEOUT',
        errorMessage: 'Request timed out',
      );

      expect(status.isComplete, isFalse);
      expect(status.isFailed, isTrue);
      expect(status.isRunning, isFalse);
    });

    test('isRunning returns true for queued and running status', () {
      final queued = JobStatus(
        jobId: 'job-123',
        status: JobState.queued,
        progress: 0,
      );

      final running = JobStatus(
        jobId: 'job-123',
        status: JobState.running,
        progress: 50,
      );

      expect(queued.isRunning, isTrue);
      expect(running.isRunning, isTrue);
    });
  });

  group('JobState', () {
    test('fromString parses valid states', () {
      expect(JobState.fromString('queued'), equals(JobState.queued));
      expect(JobState.fromString('running'), equals(JobState.running));
      expect(JobState.fromString('failed'), equals(JobState.failed));
      expect(JobState.fromString('done'), equals(JobState.done));
    });

    test('fromString returns queued for invalid state', () {
      expect(JobState.fromString('invalid'), equals(JobState.queued));
    });
  });

  group('BookResult', () {
    test('fromJson parses correctly', () {
      final json = {
        'book_id': 'book-123',
        'title': '토끼의 모험',
        'cover_image_url': 'https://example.com/cover.jpg',
        'pages': [
          {
            'page_number': 1,
            'text': '옛날 옛적에...',
            'image_url': 'https://example.com/page1.jpg',
          },
        ],
        'character_id': 'char-123',
      };

      final result = BookResult.fromJson(json);

      expect(result.bookId, equals('book-123'));
      expect(result.title, equals('토끼의 모험'));
      expect(result.coverImageUrl, equals('https://example.com/cover.jpg'));
      expect(result.pages.length, equals(1));
      expect(result.characterId, equals('char-123'));
    });

    test('fromJson parses numeric series index string', () {
      final json = {
        'book_id': 'book-123',
        'title': '토끼의 모험',
        'cover_image_url': 'https://example.com/cover.jpg',
        'pages': [
          {
            'page_number': 1,
            'text': '옛날 옛적에...',
            'image_url': 'https://example.com/page1.jpg',
          },
        ],
        'series_index': '2',
      };

      final result = BookResult.fromJson(json);

      expect(result.seriesIndex, equals(2));
    });
  });

  group('PageResult', () {
    test('fromJson parses correctly', () {
      final json = {
        'page_number': 1,
        'text': '옛날 옛적에...',
        'image_url': 'https://example.com/page1.jpg',
      };

      final page = PageResult.fromJson(json);

      expect(page.pageNumber, equals(1));
      expect(page.text, equals('옛날 옛적에...'));
      expect(page.imageUrl, equals('https://example.com/page1.jpg'));
    });

    test('fromJson parses string page number and quiz option coercion', () {
      final json = {
        'page_number': '2',
        'text': '다음 날...',
        'image_url': 'https://example.com/page2.jpg',
        'quiz': [
          {
            'question': '정답은?',
            'options': ['하나', 2],
            'answer_index': '1',
          },
        ],
      };

      final page = PageResult.fromJson(json);

      expect(page.pageNumber, equals(2));
      expect(page.quiz, isNotNull);
      expect(page.quiz!.first.options, equals(['하나', '2']));
      expect(page.quiz!.first.answerIndex, equals(1));
    });

    test('hasLearningContent is true when only comprehension exists', () {
      final page = PageResult(
        pageNumber: 1,
        text: '본문',
        imageUrl: 'https://example.com/page.jpg',
        comprehensionQuestions: [
          ComprehensionQuestion(
            question: '누가 주인공인가요?',
            answer: '토끼예요.',
          ),
        ],
      );

      expect(page.hasLearningContent, isTrue);
    });

    test('hasLearningContent is true when only quiz exists', () {
      final page = PageResult(
        pageNumber: 1,
        text: '본문',
        imageUrl: 'https://example.com/page.jpg',
        quiz: [
          QuizItem(
            question: '정답은?',
            options: ['하나', '둘'],
            answerIndex: 0,
          ),
        ],
      );

      expect(page.hasLearningContent, isTrue);
    });

    test('hasLearningContent is false when all learning assets are empty', () {
      final page = PageResult(
        pageNumber: 1,
        text: '본문',
        imageUrl: 'https://example.com/page.jpg',
        vocab: const [],
        comprehensionQuestions: const [],
        quiz: const [],
      );

      expect(page.hasLearningContent, isFalse);
    });
  });

  group('Character', () {
    test('fromJson parses correctly', () {
      final json = {
        'id': 'char-123',
        'name': '토리',
        'master_description': '귀여운 토끼',
        'appearance': {
          'age_visual': '5세',
          'face': '둥근 얼굴',
          'hair': '없음',
          'skin': '갈색 털',
          'body': '통통함',
        },
        'clothing': {
          'top': '티셔츠',
          'bottom': '바지',
          'shoes': '운동화',
          'accessories': '없음',
        },
        'personality_traits': ['호기심', '용감함'],
        'visual_style_notes': '수채화',
        'created_at': '2024-01-01T00:00:00Z',
      };

      final character = Character.fromJson(json);

      expect(character.id, equals('char-123'));
      expect(character.name, equals('토리'));
      expect(character.masterDescription, equals('귀여운 토끼'));
      expect(character.appearance.face, equals('둥근 얼굴'));
      expect(character.clothing.top, equals('티셔츠'));
      expect(character.personalityTraits, contains('호기심'));
      expect(character.distinctiveFeatures, isNull);
    });

    test('fromJson parses distinctive_features when present', () {
      final character = Character.fromJson({
        'id': 'char-df',
        'name': '토리',
        'master_description': '귀여운 토끼',
        'appearance': {
          'age_visual': '5세',
          'face': '둥근 얼굴',
          'hair': '없음',
          'skin': '갈색 털',
          'body': '통통함',
        },
        'clothing': {
          'top': '티셔츠',
          'bottom': '바지',
          'shoes': '운동화',
          'accessories': '빨간 안경',
        },
        'personality_traits': ['용감함'],
        'visual_style_notes': '수채화',
        'distinctive_features': ['빨간 안경', '주근깨'],
        'created_at': '2024-01-01T00:00:00Z',
      });

      expect(character.distinctiveFeatures, equals(['빨간 안경', '주근깨']));
    });

    test('fromJson coerces mixed scalar types', () {
      final json = {
        'character_id': 777,
        'name': 123,
        'master_description': '설명',
        'appearance': {
          'age_visual': '5세',
          'face': 9,
          'hair': '없음',
          'skin': '갈색 털',
          'body': '통통함',
        },
        'clothing': {
          'top': '티셔츠',
          'bottom': '바지',
          'shoes': '운동화',
          'accessories': 0,
        },
        'personality_traits': ['호기심', 42],
        'created_at': '2024-01-01T00:00:00Z',
      };

      final character = Character.fromJson(json);

      expect(character.id, equals('777'));
      expect(character.name, equals('123'));
      expect(character.appearance.face, equals('9'));
      expect(character.clothing.accessories, equals('0'));
      expect(character.personalityTraits, equals(['호기심', '42']));
    });
  });

  group('Appearance', () {
    test('toJson returns correct format', () {
      final appearance = Appearance(
        ageVisual: '5세',
        face: '둥근 얼굴',
        hair: '없음',
        skin: '갈색 털',
        body: '통통함',
      );

      final json = appearance.toJson();

      expect(json['age_visual'], equals('5세'));
      expect(json['face'], equals('둥근 얼굴'));
    });
  });

  group('Clothing', () {
    test('toJson returns correct format', () {
      final clothing = Clothing(
        top: '티셔츠',
        bottom: '바지',
        shoes: '운동화',
        accessories: '없음',
      );

      final json = clothing.toJson();

      expect(json['top'], equals('티셔츠'));
      expect(json['bottom'], equals('바지'));
    });
  });

  group('LibraryBook', () {
    test('fromJson parses correctly', () {
      final json = {
        'id': 'book-123',
        'title': '토끼의 모험',
        'cover_image_url': 'https://example.com/cover.jpg',
        'target_age': '5-7',
        'style': 'watercolor',
        'theme': '우정',
        'created_at': '2024-01-01T00:00:00Z',
      };

      final book = LibraryBook.fromJson(json);

      expect(book.id, equals('book-123'));
      expect(book.title, equals('토끼의 모험'));
      expect(book.targetAge, equals('5-7'));
      expect(book.theme, equals('우정'));
    });

    test('fromJson coerces mixed scalar types', () {
      final json = {
        'book_id': 100,
        'title': '숫자 제목',
        'cover_image_url': 'https://example.com/cover.jpg',
        'target_age': 7,
        'style': 'watercolor',
        'theme': 123,
        'created_at': '2024-01-01T00:00:00Z',
      };

      final book = LibraryBook.fromJson(json);

      expect(book.id, equals('100'));
      expect(book.targetAge, equals('7'));
      expect(book.theme, equals('123'));
    });
  });

  group('LibraryResponse', () {
    test('fromJson parses correctly', () {
      final json = {
        'books': [
          {
            'id': 'book-123',
            'title': '토끼의 모험',
            'cover_image_url': 'https://example.com/cover.jpg',
            'target_age': '5-7',
            'style': 'watercolor',
            'created_at': '2024-01-01T00:00:00Z',
          },
        ],
        'total': 1,
      };

      final response = LibraryResponse.fromJson(json);

      expect(response.books.length, equals(1));
      expect(response.total, equals(1));
    });

    test('fromJson falls back total to books length when omitted', () {
      final json = {
        'books': [
          {
            'id': 'book-123',
            'title': '토끼의 모험',
            'cover_image_url': 'https://example.com/cover.jpg',
            'target_age': '5-7',
            'style': 'watercolor',
            'created_at': '2024-01-01T00:00:00Z',
          },
          {
            'id': 'book-456',
            'title': '곰의 모험',
            'cover_image_url': 'https://example.com/cover2.jpg',
            'target_age': '7-9',
            'style': 'cartoon',
            'created_at': '2024-01-02T00:00:00Z',
          },
        ],
      };

      final response = LibraryResponse.fromJson(json);

      expect(response.books.length, equals(2));
      expect(response.total, equals(2));
    });
  });
}
