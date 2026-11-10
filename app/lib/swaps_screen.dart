import 'package:flutter/material.dart';

import 'api.dart';

/// My swaps: incoming proposals, active swaps, history.
class SwapsScreen extends StatefulWidget {
  const SwapsScreen({super.key, required this.api});
  final SwapApi api;

  @override
  State<SwapsScreen> createState() => _SwapsScreenState();
}

class _SwapsScreenState extends State<SwapsScreen> {
  List<Swap> _swaps = [];
  bool _loading = true;
  String? _error;
  int? _busyId; // swap that is being changed right now

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

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final s = await widget.api.swaps();
      if (!mounted) return;
      setState(() {
        _swaps = s;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _act(Swap s, Future<void> Function(int) action, String done) async {
    setState(() => _busyId = s.id);
    try {
      await action(s.id);
      _toast(done);
      final fresh = await widget.api.swaps();
      if (mounted) setState(() => _swaps = fresh);
    } catch (e) {
      _toast(e.toString());
      // state may have changed on the other side: refresh the list
      try {
        final fresh = await widget.api.swaps();
        if (mounted) setState(() => _swaps = fresh);
      } catch (_) {}
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  Future<void> _confirmCancel(Swap s) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Отменить обмен?'),
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
    if (ok == true) await _act(s, widget.api.cancelSwap, 'Обмен отменён');
  }

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
    return RefreshIndicator(
      onRefresh: _load,
      child: _swaps.isEmpty
          ? ListView(
              children: const [
                SizedBox(height: 120),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 32),
                  child: Text(
                    'Обменов пока нет. Откройте «Подбор» и предложите обмен.',
                    textAlign: TextAlign.center,
                  ),
                ),
              ],
            )
          : ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: _swaps.length,
              itemBuilder: (_, i) {
                final s = _swaps[i];
                return _SwapCard(
                  swap: s,
                  me: widget.api.userId,
                  busy: _busyId == s.id,
                  onAccept: () => _act(s, widget.api.acceptSwap, 'Обмен принят'),
                  onDecline: () => _act(s, widget.api.cancelSwap, 'Предложение отклонено'),
                  onCancel: () => _confirmCancel(s),
                  onConfirm: () => _act(s, widget.api.confirmSwap, 'Отмечено'),
                );
              },
            ),
    );
  }
}

class _SwapCard extends StatelessWidget {
  const _SwapCard({
    required this.swap,
    required this.me,
    required this.busy,
    required this.onAccept,
    required this.onDecline,
    required this.onCancel,
    required this.onConfirm,
  });
  final Swap swap;
  final String me;
  final bool busy;
  final VoidCallback onAccept;
  final VoidCallback onDecline;
  final VoidCallback onCancel;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final iAmProposer = swap.userA == me;
    final partner = iAmProposer ? swap.nameB : swap.nameA;
    final iTeach = iAmProposer ? swap.skillA : swap.skillB;
    final theyTeach = iAmProposer ? swap.skillB : swap.skillA;
    final myDone = iAmProposer ? swap.aDone : swap.bDone;
    final partnerDone = iAmProposer ? swap.bDone : swap.aDone;

    final (statusText, statusColor) = switch (swap.status) {
      'proposed' => (
          iAmProposer ? 'Ждём ответа' : 'Новое предложение',
          theme.colorScheme.tertiaryContainer
        ),
      'accepted' => ('Идёт', theme.colorScheme.primaryContainer),
      'completed' => ('Завершён', theme.colorScheme.surfaceContainerHighest),
      _ => ('Отменён', theme.colorScheme.surfaceContainerHighest),
    };

    final List<Widget> actions = [];
    String? note;
    if (swap.status == 'proposed') {
      if (iAmProposer) {
        actions.add(TextButton(onPressed: onCancel, child: const Text('Отменить')));
      } else {
        actions.add(TextButton(onPressed: onDecline, child: const Text('Отклонить')));
        actions.add(FilledButton(onPressed: onAccept, child: const Text('Принять')));
      }
    } else if (swap.status == 'accepted') {
      actions.add(TextButton(onPressed: onCancel, child: const Text('Отменить')));
      if (!myDone) {
        actions.add(FilledButton(
            onPressed: onConfirm, child: const Text('Мы позанимались')));
      } else if (!partnerDone) {
        note = 'Вы подтвердили. Ждём подтверждения от $partner.';
      }
    }

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
            const SizedBox(height: 8),
            Text('Вы учите: $iTeach'),
            Text('Вас учат: $theyTeach'),
            if (note != null) ...[
              const SizedBox(height: 8),
              Text(note, style: theme.textTheme.bodySmall),
            ],
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 12),
              if (busy)
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
                  children: actions,
                ),
            ],
          ],
        ),
      ),
    );
  }
}
