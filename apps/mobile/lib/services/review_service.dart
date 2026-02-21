import 'package:in_app_review/in_app_review.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ReviewService {
  static const _lastPromptAtKey = 'review_last_prompt_at_v1';

  final InAppReview _inAppReview;

  ReviewService({InAppReview? inAppReview})
      : _inAppReview = inAppReview ?? InAppReview.instance;

  Future<bool> canPrompt(SharedPreferences prefs) async {
    final lastPrompt = prefs.getInt(_lastPromptAtKey);
    if (lastPrompt == null) {
      return true;
    }

    final last = DateTime.fromMillisecondsSinceEpoch(lastPrompt);
    final now = DateTime.now();
    return now.difference(last).inDays >= 30;
  }

  Future<void> requestReviewIfEligible(SharedPreferences prefs) async {
    if (!await canPrompt(prefs)) {
      return;
    }

    final available = await _inAppReview.isAvailable();
    if (!available) {
      return;
    }

    await _inAppReview.requestReview();
    await prefs.setInt(_lastPromptAtKey, DateTime.now().millisecondsSinceEpoch);
  }
}
