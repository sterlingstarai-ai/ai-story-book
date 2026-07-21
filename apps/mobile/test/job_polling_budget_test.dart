import 'package:flutter_test/flutter_test.dart';

import 'package:ai_story_book/providers/providers.dart';

// H17: 폴링 예산을 서버 SLA(10분)와 일치. 이전 maxAttempts(≈4분)가 정상 잡을
// 조기 실패시키던 문제를 순수 헬퍼로 결정적 검증한다.
void main() {
  test('polling budget matches the 10-minute server SLA (H17)', () {
    // 서버 SLA 내(예: 4분·9분 59초)는 예산 초과가 아니다 — 허위 실패 없음.
    expect(jobPollingBudgetExceeded(const Duration(minutes: 4)), isFalse);
    expect(
      jobPollingBudgetExceeded(const Duration(minutes: 9, seconds: 59)),
      isFalse,
    );
    // 10분 초과에서만 타임아웃.
    expect(
      jobPollingBudgetExceeded(const Duration(minutes: 10, seconds: 1)),
      isTrue,
    );
    expect(kJobPollingHardTimeout, const Duration(minutes: 10));
  });
}
