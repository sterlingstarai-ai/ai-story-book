/// 읽기 기록(날짜 목록)을 주 단위로 집계 — 순수함수(플러그인/네트워크 의존 0, 단위테스트 대상).
///
/// now 기준 최근 [weeks]주의 읽기 횟수를 반환한다. 결과의 마지막 원소가 '이번 주'.
/// 백엔드 시계열 엔드포인트 없이 기존 /v1/streak/history(날짜 목록)에서 클라이언트 집계한다.
List<int> weeklyReadingCounts(
  List<DateTime> dates,
  DateTime now, {
  int weeks = 6,
}) {
  final counts = List<int>.filled(weeks, 0);
  final today = DateTime(now.year, now.month, now.day);
  for (final d in dates) {
    final day = DateTime(d.year, d.month, d.day);
    final daysAgo = today.difference(day).inDays;
    if (daysAgo < 0) {
      continue; // 미래 날짜 무시
    }
    final wk = weeks - 1 - (daysAgo ~/ 7);
    if (wk >= 0 && wk < weeks) {
      counts[wk]++;
    }
  }
  return counts;
}
