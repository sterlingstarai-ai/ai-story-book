import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

class AgeChallenge {
  final int left;
  final int right;

  const AgeChallenge({
    required this.left,
    required this.right,
  });

  int get answer => left + right;
  String get prompt => '$left + $right = ?';
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
    if (elapsed <= _ageGateValidity) {
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
    return AgeChallenge(
      left: 10 + _random.nextInt(90),
      right: 10 + _random.nextInt(90),
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
