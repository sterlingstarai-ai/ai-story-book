"""P1-8: 스트릭 마일스톤 — 보상은 누적(total_days)에 붙어 임계마다 한 번만 발화(악용 불가).

핵심: 스트릭을 깼다 다시 쌓아도 total_days는 줄지 않으므로 보상이 재지급되지 않는다.
(적대적 리뷰가 잡은 current_streak == days repeat-after-reset 버그를 보상에서 회피.)
"""

from src.services.streak import streak_service


def test_total_milestone_has_reward_and_fires_at_threshold():
    ms = streak_service._check_milestones(current_streak=3, total_days=10)
    total10 = [m for m in ms if m["type"] == "total" and m["days"] == 10]
    assert len(total10) == 1
    assert total10[0]["reward"] == "free_pdf"


def test_total_reward_does_not_refire_past_threshold():
    # 누적이 임계를 지나면(=11) 더 이상 발화하지 않음 → 보상 1회만(exploit-proof)
    ms = streak_service._check_milestones(current_streak=3, total_days=11)
    assert not any(m["type"] == "total" and m["days"] == 10 for m in ms)


def test_streak_milestone_carries_no_reward():
    # 스트릭 마일스톤은 축하용(보상 없음) — 재축적 재발화해도 악용 위험 없음
    ms = streak_service._check_milestones(current_streak=7, total_days=7)
    streak7 = [m for m in ms if m["type"] == "streak" and m["days"] == 7]
    assert len(streak7) == 1
    assert streak7[0]["reward"] is None
