import 'dart:convert';

import 'package:http/http.dart' as http;

/// Error from the backend with a human-readable message.
class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

class TeachSkill {
  TeachSkill(this.skill, this.price);
  final String skill;
  final int price;
  factory TeachSkill.fromJson(Map<String, dynamic> j) =>
      TeachSkill(j['skill'] as String, (j['price'] as num?)?.toInt() ?? 0);
}

class Profile {
  Profile({
    required this.name,
    required this.city,
    required this.bio,
    required this.teach,
    required this.learn,
  });
  final String name;
  final String city;
  final String bio;
  final List<TeachSkill> teach;
  final List<String> learn;

  factory Profile.fromJson(Map<String, dynamic> j) => Profile(
        name: j['name'] as String,
        city: (j['city'] as String?) ?? '',
        bio: (j['bio'] as String?) ?? '',
        teach: ((j['teach'] as List?) ?? [])
            .map((e) => TeachSkill.fromJson(e as Map<String, dynamic>))
            .toList(),
        learn: ((j['learn'] as List?) ?? []).map((e) => e as String).toList(),
      );
}

class SwapMatch {
  SwapMatch({
    required this.userId,
    required this.name,
    required this.city,
    required this.mutual,
    required this.theyTeach,
    required this.iTeach,
  });
  final String userId;
  final String name;
  final String city;
  final bool mutual;
  final List<TeachSkill> theyTeach; // what they can teach me (I would pay)
  final List<String> iTeach; // what I can teach them

  factory SwapMatch.fromJson(Map<String, dynamic> j) => SwapMatch(
        userId: j['user_id'] as String,
        name: j['name'] as String,
        city: (j['city'] as String?) ?? '',
        mutual: j['mutual'] as bool,
        theyTeach: ((j['they_teach'] as List?) ?? [])
            .map((e) => TeachSkill.fromJson(e as Map<String, dynamic>))
            .toList(),
        iTeach: ((j['i_teach'] as List?) ?? []).map((e) => e as String).toList(),
      );
}

/// A mutual swap (no credits). userA is the proposer.
class Swap {
  Swap({
    required this.id,
    required this.userA,
    required this.userB,
    required this.nameA,
    required this.nameB,
    required this.skillA,
    required this.skillB,
    required this.status,
    required this.aDone,
    required this.bDone,
  });
  final int id;
  final String userA;
  final String userB;
  final String nameA;
  final String nameB;
  final String skillA; // what A teaches B
  final String skillB; // what B teaches A
  final String status; // proposed | accepted | completed | cancelled
  final bool aDone;
  final bool bDone;

  factory Swap.fromJson(Map<String, dynamic> j) => Swap(
        id: (j['id'] as num).toInt(),
        userA: j['user_a'] as String,
        userB: j['user_b'] as String,
        nameA: (j['name_a'] as String?) ?? (j['user_a'] as String),
        nameB: (j['name_b'] as String?) ?? (j['user_b'] as String),
        skillA: j['skill_a'] as String,
        skillB: j['skill_b'] as String,
        status: j['status'] as String,
        aDone: (j['a_done'] as num) == 1,
        bDone: (j['b_done'] as num) == 1,
      );
}

/// Turns server errors into short Russian messages for the user.
String friendlyError(Object e) {
  if (e is ApiException && e.status == 409 && e.message.contains('available')) {
    return 'Недостаточно кредитов';
  }
  return e.toString();
}

class Wallet {
  Wallet({required this.available, required this.held});
  final int available; // can be spent now
  final int held; // frozen for lessons that are not confirmed yet
  factory Wallet.fromJson(Map<String, dynamic> j) => Wallet(
        available: (j['available'] as num).toInt(),
        held: (j['held'] as num).toInt(),
      );
}

class HistoryItem {
  HistoryItem({required this.amount, required this.kind, required this.createdAt});
  final int amount; // + income, - spending
  final String kind; // welcome_bonus | hold | earn | refund
  final String createdAt;
  factory HistoryItem.fromJson(Map<String, dynamic> j) => HistoryItem(
        amount: (j['amount'] as num).toInt(),
        kind: j['kind'] as String,
        createdAt: (j['created_at'] as String?) ?? '',
      );
}

