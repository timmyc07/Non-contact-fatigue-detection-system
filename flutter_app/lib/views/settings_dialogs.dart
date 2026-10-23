part of '../main.dart';

Future<void> _confirmSettingsReset(
  BuildContext context,
  List<String> sections,
  Future<void> Function(String, [Map<String, dynamic>?]) onCommand,
) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      scrollable: true,
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      title: const Text('確認重設'),
      content: Text(sections.length == 1 ? '確定要重設這個設定區段嗎？' : '確定要重設所有設定區段嗎？'),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消')),
        FilledButton.icon(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            icon: const Icon(Icons.restore),
            label: const Text('確認重設')),
      ],
    ),
  );
  if (confirmed == true) {
    await onCommand('settings.reset', <String, dynamic>{'sections': sections});
  }
}

const _alarmScenarioLabels = <String, String>{
  'low_vigilance': '低警覺',
  'drowsy': '嗜睡',
  'critical': '高度疲勞',
  'microsleep': '微睡眠',
};

Map<String, dynamic> _alarmDraft(dynamic raw) {
  final source =
      raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
  final rawScenarios = source['scenarios'];
  final scenarios = <String, dynamic>{};
  for (final key in _alarmScenarioLabels.keys) {
    final value = rawScenarios is Map && rawScenarios[key] is Map
        ? Map<String, dynamic>.from(rawScenarios[key] as Map)
        : <String, dynamic>{};
    scenarios[key] = <String, dynamic>{
      'enabled': value['enabled'] == true,
      'sound_path': value['sound_path']?.toString() ?? ''
    };
  }
  return <String, dynamic>{
    'enabled': source['enabled'] == true,
    'volume': (source['volume'] as num?)?.toInt() ?? 70,
    'trigger_delay_sec':
        (source['trigger_delay_sec'] as num?)?.toDouble() ?? 1.0,
    'repeat_interval_sec':
        (source['repeat_interval_sec'] as num?)?.toDouble() ?? 20.0,
    'repeat_while_critical': source['repeat_while_critical'] == true,
    'use_builtin_fallback': source['use_builtin_fallback'] != false,
    'scenarios': scenarios,
  };
}

Future<void> _showAlarmDialog(BuildContext context, Map<String, dynamic> state,
    Future<void> Function(String, [Map<String, dynamic>?]) onCommand) async {
  final result = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _AlarmDialog(
        initial: _alarmDraft(state['alarm']),
        onTest: (scenario, alarm) => onCommand('alarm.test',
            <String, dynamic>{'scenario': scenario, 'alarm': alarm})),
  );
  if (result != null) {
    await onCommand('alarm.configure', <String, dynamic>{'alarm': result});
  }
}

class _AlarmDialog extends StatefulWidget {
  const _AlarmDialog({required this.initial, required this.onTest});
  final Map<String, dynamic> initial;
  final Future<void> Function(String, Map<String, dynamic>) onTest;
  @override
  State<_AlarmDialog> createState() => _AlarmDialogState();
}

class _AlarmDialogState extends State<_AlarmDialog> {
  late bool _enabled;
  late bool _repeatWhileCritical;
  late bool _useBuiltinFallback;
  late int _volume;
  late final TextEditingController _delayController;
  late final TextEditingController _repeatController;
  late final Map<String, bool> _scenarioEnabled;
  late final Map<String, TextEditingController> _scenarioPaths;
  String? _error;

  @override
  void initState() {
    super.initState();
    _enabled = widget.initial['enabled'] == true;
    _repeatWhileCritical = widget.initial['repeat_while_critical'] == true;
    _useBuiltinFallback = widget.initial['use_builtin_fallback'] == true;
    _volume = (widget.initial['volume'] as num?)?.toInt() ?? 70;
    _delayController = TextEditingController(
        text: '${widget.initial['trigger_delay_sec'] ?? 1.0}');
    _repeatController = TextEditingController(
        text: '${widget.initial['repeat_interval_sec'] ?? 20.0}');
    _scenarioEnabled = <String, bool>{};
    _scenarioPaths = <String, TextEditingController>{};
    final scenarios = widget.initial['scenarios'] as Map? ?? const {};
    for (final key in _alarmScenarioLabels.keys) {
      final scenario = scenarios[key] is Map ? scenarios[key] as Map : const {};
      _scenarioEnabled[key] = scenario['enabled'] == true;
      _scenarioPaths[key] =
          TextEditingController(text: scenario['sound_path']?.toString() ?? '');
    }
  }

