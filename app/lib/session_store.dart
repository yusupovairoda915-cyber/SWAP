import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';

/// Keeps the login token on the phone (encrypted storage), so the person
/// does not have to log in again every time the app starts.
class SessionStore {
  static const _storage = FlutterSecureStorage();

  static Future<Session?> load() async {
    try {
      final token = await _storage.read(key: 'token');
      final userId = await _storage.read(key: 'user_id');
      if (token == null || userId == null) return null;
      return Session(token: token, userId: userId, isNew: false);
    } catch (_) {
      return null; // storage unavailable: just ask to log in
    }
  }

  static Future<void> save(Session s) async {
    try {
      await _storage.write(key: 'token', value: s.token);
      await _storage.write(key: 'user_id', value: s.userId);
    } catch (_) {}
  }

  static Future<void> clear() async {
    try {
      await _storage.deleteAll();
    } catch (_) {}
  }
}
