import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// 보호자 확인 문제.
///
/// R4(2026-08-17 보안감사): 예전에는 **두 자리 덧셈**(`47 + 82`)이었다. 이 앱의 타깃 연령
/// 상단(7-9세)은 학교에서 두 자리 덧셈을 배우므로, 게이트가 막으려는 바로 그 사용자가
/// 통과한다 — 결제·동의철회·계정삭제·스크린타임이 전부 이 게이트 뒤에 있다.
///
/// 지금은 **세 자리 × 한 자리 곱셈**이다. 다자리 곱셈은 초등 고학년 이후 과정이라 7-9세가
/// 암산으로 풀 수 없고, 성인에게는 몇 초짜리다. (게이트는 보안 경계가 아니라 '아이가
/// 실수로/충동적으로 넘지 못하게' 하는 속도 방지턱이라는 점은 그대로다.)
class AgeChallenge {
  final int left;
  final int right;

  const AgeChallenge({
    required this.left,
    required this.right,
  });

  int get answer => left * right;
  String get prompt => '$left × $right = ?';
}

class ParentalControlService {
  static const consentGrantedKey = 'consent_granted_v1';
  static const onboardingDoneKey = 'onboarding_done_v1';
  static const ageGateSessionKey = 'age_gate_session_v1';
  static const reviewLastPromptAtKey = 'review_last_prompt_at_v1';
  static const _ageGateValidity = Duration(minutes: 30);

  bool _ageGateSessionVerified = false;
  final Random _random;

  ParentalControlService({Random? random}) : _random = random ?? Random();

  bool get isAgeGateVerifiedForSession => _ageGateSessionVerified;

  void resetAgeGateSession() {
    _ageGateSessionVerified = false;
  }

  void markAgeGateVerified() {
    _ageGateSessionVerified = true;
  }

  Future<void> loadAgeGateSession(SharedPreferences prefs) async {
    final verifiedAt = prefs.getInt(ageGateSessionKey);
    if (verifiedAt == null) {
      _ageGateSessionVerified = false;
      return;
    }

    final elapsed = DateTime.now()
        .difference(DateTime.fromMillisecondsSinceEpoch(verifiedAt));
    // R4: 기기 시계 되돌림에 견고하게. 예전에는 `elapsed <= 30분` 만 봤기 때문에, 시계를
    // 과거로 돌리면 elapsed 가 **음수**가 되어 조건을 항상 만족했다 → 한 번 통과한 세션이
    // 영구 유효. 음수 경과는 정상 시간 흐름이 아니므로 조작으로 보고 fail-closed 로 만료시킨다.
    if (!elapsed.isNegative && elapsed <= _ageGateValidity) {
      _ageGateSessionVerified = true;
      return;
    }

    _ageGateSessionVerified = false;
    await prefs.remove(ageGateSessionKey);
  }

  Future<void> persistAgeGateSession(SharedPreferences prefs) async {
    markAgeGateVerified();
    await prefs.setInt(
      ageGateSessionKey,
      DateTime.now().millisecondsSinceEpoch,
    );
  }

  Future<void> clearAgeGateSession(SharedPreferences prefs) async {
    resetAgeGateSession();
    await prefs.remove(ageGateSessionKey);
  }

  AgeChallenge createChallenge() {
    // 3자리(112~989) × 1자리(3~9). 0/1/2 배수와 반올림 쉬운 100단위는 제외해 난이도를
    // 균일하게 유지한다.
    return AgeChallenge(
      left: 112 + _random.nextInt(878),
      right: 3 + _random.nextInt(7),
    );
  }

  bool verifyChallenge(AgeChallenge challenge, String input) {
    final parsed = int.tryParse(input.trim());
    if (parsed == null) {
      return false;
    }
    return parsed == challenge.answer;
  }

  Future<bool> hasConsent(SharedPreferences prefs) async {
    return prefs.getBool(consentGrantedKey) ?? false;
  }

  Future<void> setConsent(
    SharedPreferences prefs,
    bool granted,
  ) async {
    await prefs.setBool(consentGrantedKey, granted);
    if (!granted) {
      await prefs.setBool(onboardingDoneKey, false);
      await clearAgeGateSession(prefs);
    }
  }

  Future<bool> hasSeenOnboarding(SharedPreferences prefs) async {
    return prefs.getBool(onboardingDoneKey) ?? false;
  }

  Future<void> setOnboardingDone(
    SharedPreferences prefs,
    bool done,
  ) async {
    await prefs.setBool(onboardingDoneKey, done);
  }
}