  @override
  void dispose() {
    _delayController.dispose();
    _repeatController.dispose();
    for (final controller in _scenarioPaths.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Map<String, dynamic>? _payload() {
    final delay = double.tryParse(_delayController.text.trim());
    final repeat = double.tryParse(_repeatController.text.trim());
    if (_volume < 0 || _volume > 100) {
      _error = '音量需介於 0 到 100';
      return null;
    }
    if (delay == null || !delay.isFinite || delay < 0 || delay > 10) {
      _error = '觸發延遲需介於 0 到 10 秒';
      return null;
    }
    if (repeat == null || !repeat.isFinite || repeat < 5 || repeat > 120) {
      _error = '重複間隔需介於 5 到 120 秒';
      return null;
    }
    return <String, dynamic>{
      'enabled': _enabled,
      'volume': _volume,
      'trigger_delay_sec': delay,
      'repeat_interval_sec': repeat,
      'repeat_while_critical': _repeatWhileCritical,
      'use_builtin_fallback': _useBuiltinFallback,
      'scenarios': <String, dynamic>{
        for (final key in _alarmScenarioLabels.keys)
          key: <String, dynamic>{
            'enabled': _scenarioEnabled[key] == true,
            'sound_path': _scenarioPaths[key]!.text.trim()
          }
      },
    };
  }

  void _submit() {
    final payload = _payload();
    if (payload == null) {
      setState(() {});
      return;
    }
    Navigator.of(context).pop(payload);
  }

  Future<void> _testScenario(String scenario) async {
    final payload = _payload();
    if (payload == null) {
      setState(() {});
      return;
    }
    await widget.onTest(scenario, payload);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      title: const Text('警報器'),
      content: SizedBox(
        width: 640,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('啟用警報'),
              value: _enabled,
              onChanged: (value) => setState(() => _enabled = value)),
          Wrap(spacing: 12, children: [
            const Text('音量'),
            Text('$_volume%', style: const TextStyle(color: kMutedInk)),
          ]),
          Slider(
              value: _volume.toDouble(),
              min: 0,
              max: 100,
              divisions: 100,
              label: '$_volume%',
              onChanged: (value) => setState(() => _volume = value.round())),
          TextField(
              key: const ValueKey('alarm-delay'),
              controller: _delayController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '觸發延遲',
                  suffixText: '秒',
                  border: OutlineInputBorder(),
                  isDense: true)),
          const SizedBox(height: 10),
          TextField(
              key: const ValueKey('alarm-repeat'),
              controller: _repeatController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '重複間隔',
                  suffixText: '秒',
                  border: OutlineInputBorder(),
                  isDense: true)),
          SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('危急狀態持續重複'),
              value: _repeatWhileCritical,
              onChanged: (value) =>
                  setState(() => _repeatWhileCritical = value)),
          SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('找不到音效時使用內建音效'),
              value: _useBuiltinFallback,
              onChanged: (value) =>
                  setState(() => _useBuiltinFallback = value)),
          const Divider(),
          const Text('警報情境', style: TextStyle(fontWeight: FontWeight.w700)),
          for (final entry in _alarmScenarioLabels.entries)
            Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Column(children: [
                  Row(children: [
                    Expanded(child: Text(entry.value)),
                    Semantics(
                        label: '${entry.value}警報',
                        child: Switch(
                            value: _scenarioEnabled[entry.key] == true,
                            onChanged: (value) => setState(
                                () => _scenarioEnabled[entry.key] = value))),
                    IconButton(
                        onPressed: () => _testScenario(entry.key),
                        tooltip: '測試 ${entry.key}',
                        icon: const Icon(Icons.volume_up_outlined)),
                  ]),
                  const SizedBox(height: 6),
                  TextField(
                      controller: _scenarioPaths[entry.key],
                      decoration: InputDecoration(
                          labelText: '${entry.value}音效路徑',
                          border: const OutlineInputBorder(),
                          isDense: true)),
                ])),
          if (_error != null)
            Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(_error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error))),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消')),
        FilledButton.icon(
            onPressed: _submit,
            icon: const Icon(Icons.check),
            label: const Text('套用警報設定'))
      ],
    );
  }
}

const _hotkeyFields = <String, String>{
  'toggle_metrics': '切換數值 Overlay',
  'toggle_preview': '切換鏡頭 Overlay',
  'start_stop': '開始或停止監測',
  'lock_overlay': '鎖定 Overlay',
  'toggle_all': '切換全部 Overlay',
  'toggle_recording': '切換錄影',
};

Future<void> _showHotkeysDialog(
  BuildContext context,
  Map<String, dynamic> state,
  Future<void> Function(String, [Map<String, dynamic>?]) onCommand,
) async {
  final raw = state['hotkeys'];
  final initial = raw is Map
      ? Map<String, String>.from(raw.map(
          (key, value) => MapEntry(key.toString(), value?.toString() ?? '')))
      : <String, String>{};
  final hotkeys = await showDialog<Map<String, String>>(
    context: context,
    builder: (_) => _HotkeysDialog(initial: initial),
  );
  if (hotkeys != null) {
    await onCommand('hotkeys.configure', <String, dynamic>{'hotkeys': hotkeys});
  }
}