/// A paid lesson: the learner's credits are held until the learner confirms it.
class Booking {
  Booking({
    required this.id,
    required this.learnerId,
    required this.teacherId,
    required this.learnerName,
    required this.teacherName,
    required this.skill,
    required this.credits,
    required this.status,
  });
  final int id;
  final String learnerId;
  final String teacherId;
  final String learnerName;
  final String teacherName;
  final String skill;
  final int credits;
  final String status; // held | completed | cancelled

  factory Booking.fromJson(Map<String, dynamic> j) => Booking(
        id: (j['id'] as num).toInt(),
        learnerId: j['learner_id'] as String,
        teacherId: j['teacher_id'] as String,
        learnerName: (j['learner_name'] as String?) ?? (j['learner_id'] as String),
        teacherName: (j['teacher_name'] as String?) ?? (j['teacher_id'] as String),
        skill: (j['skill'] as String?) ?? '',
        credits: (j['credits'] as num).toInt(),
        status: j['status'] as String,
      );
}

/// Result of a successful login.
class Session {
  Session({required this.token, required this.userId, required this.isNew});
  final String token;
  final String userId;
  final bool isNew; // first login: send the person to fill in the profile
}

dynamic _decodeAuth(http.Response r) {
  if (r.statusCode >= 200 && r.statusCode < 300) {
    if (r.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(r.bodyBytes));
  }
  var message = 'Ошибка ${r.statusCode}';
  try {
    final d = jsonDecode(utf8.decode(r.bodyBytes));
    if (d is Map && d['detail'] is String) message = d['detail'] as String;
  } catch (_) {}
  throw ApiException(r.statusCode, message);
}

/// Login by phone number: request an SMS code, then verify it.
class AuthApi {
  AuthApi(this.baseUrl);
  final String baseUrl;

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    try {
      final r = await http
          .post(
            Uri.parse('$baseUrl$path'),
            headers: {'Content-Type': 'application/json; charset=utf-8'},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 15));
      return _decodeAuth(r);
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException(0, 'Нет связи с сервером. Проверьте интернет.');
    }
  }

  Future<void> requestCode(String phone) =>
      _post('/auth/request-code', {'phone': phone});

  Future<Session> verify(String phone, String code) async {
    final j = await _post('/auth/verify', {'phone': phone, 'code': code})
        as Map<String, dynamic>;
    return Session(
      token: j['token'] as String,
      userId: j['user_id'] as String,
      isNew: j['is_new'] as bool,
    );
  }
}

