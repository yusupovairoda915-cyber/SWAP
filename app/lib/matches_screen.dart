import 'package:flutter/material.dart';

import 'api.dart';

class MatchesScreen extends StatefulWidget {
  const MatchesScreen({super.key, required this.api});
  final SwapApi api;

  @override
  State<MatchesScreen> createState() => _MatchesScreenState();
}

class _MatchesScreenState extends State<MatchesScreen> {
  List<SwapMatch> _matches = [];
  bool _loading = true;
  String? _error;

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
      final m = await widget.api.matches();
      if (!mounted) return;
      setState(() {
        _matches = m;
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

  Future<void> _propose(SwapMatch m) async {
    // Simplest rule for now: first skill of each side. Add a picker later.
    final mine = m.iTeach.first;
    final theirs = m.theyTeach.first.skill;
    try {
      await widget.api.proposeSwap(m.userId, mine, theirs);
      _toast('Предложение отправлено: вы учите «$mine», ${m.name} учит «$theirs»');
    } catch (e) {
      _toast(e.toString());
    }
  }

  Future<void> _book(SwapMatch m, TeachSkill s) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Записаться на урок?'),
        content: Text(
          '${m.name} научит вас: ${s.skill}\n'
          'Цена: ${s.price} кр за час.\n\n'
          'Кредиты заморозятся и перейдут учителю, когда вы подтвердите, что урок прошёл.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Отмена')),
          FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text('Записаться за ${s.price} кр')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.bookLesson(m.userId, s.skill, 1);
      _toast('Вы записались. Детали на вкладке «Кошелёк».');
    } catch (e) {
      _toast(friendlyError(e));
    }
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
      child: _matches.isEmpty
          ? ListView(
              // ListView so pull-to-refresh also works on the empty screen
              children: const [
                SizedBox(height: 120),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 32),
                  child: Text(
                    'Пока никого нет. Добавьте в профиле, что вы умеете и что хотите выучить, и потяните экран вниз, чтобы обновить.',
                    textAlign: TextAlign.center,
                  ),
                ),
              ],
            )
          : ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: _matches.length,
              itemBuilder: (_, i) => _MatchCard(
                match: _matches[i],
                onPropose: () => _propose(_matches[i]),
                onBook: (s) => _book(_matches[i], s),
              ),
            ),
    );
  }
}

class _MatchCard extends StatelessWidget {
  const _MatchCard({
    required this.match,
    required this.onPropose,
    required this.onBook,
  });
  final SwapMatch match;
  final VoidCallback onPropose;
  final void Function(TeachSkill) onBook;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    match.city.isEmpty
                        ? match.name
                        : '${match.name} · ${match.city}',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                if (match.mutual)
                  Chip(
                    label: const Text('Обмен без кредитов'),
                    backgroundColor: theme.colorScheme.primaryContainer,
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
            const SizedBox(height: 8),
            if (match.theyTeach.isNotEmpty)
              Text(
                'Научит вас: ${match.theyTeach.map((s) => '${s.skill} (${s.price} кр/час)').join(', ')}',
              ),
            if (match.iTeach.isNotEmpty)
              Text('Хочет выучить у вас: ${match.iTeach.join(', ')}'),
            if (!match.mutual && match.theyTeach.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final s in match.theyTeach)
                    OutlinedButton(
                      onPressed: () => onBook(s),
                      child: Text('${s.skill} · ${s.price} кр'),
                    ),
                ],
              ),
            ],
            if (match.mutual) ...[
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton(
                  onPressed: onPropose,
                  child: const Text('Предложить обмен'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
