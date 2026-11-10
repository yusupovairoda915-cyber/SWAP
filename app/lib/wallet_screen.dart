import 'package:flutter/material.dart';

import 'api.dart';

/// Credits balance, paid lessons (confirm / cancel) and the history of credits.
class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key, required this.api});
  final SwapApi api;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  Wallet? _wallet;
  List<Booking> _bookings = [];
  List<HistoryItem> _history = [];
  bool _loading = true;
  String? _error;
  int? _busyId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _toast(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _fetch() async {
    final results = await Future.wait([
      widget.api.wallet(),
      widget.api.bookings(),
      widget.api.history(),
    ]);
    if (!mounted) return;
    setState(() {
      _wallet = results[0] as Wallet;
      _bookings = results[1] as List<Booking>;
      _history = results[2] as List<HistoryItem>;
    });
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await _fetch();
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = friendlyError(e);
        _loading = false;
      });
    }
  }

  Future<void> _act(Booking b, Future<void> Function(int) action, String done) async {
    setState(() => _busyId = b.id);
    try {
      await action(b.id);
      _toast(done);
    } catch (e) {
      _toast(friendlyError(e));
    }
    try {
      await _fetch(); // refresh either way: the other side may have changed it
    } catch (_) {}
    if (mounted) setState(() => _busyId = null);
  }

  Future<void> _confirmDone(Booking b) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Урок прошёл?'),
        content: Text(
            '${b.teacherName} получит ${b.credits} кр. Это нельзя отменить.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Нет')),
          FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Да, заплатить')),
        ],
      ),
    );
    if (ok == true) {
      await _act(b, widget.api.completeBooking, 'Готово. Кредиты переданы учителю.');
    }
  }

  Future<void> _confirmCancel(Booking b, bool iAmLearner) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Отменить урок?'),
        content: Text(iAmLearner
            ? 'Кредиты (${b.credits}) вернутся к вам.'
            : 'Кредиты (${b.credits}) вернутся ученику.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Нет')),
          FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Да, отменить')),
        ],
      ),
    );
    if (ok == true) await _act(b, widget.api.cancelBooking, 'Урок отменён');
  }

  String _kindLabel(String kind) => switch (kind) {
        'welcome_bonus' => 'Приветственный бонус',
        'hold' => 'Заморожено под урок',
        'earn' => 'Получено за урок',
        'refund' => 'Возврат за отменённый урок',
        _ => kind,
      };

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('Повторить')),
            ],
          ),
        ),
      );
    }

    final theme = Theme.of(context);
    final w = _wallet!;
    final me = widget.api.userId;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            color: theme.colorScheme.primaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Ваши кредиты'),
                  const SizedBox(height: 4),
                  Text('${w.available}', style: theme.textTheme.displayMedium),
                  if (w.held > 0) ...[
                    const SizedBox(height: 4),
                    Text('Заморожено под уроки: ${w.held}'),
                  ],
                  const SizedBox(height: 8),
                  Text(
                    '1 кредит ≈ 1 час обучения. Кредиты зарабатываются, когда вы учите других.',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text('Платные уроки', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          if (_bookings.isEmpty)
            Text(
              'Пока нет. Запишитесь на урок на вкладке «Подбор».',
              style: theme.textTheme.bodySmall,
            ),
          for (final b in _bookings) _bookingCard(context, b, me),
          const SizedBox(height: 16),
          Text('История кредитов', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          for (final h in _history)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text(_kindLabel(h.kind)),
              subtitle: Text(h.createdAt),
              trailing: Text(
                h.amount > 0 ? '+${h.amount}' : '${h.amount}',
                style: theme.textTheme.titleMedium?.copyWith(
                  color: h.amount > 0 ? Colors.green.shade700 : theme.colorScheme.error,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _bookingCard(BuildContext context, Booking b, String me) {
    final theme = Theme.of(context);
    final iAmLearner = b.learnerId == me;
    final partner = iAmLearner ? b.teacherName : b.learnerName;
    final title = iAmLearner ? 'Вы учитесь: ${b.skill}' : 'Вы учите: ${b.skill}';
    final money = iAmLearner ? '−${b.credits} кр' : '+${b.credits} кр';

    final (statusText, statusColor) = switch (b.status) {
      'held' => ('Ждёт урока', theme.colorScheme.primaryContainer),
      'completed' => ('Оплачен', theme.colorScheme.surfaceContainerHighest),
      _ => ('Отменён', theme.colorScheme.surfaceContainerHighest),
    };

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(partner, style: theme.textTheme.titleMedium)),
                Chip(
                  label: Text(statusText),
                  backgroundColor: statusColor,
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text('$title · $money'),
            if (b.status == 'held') ...[
              const SizedBox(height: 12),
              if (_busyId == b.id)
                const Align(
                  alignment: Alignment.centerRight,
                  child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2)),
                )
              else
                Wrap(
                  alignment: WrapAlignment.end,
                  spacing: 8,
                  children: [
                    TextButton(
                      onPressed: () => _confirmCancel(b, iAmLearner),
                      child: const Text('Отменить'),
                    ),
                    if (iAmLearner)
                      FilledButton(
                        onPressed: () => _confirmDone(b),
                        child: const Text('Урок прошёл'),
                      ),
                  ],
                ),
              if (!iAmLearner) ...[
                const SizedBox(height: 8),
                Text('Кредиты придут, когда ученик подтвердит урок.',
                    style: theme.textTheme.bodySmall),
              ],
            ],
          ],
        ),
      ),
    );
  }
}
