import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api.dart';
import 'matches_screen.dart';
import 'profile_screen.dart';
import 'session_store.dart';
import 'swaps_screen.dart';
import 'wallet_screen.dart';

/// Backend address.
/// Android emulator: http://10.0.2.2:8000 (points to your computer).
/// Real phone: use your server address, e.g. https://api.your-domain.uz
const String apiBaseUrl =
    String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000');

void main() => runApp(const SwapApp());

class SwapApp extends StatelessWidget {
  const SwapApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SWAP',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF2E7D6B),
      ),
      home: const Gate(),
    );
  }
}

/// Decides what to show: the app (if logged in) or the login screens.
class Gate extends StatefulWidget {
  const Gate({super.key});

  @override
  State<Gate> createState() => _GateState();
}

class _GateState extends State<Gate> {
  bool _loading = true;
  Session? _session;
  SwapApi? _api;

  @override
  void initState() {
    super.initState();
    SessionStore.load().then((s) {
      if (!mounted) return;
      setState(() {
        if (s != null) _start(s);
        _loading = false;
      });
    });
  }

  void _start(Session s) {
    _session = s;
    _api = SwapApi(
      baseUrl: apiBaseUrl,
      token: s.token,
      userId: s.userId,
      onUnauthorized: _logout,
    );
  }

  Future<void> _onLoggedIn(Session s) async {
    await SessionStore.save(s);
    if (!mounted) return;
    setState(() => _start(s));
  }

  Future<void> _logout() async {
    if (_session == null) return; // several requests can fail at once
    await SessionStore.clear();
    if (!mounted) return;
    setState(() {
      _session = null;
      _api = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final s = _session;
    if (s == null) return PhoneScreen(onLoggedIn: _onLoggedIn);
    return HomeScreen(
      key: ValueKey(s.userId),
      api: _api!,
      initialTab: s.isNew ? 3 : 0, // new people start on the profile
      onLogout: _logout,
    );
  }
}

class _AuthScaffold extends StatelessWidget {
  const _AuthScaffold({required this.children, this.showBack = false});
  final List<Widget> children;
  final bool showBack;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: showBack ? AppBar() : null,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: children,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class PhoneScreen extends StatefulWidget {
  const PhoneScreen({super.key, required this.onLoggedIn});
  final Future<void> Function(Session) onLoggedIn;

  @override
  State<PhoneScreen> createState() => _PhoneScreenState();
}

class _PhoneScreenState extends State<PhoneScreen> {
  final _phone = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _phone.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final digits = _phone.text.trim();
    if (digits.length != 9) {
      setState(() => _error = 'Введите 9 цифр номера, например 90 123 45 67');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final phone = '+998$digits';
    try {
      await AuthApi(apiBaseUrl).requestCode(phone);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => CodeScreen(phone: phone, onLoggedIn: widget.onLoggedIn),
      ));
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return _AuthScaffold(
      children: [
        Text('SWAP',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.displaySmall),
        const SizedBox(height: 8),
        const Text('Учись и учи других', textAlign: TextAlign.center),
        const SizedBox(height: 32),
        TextField(
          controller: _phone,
          keyboardType: TextInputType.phone,
          inputFormatters: [
            FilteringTextInputFormatter.digitsOnly,
            LengthLimitingTextInputFormatter(9),
          ],
          decoration: InputDecoration(
            labelText: 'Номер телефона',
            prefixText: '+998 ',
            border: const OutlineInputBorder(),
            errorText: _error,
          ),
          onSubmitted: (_) => _send(),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _send,
          child: Text(_busy ? 'Отправляю...' : 'Получить код по SMS'),
        ),
      ],
    );
  }
}

class CodeScreen extends StatefulWidget {
  const CodeScreen({super.key, required this.phone, required this.onLoggedIn});
  final String phone;
  final Future<void> Function(Session) onLoggedIn;

  @override
  State<CodeScreen> createState() => _CodeScreenState();
}

class _CodeScreenState extends State<CodeScreen> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _error;
  int _wait = 60; // seconds until "send again" is allowed
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startTimer();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  void _startTimer() {
    _timer?.cancel();
    setState(() => _wait = 60);
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return;
      setState(() => _wait = _wait > 0 ? _wait - 1 : 0);
      if (_wait == 0) t.cancel();
    });
  }

  Future<void> _verify() async {
    final code = _code.text.trim();
    if (code.length != 6) {
      setState(() => _error = 'Введите 6 цифр из SMS');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final session = await AuthApi(apiBaseUrl).verify(widget.phone, code);
      await widget.onLoggedIn(session);
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resend() async {
    try {
      await AuthApi(apiBaseUrl).requestCode(widget.phone);
      _startTimer();
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return _AuthScaffold(
      showBack: true,
      children: [
        Text('Введите код', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        Text('Мы отправили SMS на ${widget.phone}'),
        const SizedBox(height: 24),
        TextField(
          controller: _code,
          autofocus: true,
          keyboardType: TextInputType.number,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 28, letterSpacing: 8),
          inputFormatters: [
            FilteringTextInputFormatter.digitsOnly,
            LengthLimitingTextInputFormatter(6),
          ],
          decoration: InputDecoration(
            border: const OutlineInputBorder(),
            errorText: _error,
          ),
          onChanged: (v) {
            if (v.length == 6 && !_busy) _verify();
          },
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _verify,
          child: Text(_busy ? 'Проверяю...' : 'Войти'),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: _wait == 0 ? _resend : null,
          child: Text(_wait == 0
              ? 'Отправить код ещё раз'
              : 'Отправить ещё раз через $_wait с'),
        ),
      ],
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.api,
    required this.onLogout,
    this.initialTab = 0,
  });
  final SwapApi api;
  final VoidCallback onLogout;
  final int initialTab;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late int _tab = widget.initialTab;

  Future<void> _askLogout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Выйти из аккаунта?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Нет')),
          FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Выйти')),
        ],
      ),
    );
    if (ok == true) widget.onLogout();
  }

  @override
  Widget build(BuildContext context) {
    const titles = ['Подбор', 'Обмены', 'Кошелёк', 'Профиль'];
    final pages = [
      MatchesScreen(api: widget.api),
      SwapsScreen(api: widget.api),
      WalletScreen(api: widget.api),
      ProfileScreen(api: widget.api),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(titles[_tab]),
        actions: [
          IconButton(
            tooltip: 'Выйти',
            icon: const Icon(Icons.logout),
            onPressed: _askLogout,
          ),
        ],
      ),
      body: pages[_tab], // rebuilt on every tab switch, so data is always fresh
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.swap_horiz), label: 'Подбор'),
          NavigationDestination(icon: Icon(Icons.handshake), label: 'Обмены'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet), label: 'Кошелёк'),
          NavigationDestination(icon: Icon(Icons.person), label: 'Профиль'),
        ],
      ),
    );
  }
}
