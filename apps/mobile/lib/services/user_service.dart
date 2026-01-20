import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

/// 사용자 서비스 (user_key 관리)
class UserService {
  static const _userKeyKey = 'user_key';
  final SharedPreferences _prefs;

  UserService(this._prefs);

  /// user_key 가져오기 (없으면 생성)
  String getUserKey() {
    var userKey = _prefs.getString(_userKeyKey);
    if (userKey == null || userKey.length < 10) {
      userKey = const Uuid().v4();
      _prefs.setString(_userKeyKey, userKey);
    }
    return userKey;
  }

  /// user_key 초기화 (디버그용)
  Future<void> resetUserKey() async {
    await _prefs.remove(_userKeyKey);
  }
}
