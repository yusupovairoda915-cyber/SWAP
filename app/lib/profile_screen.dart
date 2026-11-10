import 'package:flutter/material.dart';

import 'api.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.api});
  final SwapApi api;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _name = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();

  Profile? _profile; // null = not created yet
  bool _loading = true;
  bool _saving = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
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
      _loadError = null;
    });
    try {
      final p = await widget.api.getProfile();
      if (!mounted) return;
      setState(() {
        _profile = p;
        if (p != null) {
          _name.text = p.name;
          _city.text = p.city;
          _bio.text = p.bio;
        }
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      _toast('Введите имя');
      return;
    }
    setState(() => _saving = true);
    try {
      final p = await widget.api
          .saveProfile(_name.text.trim(), _city.text.trim(), _bio.text.trim());
      if (!mounted) return;
      setState(() => _profile = p);
      _toast('Профиль сохранён');
    } catch (e) {
      _toast(e.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _addSkill() async {
    final result = await showDialog<_NewSkill>(
      context: context,
      builder: (_) => const _AddSkillDialog(),
    );
    if (result == null) return;
    try {
      await widget.api.addSkill(result.skill, result.kind, result.price);
      await _reloadSkills();
    } catch (e) {
      _toast(e.toString());
    }
  }

  Future<void> _removeSkill(String skill, String kind) async {
    try {
      await widget.api.removeSkill(skill, kind);
      await _reloadSkills();
    } catch (e) {
      _toast(e.toString());
    }
  }

  Future<void> _reloadSkills() async {
    final p = await widget.api.getProfile();
    if (mounted) setState(() => _profile = p);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_loadError!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('Повторить')),
            ],
          ),
        ),
      );
    }

    final p = _profile;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _name,
          maxLength: 60,
          decoration: const InputDecoration(
              labelText: 'Имя', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _city,
          maxLength: 60,
          decoration: const InputDecoration(
              labelText: 'Город', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _bio,
          maxLength: 500,
          maxLines: 3,
          decoration: const InputDecoration(
              labelText: 'О себе', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 8),
        FilledButton(
          onPressed: _saving ? null : _save,
          child: Text(_saving ? 'Сохраняю...' : 'Сохранить профиль'),
        ),
        const SizedBox(height: 24),
        if (p == null)
          const Text('Сохраните профиль, чтобы добавить навыки.')
        else ...[
          _SkillsSection(
            title: 'Могу научить',
            chips: [
              for (final s in p.teach)
                InputChip(
                  label: Text('${s.skill} · ${s.price} кр/час'),
                  onDeleted: () => _removeSkill(s.skill, 'teach'),
                ),
            ],
            emptyText: 'Пока пусто. Добавьте, чему вы можете научить.',
          ),
          const SizedBox(height: 16),
          _SkillsSection(
            title: 'Хочу выучить',
            chips: [
              for (final s in p.learn)
                InputChip(
                  label: Text(s),
                  onDeleted: () => _removeSkill(s, 'learn'),
                ),
            ],
            emptyText: 'Пока пусто. Добавьте, что хотите выучить.',
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _addSkill,
            icon: const Icon(Icons.add),
            label: const Text('Добавить навык'),
          ),
        ],
      ],
    );
  }
}

class _SkillsSection extends StatelessWidget {
  const _SkillsSection({
    required this.title,
    required this.chips,
    required this.emptyText,
  });
  final String title;
  final List<Widget> chips;
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (chips.isEmpty)
          Text(emptyText, style: Theme.of(context).textTheme.bodySmall)
        else
          Wrap(spacing: 8, runSpacing: 8, children: chips),
      ],
    );
  }
}

class _NewSkill {
  _NewSkill(this.skill, this.kind, this.price);
  final String skill;
  final String kind; // 'teach' or 'learn'
  final int? price;
}

class _AddSkillDialog extends StatefulWidget {
  const _AddSkillDialog();

  @override
  State<_AddSkillDialog> createState() => _AddSkillDialogState();
}

class _AddSkillDialogState extends State<_AddSkillDialog> {
  final _skill = TextEditingController();
  final _price = TextEditingController(text: '1');
  String _kind = 'teach';
  String? _error;

  @override
  void dispose() {
    _skill.dispose();
    _price.dispose();
    super.dispose();
  }

  void _submit() {
    final skill = _skill.text.trim();
    if (skill.isEmpty) {
      setState(() => _error = 'Введите название навыка');
      return;
    }
    int? price;
    if (_kind == 'teach') {
      price = int.tryParse(_price.text.trim());
      if (price == null || price < 1 || price > 100) {
        setState(() => _error = 'Цена: целое число от 1 до 100');
        return;
      }
    }
    Navigator.of(context).pop(_NewSkill(skill, _kind, price));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Новый навык'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'teach', label: Text('Учу')),
                ButtonSegment(value: 'learn', label: Text('Хочу выучить')),
              ],
              selected: {_kind},
              onSelectionChanged: (s) => setState(() {
                _kind = s.first;
                _error = null;
              }),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _skill,
              maxLength: 50,
              decoration: const InputDecoration(
                  labelText: 'Навык (например, Python)',
                  border: OutlineInputBorder()),
            ),
            if (_kind == 'teach') ...[
              const SizedBox(height: 8),
              TextField(
                controller: _price,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: 'Цена, кредитов за час',
                    border: OutlineInputBorder()),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Отмена')),
        FilledButton(onPressed: _submit, child: const Text('Добавить')),
      ],
    );
  }
}
