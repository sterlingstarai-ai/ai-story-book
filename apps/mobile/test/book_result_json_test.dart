import 'dart:convert';

import 'package:ai_story_book/models/job_status.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BookResult serializes and restores nested bilingual fields', () {
    final source = BookResult(
      bookId: 'book_123',
      jobId: 'job_123',
      title: '마법 숲 이야기',
      coverImageUrl: 'https://cdn.example.com/cover.jpg',
      characterId: 'char_1',
      seriesId: 'series_1',
      seriesIndex: 2,
      titleKo: '마법 숲 이야기',
      titleEn: 'Story of the Magic Forest',
      pages: [
        PageResult(
          pageNumber: 1,
          text: '토끼가 숲으로 들어갔어요.',
          textKo: '토끼가 숲으로 들어갔어요.',
          textEn: 'The rabbit walked into the forest.',
          imageUrl: 'https://cdn.example.com/page-1.jpg',
          audioUrlKo: 'https://cdn.example.com/page-1-ko.mp3',
          audioUrlEn: 'https://cdn.example.com/page-1-en.mp3',
          vocab: [
            VocabItem(
              word: '숲',
              meaning: '나무가 많은 곳',
              example: '숲에서 새가 노래해요.',
            ),
          ],
          comprehensionQuestions: [
            ComprehensionQuestion(
              question: '토끼는 어디로 갔나요?',
              answer: '숲으로 갔어요.',
            ),
          ],
          quiz: [
            QuizItem(
              question: '토끼가 간 곳은?',
              options: const ['바다', '숲'],
              answerIndex: 1,
              explanation: '이야기에서 숲으로 들어갔어요.',
            ),
          ],
        ),
      ],
      learningAssets: LearningAssets(
        sourceLanguage: 'ko',
        targetLanguage: 'en',
        titleTranslation: 'Story of the Magic Forest',
        parentGuide: ParentGuide(
          summary: '아이와 용기에 대해 이야기해볼 수 있어요.',
          discussionPrompts: const ['왜 토끼는 숲에 갔을까요?'],
          activities: const ['토끼와 숲 그림 그리기'],
        ),
      ),
    );

    final jsonMap =
        jsonDecode(jsonEncode(source.toJson())) as Map<String, dynamic>;
    final restored = BookResult.fromJson(jsonMap);

    expect(restored.bookId, 'book_123');
    expect(restored.pages.first.textEn, 'The rabbit walked into the forest.');
    expect(restored.pages.first.vocab?.first.word, '숲');
    expect(restored.pages.first.quiz?.first.options.length, 2);
    expect(
        restored.learningAssets?.parentGuide.activities.first, '토끼와 숲 그림 그리기');
  });

  test('BookResult parses book language for audio/pronunciation requests (H3)', () {
    final restored = BookResult.fromJson({
      'book_id': 'book_ja',
      'title': 'ねこの ぼうけん',
      'cover_image_url': 'https://cdn.example.com/cover.jpg',
      'language': 'ja',
      'pages': const [],
    });
    expect(restored.language, 'ja');
  });
}
