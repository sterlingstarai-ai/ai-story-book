import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('running session expires without reloading preferences', () {
    var now = DateTime(2026, 9, 19, 12);
    final service = ParentalControlService(now: () => now);
    service.markAgeGateVerified();
    now = now.add(const Duration(minutes: 30));
    expect(service.isAgeGateVerifiedForSession, isTrue);
    now = now.add(const Duration(milliseconds: 1));
    expect(service.isAgeGateVerifiedForSession, isFalse);
    now = now.subtract(const Duration(minutes: 5));
    expect(service.isAgeGateVerifiedForSession, isFalse);
  });
  test(
    'restored approval keeps its original expiry and rejects clock rollback',
    () async {
      final verifiedAt = DateTime(2026, 9, 19, 12);
      var now = verifiedAt.add(const Duration(minutes: 29));
      SharedPreferences.setMockInitialValues({
        ParentalControlService.ageGateSessionKey:
            verifiedAt.millisecondsSinceEpoch,
      });
      final prefs = await SharedPreferences.getInstance();
      final service = ParentalControlService(now: () => now);
      await service.loadAgeGateSession(prefs);
      expect(service.isAgeGateVerifiedForSession, isTrue);
      now = now.add(const Duration(minutes: 2));
      expect(service.isAgeGateVerifiedForSession, isFalse);
      service.markAgeGateVerified();
      now = now.subtract(const Duration(seconds: 1));
      expect(service.isAgeGateVerifiedForSession, isFalse);
      await service.persistAgeGateSession(prefs);
      expect(service.isAgeGateVerifiedForSession, isTrue);
      await service.clearAgeGateSession(prefs);
      expect(service.isAgeGateVerifiedForSession, isFalse);
    },
  );
}