/// Talks to the SWAP FastAPI backend with the login token.
/// If the server says 401 (token expired), onUnauthorized is called: the app logs out.
class SwapApi {
  SwapApi({
    required this.baseUrl,
    required this.token,
    required this.userId,
    this.onUnauthorized,
  });
  final String baseUrl;
  final String token;
  final String userId;
  final void Function()? onUnauthorized;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = Uri.parse('$baseUrl$path');
    return query == null ? base : base.replace(queryParameters: query);
  }

  dynamic _decode(http.Response r) {
    if (r.statusCode >= 200 && r.statusCode < 300) {
      if (r.bodyBytes.isEmpty) return null;
      return jsonDecode(utf8.decode(r.bodyBytes));
    }
    var message = 'Ошибка ${r.statusCode}';
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      if (d is Map && d['detail'] is String) message = d['detail'] as String;
    } catch (_) {}
    throw ApiException(r.statusCode, message);
  }

  Future<T> _guard<T>(Future<T> Function() call) async {
    try {
      return await call().timeout(const Duration(seconds: 15));
    } on ApiException catch (e) {
      if (e.status == 401) onUnauthorized?.call();
      rethrow;
    } catch (_) {
      throw ApiException(0, 'Нет связи с сервером. Проверьте интернет.');
    }
  }

  /// Returns null when the user has no profile yet.
  Future<Profile?> getProfile() => _guard(() async {
        final r = await http.get(_uri('/profile/$userId'), headers: _headers);
        if (r.statusCode == 404) return null;
        return Profile.fromJson(_decode(r) as Map<String, dynamic>);
      });

  Future<Profile> saveProfile(String name, String city, String bio) =>
      _guard(() async {
        final r = await http.put(
          _uri('/profile'),
          headers: _headers,
          body: jsonEncode({'name': name, 'city': city, 'bio': bio}),
        );
        return Profile.fromJson(_decode(r) as Map<String, dynamic>);
      });

  Future<void> addSkill(String skill, String kind, int? price) =>
      _guard(() async {
        final r = await http.post(
          _uri('/skills'),
          headers: _headers,
          body: jsonEncode({'skill': skill, 'kind': kind, 'price': price}),
        );
        _decode(r);
      });

  Future<void> removeSkill(String skill, String kind) => _guard(() async {
        final r = await http.delete(
          _uri('/skills', {'skill': skill, 'kind': kind}),
          headers: _headers,
        );
        _decode(r);
      });

  Future<List<SwapMatch>> matches() => _guard(() async {
        final r = await http.get(_uri('/matches'), headers: _headers);
        return (_decode(r) as List)
            .map((e) => SwapMatch.fromJson(e as Map<String, dynamic>))
            .toList();
      });

  Future<void> proposeSwap(String partnerId, String iTeach, String theyTeach) =>
      _guard(() async {
        final r = await http.post(
          _uri('/swaps'),
          headers: _headers,
          body: jsonEncode({
            'partner_id': partnerId,
            'i_teach': iTeach,
            'they_teach': theyTeach,
          }),
        );
        _decode(r);
      });

  Future<List<Swap>> swaps() => _guard(() async {
        final r = await http.get(_uri('/swaps'), headers: _headers);
        return (_decode(r) as List)
            .map((e) => Swap.fromJson(e as Map<String, dynamic>))
            .toList();
      });

  Future<void> _swapAction(int id, String action) => _guard(() async {
        final r = await http.post(_uri('/swaps/$id/$action'), headers: _headers);
        _decode(r);
      });

  Future<void> acceptSwap(int id) => _swapAction(id, 'accept');
  Future<void> cancelSwap(int id) => _swapAction(id, 'cancel');
  Future<void> confirmSwap(int id) => _swapAction(id, 'confirm');

  Future<Wallet> wallet() => _guard(() async {
        final r = await http.get(_uri('/credits/wallet'), headers: _headers);
        return Wallet.fromJson(_decode(r) as Map<String, dynamic>);
      });

  Future<List<HistoryItem>> history() => _guard(() async {
        final r = await http.get(_uri('/credits/history'), headers: _headers);
        return (_decode(r) as List)
            .map((e) => HistoryItem.fromJson(e as Map<String, dynamic>))
            .toList();
      });

  Future<List<Booking>> bookings() => _guard(() async {
        final r = await http.get(_uri('/credits/bookings'), headers: _headers);
        return (_decode(r) as List)
            .map((e) => Booking.fromJson(e as Map<String, dynamic>))
            .toList();
      });

  /// The server takes the price from the teacher's profile, so only skill and hours are sent.
  Future<void> bookLesson(String teacherId, String skill, int hours) =>
      _guard(() async {
        final r = await http.post(
          _uri('/credits/bookings'),
          headers: _headers,
          body: jsonEncode({'teacher_id': teacherId, 'skill': skill, 'hours': hours}),
        );
        _decode(r);
      });

  Future<void> _bookingAction(int id, String action) => _guard(() async {
        final r = await http.post(_uri('/credits/bookings/$id/$action'), headers: _headers);
        _decode(r);
      });

  Future<void> completeBooking(int id) => _bookingAction(id, 'complete');
  Future<void> cancelBooking(int id) => _bookingAction(id, 'cancel');
}