Future<void> _showUserProfileDialog(
  BuildContext context,
  Map<String, dynamic> state,
  Future<void> Function(String, [Map<String, dynamic>?]) onCommand,
) async {
  final raw = state['user_profile'];
  final profile =
      raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
  final values = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _UserProfileDialog(initial: profile),
  );
  if (values != null) {
    await onCommand(
        'user_profile.configure', <String, dynamic>{'user_profile': values});
  }
}

class _UserProfileDialog extends StatefulWidget {
  const _UserProfileDialog({required this.initial});
  final Map<String, dynamic> initial;

  @override
  State<_UserProfileDialog> createState() => _UserProfileDialogState();
}

class _UserProfileDialogState extends State<_UserProfileDialog> {
  late final TextEditingController _ageController;
  late final TextEditingController _heightController;
  late final TextEditingController _weightController;
  String? _error;

  @override
  void initState() {
    super.initState();
    _ageController =
        TextEditingController(text: '${widget.initial['age'] ?? 28}');
    _heightController =
        TextEditingController(text: '${widget.initial['height_cm'] ?? 170}');
    _weightController =
        TextEditingController(text: '${widget.initial['weight_kg'] ?? 65.0}');
    for (final controller in [
      _ageController,
      _heightController,
      _weightController
    ]) {
      controller.addListener(_refresh);
    }
  }

  @override
  void dispose() {
    _ageController.dispose();
    _heightController.dispose();
    _weightController.dispose();
    super.dispose();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  double? get _bmi {
    final height = double.tryParse(_heightController.text);
    final weight = double.tryParse(_weightController.text);
    if (height == null || weight == null || height <= 0) return null;
    return weight / ((height / 100) * (height / 100));
  }

  void _submit() {
    final age = int.tryParse(_ageController.text.trim());
    final height = int.tryParse(_heightController.text.trim());
    final weight = double.tryParse(_weightController.text.trim());
    if (age == null || age < 0 || age > 110) {
      setState(() => _error = '年齡需介於 0 到 110');
      return;
    }
    if (height == null || height < 100 || height > 220) {
      setState(() => _error = '身高需介於 100 到 220 公分');
      return;
    }
    if (weight == null || !weight.isFinite || weight < 30 || weight > 200) {
      setState(() => _error = '體重需介於 30 到 200 公斤');
      return;
    }
    Navigator.of(context).pop(<String, dynamic>{
      'age': age,
      'height_cm': height,
      'weight_kg': weight
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      title: const Text('使用者資料'),
      content: SizedBox(
        width: 460,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: _ageController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: '年齡',
                  suffixText: '歲',
                  border: OutlineInputBorder(),
                  isDense: true)),
          const SizedBox(height: 10),
          TextField(
              controller: _heightController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: '身高',
                  suffixText: '公分',
                  border: OutlineInputBorder(),
                  isDense: true)),
          const SizedBox(height: 10),
          TextField(
              controller: _weightController,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '體重',
                  suffixText: '公斤',
                  border: OutlineInputBorder(),
                  isDense: true)),
          const SizedBox(height: 12),
          Align(
              alignment: Alignment.centerLeft,
              child: Text(
                  _bmi == null ? 'BMI --' : 'BMI ${_bmi!.toStringAsFixed(1)}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, color: kAccentBright))),
          if (_error != null)
            Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(_error!,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error)))),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消')),
        FilledButton.icon(
            onPressed: _submit,
            icon: const Icon(Icons.check),
            label: const Text('套用使用者資料')),
      ],
    );
  }
}

class _HotkeysDialog extends StatefulWidget {
  const _HotkeysDialog({required this.initial});
  final Map<String, String> initial;

  @override
  State<_HotkeysDialog> createState() => _HotkeysDialogState();
}

class _HotkeysDialogState extends State<_HotkeysDialog> {
  late final Map<String, TextEditingController> _controllers;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controllers = {
      for (final entry in _hotkeyFields.entries)
        entry.key: TextEditingController(text: widget.initial[entry.key] ?? ''),
    };
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void _submit() {
    if (_controllers.values.any((controller) => controller.text.length > 64)) {
      setState(() => _error = '每個快捷鍵最多 64 個字元');
      return;
    }
    Navigator.of(context).pop(<String, String>{
      for (final key in _hotkeyFields.keys) key: _controllers[key]!.text.trim(),
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      title: const Text('快捷鍵設定'),
      content: SizedBox(
        width: 560,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final entry in _hotkeyFields.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: TextField(
                  controller: _controllers[entry.key],
                  decoration: InputDecoration(
                      labelText: entry.value,
                      hintText: '例如 Ctrl+Alt+O',
                      border: const OutlineInputBorder(),
                      isDense: true),
                ),
              ),
            if (_error != null)
              Align(
                  alignment: Alignment.centerLeft,
                  child: Text(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error))),
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消')),
        FilledButton.icon(
            onPressed: _submit,
            icon: const Icon(Icons.check),
            label: const Text('套用快捷鍵')),
      ],
    );
  }
}
