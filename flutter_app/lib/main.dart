import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'services/backend_service.dart';
import 'services/tauri_bridge.dart';

// Shared visual tokens keep the monitoring surfaces consistent across views.
const kAccent = Color(0xffa98bff);
const kAccentBright = Color(0xffded5ff);
const kAccentDeep = Color(0xff7d5cff);
const kInk = Color(0xfffffaff);
const kMutedInk = Color(0xffd2c9df);
const kBackground = Color(0xff140d22);
const kBackgroundDeep = Color(0xff0d0918);
const kSurface = Color(0xff1f1534);
const kSurfaceElevated = Color(0xff2b1d46);
const kLine = Color(0x36ffffff);
const kAccentLine = Color(0x70ded5ff);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const FatigueMonitorApp());
}

class FatigueMonitorApp extends StatelessWidget {
  const FatigueMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    const ink = kInk;
    return MaterialApp(
      title: '疲勞監測操作台',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.transparent,
        colorScheme: ColorScheme.fromSeed(
          seedColor: kAccent,
          brightness: Brightness.dark,
          surface: kSurface,
        ),
        dividerColor: kLine,
        inputDecorationTheme: const InputDecorationTheme(
          enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: kLine)),
          focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: kAccentLine, width: 1.2)),
        ),
        fontFamily: 'Segoe UI',
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: ink, height: 1.35),
          titleMedium: TextStyle(color: ink, fontWeight: FontWeight.w700),
        ),
      ),
      home: const MonitorShell(),
    );
  }
}

class MonitorShell extends StatefulWidget {
  const MonitorShell({super.key});

  @override
  State<MonitorShell> createState() => _MonitorShellState();
}

class _MonitorShellState extends State<MonitorShell> {
  final _backend = BackendService();
  final _bridge = TauriBridge.instance;
  StreamSubscription<Map<String, dynamic>>? _metricsSubscription;
  StreamSubscription<String>? _frameSubscription;
  Timer? _statePoller;
  Map<String, dynamic> _metrics = <String, dynamic>{};
  Map<String, dynamic> _engineState = <String, dynamic>{};
  List<Map<String, dynamic>> _recordings = <Map<String, dynamic>>[];
  Map<String, dynamic>? _selectedRecording;
  List<Map<String, dynamic>> _playbackRows = <Map<String, dynamic>>[];
  bool _playbackBusy = false;
  Uint8List? _previewFrame;
  String? _error;
  bool _connected = false;
  bool _commandBusy = false;
  bool _alwaysOnTop = false;
  int _selectedSection = 0;

  @override
  void initState() {
    super.initState();
    _metricsSubscription = _backend.connectMetrics().listen(
      (packet) {
        if (!mounted) return;
        setState(() {
          _metrics = packet;
          _connected = true;
          _error = null;
        });
      },
      onError: (_) {
        if (mounted) setState(() => _connected = false);
      },
    );
    _frameSubscription = _backend.previewFrames.listen((frame) {
      try {
        final bytes = base64Decode(frame);
        if (mounted) setState(() => _previewFrame = bytes);
      } catch (_) {}
    });
    _refreshEngineState();
    _statePoller = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _refreshEngineState(silent: true),
    );
    _loadRecordings();
  }

  Future<void> _refreshEngineState({bool silent = false}) async {
    try {
      final state = await _backend.controlState();
      if (!mounted) return;
      setState(() {
        _engineState = state;
        _connected = true;
        if (!silent) _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _connected = false;
        if (!silent) _error = 'Python engine 尚未就緒：$error';
      });
    }
  }

  Future<void> _runCommand(
    String command, [
    Map<String, dynamic>? args,
  ]) async {
    if (_commandBusy) return;
    setState(() {
      _commandBusy = true;
      _error = null;
    });
    try {
      final state = await _backend.command(command, args);
      if (mounted) {
        setState(() => _engineState = state);
        final message = _commandSuccessMessage(command, args);
        if (message != null) _showCommandMessage(message);
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = '操作失敗：$error');
        _showCommandMessage('操作失敗：$error', isError: true);
      }
    } finally {
      if (mounted) setState(() => _commandBusy = false);
    }
  }

  String? _commandSuccessMessage(String command, Map<String, dynamic>? args) {
    if (command == 'settings.save') return '設定已儲存';
    if (command == 'baseline.start') return '已開始記錄清醒基線';
    if (command == 'monitor.layout') {
      return args?['focus'] == true ? '已切換為專注模式' : '已切換為分割模式';
    }
    if (command == 'settings.action') {
      return switch (args?['action']) {
        'recordings' => '已開啟記錄目錄',
        'hotkeys' => '快捷鍵設定已完成',
        'profile' => '使用者資料設定已完成',
        'alarm' => '警報器設定已完成',
        'web' => '已開啟 Web 儀表板',
        'web_lan' => 'Web 區域網設定已更新',
        _ => '操作已完成',
      };
    }
    return null;
  }

  void _showCommandMessage(String message, {bool isError = false}) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(message),
        duration: Duration(seconds: isError ? 4 : 2),
        backgroundColor: isError ? const Color(0xff8f3f4d) : kSurfaceElevated,
      ),
    );
  }

  Future<void> _loadRecordings() async {
    try {
      final values = await _backend.recordings();
      if (mounted) setState(() => _recordings = values);
    } catch (error) {
      if (mounted) setState(() => _error = '無法讀取回放資料：$error');
    }
  }

  Future<void> _openRecording(Map<String, dynamic> recording) async {
    final path = recording['path']?.toString();
    if (path == null || path.isEmpty) return;
    setState(() {
      _selectedRecording = recording;
      _playbackRows = <Map<String, dynamic>>[];
      _playbackBusy = true;
    });
    try {
      final payload = await _backend.playback(path, limit: 200);
      if (mounted) {
        setState(() {
          _playbackRows = (payload['data'] as List?)
                  ?.whereType<Map>()
                  .map((row) => Map<String, dynamic>.from(row))
                  .toList() ??
              <Map<String, dynamic>>[];
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = '無法讀取回放指標：$error');
    } finally {
      if (mounted) setState(() => _playbackBusy = false);
    }
  }

  @override
  void dispose() {
    _metricsSubscription?.cancel();
    _frameSubscription?.cancel();
    _statePoller?.cancel();
    unawaited(_backend.dispose());
    super.dispose();
  }

  Future<void> _windowAction(Future<void> Function() action) async {
    try {
      await action();
    } catch (_) {
      // Browser fallback keeps the UI usable when not hosted by Tauri.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: DecoratedBox(
        decoration: const BoxDecoration(
          color: kBackground,
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [kSurface, kBackgroundDeep],
          ),
        ),
        child: SafeArea(
          top: false,
          child: Column(
            children: [
              AppTitleBar(
                onDrag: () => _windowAction(_bridge.startDragging),
                onMinimize: () => _windowAction(_bridge.minimizeWindow),
                onMaximize: () => _windowAction(_bridge.toggleMaximizeWindow),
                onClose: () => _windowAction(_bridge.closeWindow),
              ),
              Expanded(
                child: Row(
                  children: [
                    NavigationRailPanel(
                      selectedIndex: _selectedSection,
                      onSelected: (value) => setState(() => _selectedSection = value),
                      alwaysOnTop: _alwaysOnTop,
                      onAlwaysOnTop: () async {
                        try {
                          final value = await _bridge.toggleAlwaysOnTop();
                          if (mounted) setState(() => _alwaysOnTop = value);
                        } catch (_) {}
                      },
                    ),
                    Expanded(child: _content()),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content() {
    if (_selectedSection == 1) {
      return ChestBeltView(
        metrics: _metrics,
        state: _engineState,
        busy: _commandBusy,
        onCommand: _runCommand,
      );
    }
    if (_selectedSection == 2) {
      return PlaybackView(
        recordings: _recordings,
        selected: _selectedRecording,
        rows: _playbackRows,
        busy: _playbackBusy,
        state: _engineState,
        onCommand: _runCommand,
        onRefresh: _loadRecordings,
        onOpen: _openRecording,
        onClose: () => setState(() => _selectedRecording = null),
      );
    }
    if (_selectedSection == 3) {
      return SettingsView(
        state: _engineState,
        busy: _commandBusy,
        onCommand: _runCommand,
      );
    }
    return DashboardView(
      metrics: _metrics,
      engineState: _engineState,
      previewFrame: _previewFrame,
      connected: _connected,
      busy: _commandBusy,
      error: _error,
      onRetry: _refreshEngineState,
      onCommand: _runCommand,
    );
  }
}

class AppTitleBar extends StatelessWidget {
  const AppTitleBar({required this.onDrag, required this.onMinimize, required this.onMaximize, required this.onClose, super.key});

  final VoidCallback onDrag;
  final VoidCallback onMinimize;
  final VoidCallback onMaximize;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.basic,
      child: GestureDetector(
        onPanDown: (_) => onDrag(),
        behavior: HitTestBehavior.opaque,
        child: Container(
          height: 56,
          padding: const EdgeInsets.only(left: 20, right: 10),
          decoration: BoxDecoration(
            color: kSurface.withValues(alpha: .84),
            border: const Border(bottom: BorderSide(color: kAccentLine)),
          ),
          child: Row(
            children: [
              Container(width: 28, height: 28, decoration: BoxDecoration(color: kAccent.withValues(alpha: .16), border: Border.all(color: kAccentLine), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.visibility_outlined, size: 17, color: kAccentBright)),
              const SizedBox(width: 12),
              const Text('疲勞監測操作台', style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: .2)),
              const SizedBox(width: 12),
              Text('NON-CONTACT / LIVE', style: TextStyle(fontSize: 10, color: Colors.white.withValues(alpha: .42), letterSpacing: 1.4)),
              const Spacer(),
              WindowButton(icon: Icons.remove, tooltip: '最小化', onPressed: onMinimize),
              WindowButton(icon: Icons.crop_square, tooltip: '最大化或還原', onPressed: onMaximize),
              WindowButton(icon: Icons.close, tooltip: '關閉', isClose: true, onPressed: onClose),
            ],
          ),
        ),
      ),
    );
  }
}

class WindowButton extends StatefulWidget {
  const WindowButton({required this.icon, required this.tooltip, required this.onPressed, this.isClose = false, super.key});
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  final bool isClose;

  @override
  State<WindowButton> createState() => _WindowButtonState();
}

class _WindowButtonState extends State<WindowButton> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: widget.tooltip,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          width: 42,
          height: 34,
          decoration: BoxDecoration(color: _hovered ? (widget.isClose ? const Color(0xffd35f63).withValues(alpha: .8) : kAccent.withValues(alpha: .14)) : Colors.transparent, border: _hovered && !widget.isClose ? Border.all(color: kAccentLine) : null, borderRadius: BorderRadius.circular(7)),
          child: IconButton(onPressed: widget.onPressed, icon: Icon(widget.icon, size: 16), splashRadius: 18),
        ),
      ),
    );
  }
}

class NavigationRailPanel extends StatelessWidget {
  const NavigationRailPanel({required this.selectedIndex, required this.onSelected, required this.alwaysOnTop, required this.onAlwaysOnTop, super.key});
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final bool alwaysOnTop;
  final VoidCallback onAlwaysOnTop;

  @override
  Widget build(BuildContext context) {
    const items = [
      (Icons.radar_outlined, '即時監測'),
      (Icons.favorite_outline, '心跳帶'),
      (Icons.history, '歷史回放'),
      (Icons.tune, '系統設定'),
    ];
    return Container(
      width: 222,
      padding: const EdgeInsets.fromLTRB(14, 20, 14, 16),
      decoration: const BoxDecoration(border: Border(right: BorderSide(color: kLine))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('CONTROL ROOM', style: TextStyle(fontSize: 10, letterSpacing: 1.8, color: Colors.white.withValues(alpha: .35))),
          const SizedBox(height: 16),
          for (var index = 0; index < items.length; index++) ...[
            _NavItem(icon: items[index].$1, label: items[index].$2, selected: selectedIndex == index, onTap: () => onSelected(index)),
            const SizedBox(height: 5),
          ],
          const Spacer(),
          InkWell(
            onTap: onAlwaysOnTop,
            borderRadius: BorderRadius.circular(8),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
              child: Row(children: [Icon(alwaysOnTop ? Icons.push_pin : Icons.push_pin_outlined, size: 17, color: alwaysOnTop ? kAccentBright : Colors.white54), const SizedBox(width: 10), Text('固定在最上層', style: TextStyle(fontSize: 12, color: alwaysOnTop ? kInk : Colors.white54))]),
            ),
          ),
          const SizedBox(height: 14),
          Text('ENGINE ONLINE', style: TextStyle(fontSize: 10, letterSpacing: 1.2, color: Colors.white.withValues(alpha: .3))),
          const SizedBox(height: 6),
          Row(children: [Container(width: 7, height: 7, decoration: const BoxDecoration(shape: BoxShape.circle, color: kAccent)), const SizedBox(width: 7), Text('Python backend', style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: .55)))]),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.icon, required this.label, required this.selected, required this.onTap});
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: selected ? kAccent.withValues(alpha: .14) : Colors.transparent,
        border: selected ? Border.all(color: kAccentLine) : null,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12), child: Row(children: [Icon(icon, size: 18, color: selected ? kAccentBright : Colors.white54), const SizedBox(width: 11), Text(label, style: TextStyle(fontSize: 13, fontWeight: selected ? FontWeight.w700 : FontWeight.w500, color: selected ? kInk : Colors.white60))])),
        ),
      ),
    );
  }
}

class DashboardView extends StatelessWidget {
  const DashboardView({
    required this.metrics,
    required this.engineState,
    required this.previewFrame,
    required this.connected,
    required this.busy,
    required this.error,
    required this.onRetry,
    required this.onCommand,
    super.key,
  });
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> engineState;
  final Uint8List? previewFrame;
  final bool connected;
  final bool busy;
  final String? error;
  final Future<void> Function() onRetry;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  double _number(String key, [double fallback = 0]) => (metrics[key] as num?)?.toDouble() ?? fallback;
  String _text(String key, [String fallback = '--']) => metrics[key]?.toString() ?? fallback;

  @override
  Widget build(BuildContext context) {
    final fatigue = _text('status', connected ? '等待資料' : '尚未連線');
    final fatigueColor = fatigue.contains('警') || fatigue.contains('疲') ? const Color(0xffe77b78) : kAccent;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(30, 26, 30, 34),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('即時監測', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)), const SizedBox(height: 7), Text('以臉部行為與 rPPG 訊號交叉檢視操作者狀態。', style: TextStyle(color: Colors.white.withValues(alpha: .5), fontSize: 13))])),
          _ConnectionPill(connected: connected),
        ]),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 16), child: _InlineNotice(message: error!, onRetry: onRetry)),
        const SizedBox(height: 24),
        IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Expanded(flex: 5, child: CameraPreview(frame: previewFrame, running: engineState['pipeline_running'] == true)),
            const SizedBox(width: 16),
            Expanded(
              flex: 3,
              child: DesktopControlPanel(
                state: engineState,
                busy: busy,
                onCommand: onCommand,
              ),
            ),
          ]),
        ),
        const SizedBox(height: 16),
        IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Expanded(flex: 5, child: _StatusPanel(status: fatigue, color: fatigueColor, metrics: metrics)),
            const SizedBox(width: 16),
            Expanded(flex: 3, child: _SignalPanel(bpm: _number('stress_bpm'), sqi: _number('stress_sqi'), fps: _number('fps'))),
          ]),
        ),
        const SizedBox(height: 16),
        HeartRateBeltPanel(metrics: metrics, engineState: engineState, busy: busy, onCommand: onCommand),
        const SizedBox(height: 16),
        Wrap(spacing: 12, runSpacing: 12, children: [
          MetricTile(label: '眼瞼閉合 EAR', value: _number('ear').toStringAsFixed(2), suffix: 'ratio', icon: Icons.remove_red_eye_outlined),
          MetricTile(label: 'PERCLOS', value: _number('perclos').toStringAsFixed(1), suffix: '%', icon: Icons.timer_outlined),
          MetricTile(label: '眨眼次數', value: _text('blink_count'), suffix: '次', icon: Icons.visibility_off_outlined),
          MetricTile(label: '頭部俯仰', value: _number('head_pitch').toStringAsFixed(1), suffix: 'deg', icon: Icons.threed_rotation),
        ]),
        const SizedBox(height: 24),
        Text('訊號品質', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        _QualityStrip(metrics: metrics),
      ]),
    );
  }
}

class CameraPreview extends StatelessWidget {
  const CameraPreview({required this.frame, required this.running, super.key});
  final Uint8List? frame;
  final bool running;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('LIVE CAMERA', style: TextStyle(color: Colors.white.withValues(alpha: .38), fontSize: 10, letterSpacing: 1.4)),
          const Spacer(),
          _ConnectionPill(connected: running),
        ]),
        const SizedBox(height: 14),
        AspectRatio(
          aspectRatio: 16 / 9,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: ColoredBox(
              color: kBackgroundDeep,
              child: frame == null
                  ? Center(child: Column(mainAxisSize: MainAxisSize.min, children: [Icon(running ? Icons.videocam_outlined : Icons.videocam_off_outlined, color: Colors.white24, size: 34), const SizedBox(height: 10), Text(running ? '等待影像串流' : '啟動管線後顯示即時畫面', style: TextStyle(color: Colors.white.withValues(alpha: .35), fontSize: 12))]))
                  : Image.memory(frame!, fit: BoxFit.contain, gaplessPlayback: true),
            ),
          ),
        ),
      ]),
    );
  }
}

class DesktopControlPanel extends StatelessWidget {
  const DesktopControlPanel({required this.state, required this.busy, required this.onCommand, super.key});
  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  @override
  Widget build(BuildContext context) {
    final running = state['pipeline_running'] == true;
    final recording = state['recording'] == true;
    final benchmark = state['benchmark_active'] == true;
    final focus = state['monitor_focus'] == true;
    final capturing = state['auto_capture_active'] == true;
    final autoDuration = (state['auto_capture_seconds'] as num?)?.toInt() ?? 60;
    final includeBelt = state['auto_capture_include_belt'] == true;
    final cameraRows = (state['cameras'] as List?)?.whereType<Map>().toList() ?? <Map>[];
    final cameraIndexes = cameraRows.map((row) => row['index']).whereType<int>().toSet();
    final selectedRaw = state['selected_camera_index'];
    final selected = selectedRaw is int && cameraIndexes.contains(selectedRaw) ? selectedRaw : null;
    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('SYSTEM CONTROL', style: TextStyle(color: Colors.white.withValues(alpha: .38), fontSize: 10, letterSpacing: 1.4)),
        const SizedBox(height: 14),
        DropdownButtonFormField<int>(
          initialValue: selected,
          decoration: const InputDecoration(labelText: '攝影機', border: OutlineInputBorder(), isDense: true),
          items: cameraRows.map((row) => DropdownMenuItem<int>(value: row['index'] as int, child: Text(row['label']?.toString() ?? 'Camera ${row['index']}'))).toList(),
          onChanged: busy || running ? null : (value) { if (value != null) onCommand('camera.select', <String, dynamic>{'index': value}); },
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: busy || (!running && selected == null) ? null : () => onCommand('pipeline.set', <String, dynamic>{'enabled': !running}),
          icon: Icon(running ? Icons.stop_circle_outlined : Icons.play_arrow),
          label: Text(running ? '停止監測' : '開始監測'),
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44), backgroundColor: running ? const Color(0xffb75255) : kAccentDeep),
        ),
        const SizedBox(height: 9),
        Row(children: [
          Expanded(child: OutlinedButton.icon(onPressed: busy || !running ? null : () => onCommand('benchmark.set', <String, dynamic>{'enabled': !benchmark}), icon: Icon(benchmark ? Icons.stop_circle_outlined : Icons.speed_outlined), label: Text(benchmark ? '停止基準測試' : 'DL 基準測試（120s）'))),
          const SizedBox(width: 8),
          Tooltip(message: '切換右側數值欄顯示', child: SegmentedButton<bool>(segments: const [ButtonSegment<bool>(value: false, label: Text('分割')), ButtonSegment<bool>(value: true, label: Text('專注'))], selected: <bool>{focus}, onSelectionChanged: busy ? null : (values) => onCommand('monitor.layout', <String, dynamic>{'focus': values.first}))),
        ]),
        const SizedBox(height: 9),
        OutlinedButton.icon(
          onPressed: busy || (!running && !recording) ? null : () => onCommand('recording.set', <String, dynamic>{'enabled': !recording}),
          icon: Icon(recording ? Icons.stop : Icons.fiber_manual_record, color: recording ? const Color(0xffe77b78) : null),
          label: Text(recording ? '停止記錄' : '開始記錄'),
        ),
        const SizedBox(height: 9),
        DropdownButtonFormField<int>(
          initialValue: <int>[30, 60, 120, 300, 600].contains(autoDuration) ? autoDuration : 60,
          decoration: const InputDecoration(labelText: '自動採集秒數', border: OutlineInputBorder(), isDense: true),
          items: const [30, 60, 120, 300, 600]
              .map((seconds) => DropdownMenuItem<int>(value: seconds, child: Text('$seconds 秒')))
              .toList(),
          onChanged: busy || capturing ? null : (value) {
            if (value != null) onCommand('auto_capture.configure', <String, dynamic>{'duration_seconds': value, 'include_belt': includeBelt});
          },
        ),
        SwitchListTile.adaptive(
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: const Text('同步心跳帶真值'),
          value: includeBelt,
          onChanged: busy || capturing ? null : (value) => onCommand('auto_capture.configure', <String, dynamic>{'duration_seconds': autoDuration, 'include_belt': value}),
        ),
        OutlinedButton.icon(
          onPressed: busy ? null : () => onCommand('auto_capture.set', <String, dynamic>{'enabled': !capturing, 'duration_seconds': autoDuration, 'include_belt': includeBelt}),
          icon: Icon(capturing ? Icons.timer_off_outlined : Icons.timer_outlined),
          label: Text(capturing ? '停止自動採集' : '自動採集'),
        ),
        const SizedBox(height: 8),
        TextButton.icon(onPressed: busy || running ? null : () => onCommand('camera.refresh'), icon: const Icon(Icons.refresh, size: 17), label: const Text('刷新攝影機')),
      ]),
    );
  }
}

class _ConnectionPill extends StatelessWidget {
  const _ConnectionPill({required this.connected});
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final color = connected ? kAccent : const Color(0xffe0a35d);
    return Container(padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7), decoration: BoxDecoration(color: color.withValues(alpha: .1), border: Border.all(color: color.withValues(alpha: .28)), borderRadius: BorderRadius.circular(20)), child: Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)), const SizedBox(width: 7), Text(connected ? '資料串流中' : '等待後端', style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700))]));
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({required this.status, required this.color, required this.metrics});
  final String status;
  final Color color;
  final Map<String, dynamic> metrics;

  @override
  Widget build(BuildContext context) {
    final calibrated = metrics['calibrated'] == true;
    return GlassPanel(
      child: Row(children: [
        SizedBox(width: 118, height: 118, child: CustomPaint(painter: StatusRingPainter(color: color, progress: calibrated ? .84 : .22), child: Center(child: Icon(calibrated ? Icons.shield_outlined : Icons.hourglass_top, color: color, size: 34)))),
        const SizedBox(width: 24),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [Text('CURRENT STATE', style: TextStyle(color: Colors.white.withValues(alpha: .38), fontSize: 10, letterSpacing: 1.5)), const SizedBox(height: 8), Text(status, style: TextStyle(color: color, fontSize: 26, fontWeight: FontWeight.w800)), const SizedBox(height: 9), Text(calibrated ? '臉部追蹤與個人基線已就緒' : '正在等待臉部與校準資料', style: TextStyle(color: Colors.white.withValues(alpha: .55), fontSize: 12))])),
      ]),
    );
  }
}

class _SignalPanel extends StatelessWidget {
  const _SignalPanel({required this.bpm, required this.sqi, required this.fps});
  final double bpm;
  final double sqi;
  final double fps;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('PHYSIOLOGY / rPPG', style: TextStyle(color: Colors.white.withValues(alpha: .38), fontSize: 10, letterSpacing: 1.4)),
          const Spacer(),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(bpm > 0 ? bpm.toStringAsFixed(0) : '--', style: const TextStyle(fontSize: 38, fontWeight: FontWeight.w800)),
            const SizedBox(width: 8),
            Padding(padding: const EdgeInsets.only(bottom: 7), child: Text('BPM', style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 12))),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            Text('SQI ${(sqi * 100).toStringAsFixed(0)}%', style: const TextStyle(color: kAccentBright, fontSize: 12)),
            const Spacer(),
            Text('${fps.toStringAsFixed(1)} FPS', style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 11)),
          ]),
        ],
      ),
    );
  }
}

class ChestBeltView extends StatelessWidget {
  const ChestBeltView({required this.metrics, required this.state, required this.busy, required this.onCommand, super.key});
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  String _text(String key, [String fallback = '--']) {
    final value = metrics[key]?.toString();
    return value == null || value.isEmpty ? fallback : value;
  }

  double _number(String key) => (metrics[key] as num?)?.toDouble() ?? 0;

  @override
  Widget build(BuildContext context) {
    final config = state['belt_config'] is Map ? Map<String, dynamic>.from(state['belt_config'] as Map) : <String, dynamic>{};
    final enabled = state['belt_calibration'] == true;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(30, 28, 30, 34),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('心跳帶設備', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)), const SizedBox(height: 7), Text('BLE 真值只用於 rPPG 校準與訊號檢視，不進入疲勞融合分數。', style: TextStyle(color: Colors.white.withValues(alpha: .5), fontSize: 13))])),
          _BeltStatusPill(label: enabled ? (_text('belt_state', 'idle') == 'connected' ? '已連線' : '啟動中') : '未啟用', color: enabled ? kAccent : const Color(0xffe0a35d)),
        ]),
        const SizedBox(height: 20),
        HeartRateBeltPanel(metrics: metrics, engineState: state, busy: busy, onCommand: onCommand),
        const SizedBox(height: 14),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: GlassPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('rPPG 校準 / CALIBRATION', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            _BeltDetailRow(label: 'Offset', value: '${_number('calib_offset_bpm').toStringAsFixed(1)} BPM'),
            _BeltDetailRow(label: '原始殘差', value: '${_number('calib_raw_residual_bpm').toStringAsFixed(1)} BPM'),
            _BeltDetailRow(label: '校正後殘差', value: '${_number('calib_residual_bpm').toStringAsFixed(1)} BPM'),
            _BeltDetailRow(label: '信心 / 狀態', value: '${_text('calib_confidence')} / ${metrics['calib_converged'] == true ? '已收斂' : '暖機中'}'),
            _BeltDetailRow(label: '配對數', value: _text('calib_pairs_used', '0')),
          ]))),
          const SizedBox(width: 14),
          Expanded(child: GlassPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('設備設定 / PREFERENCES', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            _BeltDetailRow(label: '名稱前綴', value: config['name_prefix']?.toString().isNotEmpty == true ? config['name_prefix'].toString() : '未指定'),
            _BeltDetailRow(label: '指定位址', value: config['address']?.toString().isNotEmpty == true ? config['address'].toString() : '自動掃描'),
            _BeltDetailRow(label: '參數自適應', value: config['rppg_param_tuning_enabled'] == true ? '開啟' : '關閉'),
            _BeltDetailRow(label: '同步錄製', value: config['capture_enabled'] == true ? '開啟' : '關閉'),
            const SizedBox(height: 8),
            Text('若要變更設備前綴、位址或同步錄製，請編輯 config/hr_belt.json 後重新啟動。', style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 11)),
          ]))),
        ]),
      ]),
    );
  }
}

class _BeltDetailRow extends StatelessWidget {
  const _BeltDetailRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.symmetric(vertical: 5), child: Row(children: [SizedBox(width: 94, child: Text(label, style: TextStyle(color: Colors.white.withValues(alpha: .48), fontSize: 11))), Expanded(child: Text(value, style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis))]));
}

class HeartRateBeltPanel extends StatelessWidget {
  const HeartRateBeltPanel({required this.metrics, required this.engineState, required this.busy, required this.onCommand, super.key});
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> engineState;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  double _number(String key, [double fallback = 0]) => (metrics[key] as num?)?.toDouble() ?? fallback;
  String _text(String key, [String fallback = '--']) {
    final value = metrics[key]?.toString();
    return value == null || value.isEmpty ? fallback : value;
  }

  @override
  Widget build(BuildContext context) {
    final calibrationEnabled = engineState['belt_calibration'] == true;
    final beltEnabled = metrics['belt_enabled'] == true || calibrationEnabled;
    final beltState = _text('belt_state', 'idle');
    final stale = metrics['belt_stale'] == true;
    final connected = beltState == 'connected' && !stale;
    final stateLabel = stale
        ? '訊號停滯'
        : switch (beltState) {
            'connected' => '已連線',
            'scanning' => '掃描裝置',
            'connecting' => '連線中',
            'reconnecting' => '重新連線',
            'error' => '連線錯誤',
            'stopped' => '已停止',
            _ => beltEnabled ? '等待裝置' : '未啟用',
          };
    final stateColor = stale || beltState == 'error'
        ? const Color(0xffe77b78)
        : connected
            ? kAccent
            : const Color(0xffe0a35d);
    final canEnable = engineState['pipeline_running'] == true && engineState['rppg_enabled'] == true;
    final contactSupported = metrics['belt_contact_supported'] == true;
    final contactDetected = metrics['belt_contact_detected'] == true;
    final contact = contactSupported ? (contactDetected ? '已接觸' : '未接觸') : '未提供';
    final battery = _number('belt_battery', -1);
    final rssi = _number('belt_rssi');
    final signalAge = _number('belt_signal_age_sec', -1);
    final connectedFor = _number('belt_connected_duration_sec', -1);
    final hrv = 'HRV  RMSSD ${_number('belt_hrv_rmssd') > 0 ? _number('belt_hrv_rmssd').toStringAsFixed(1) : '--'} ms   SDNN ${_number('belt_hrv_sdnn') > 0 ? _number('belt_hrv_sdnn').toStringAsFixed(1) : '--'} ms   LF/HF ${_number('belt_hrv_lf_hf') > 0 ? _number('belt_hrv_lf_hf').toStringAsFixed(2) : '--'}';

    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('HEART RATE BELT / BLE', style: TextStyle(color: Colors.white.withValues(alpha: .38), fontSize: 10, letterSpacing: 1.4)),
            const SizedBox(height: 7),
            Text(_text('belt_device_name', '未偵測到心跳帶'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Text('${_text('belt_device_address')}  ·  ${_text('belt_sensor_location', '位置未知')}', style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 11), overflow: TextOverflow.ellipsis),
          ])),
          _BeltStatusPill(label: stateLabel, color: stateColor),
        ]),
        const SizedBox(height: 18),
        Wrap(spacing: 10, runSpacing: 10, children: [
          _BeltReadout(label: '心率', value: _number('belt_bpm') > 0 ? _number('belt_bpm').toStringAsFixed(0) : '--', suffix: 'BPM', icon: Icons.favorite_outline, accent: stateColor),
          _BeltReadout(label: '擷取訊號', value: signalAge >= 0 ? signalAge.toStringAsFixed(1) : '--', suffix: '秒前', icon: Icons.graphic_eq_outlined, accent: connected ? kAccentBright : Colors.white38),
          _BeltReadout(label: '感測器接觸', value: contact, suffix: '', icon: Icons.sensors_outlined, accent: contact == '未接觸' ? const Color(0xffe77b78) : kAccentBright),
          _BeltReadout(label: '電量', value: battery >= 0 ? battery.toStringAsFixed(0) : '--', suffix: battery >= 0 ? '%' : '', icon: Icons.battery_5_bar_outlined, accent: kAccentBright),
          _BeltReadout(label: 'RSSI', value: rssi != 0 ? rssi.toStringAsFixed(0) : '--', suffix: 'dBm', icon: Icons.wifi_tethering_outlined, accent: kAccentBright),
          _BeltReadout(label: 'RR 樣本', value: _text('belt_rr_count', '0'), suffix: '筆', icon: Icons.timeline_outlined, accent: kAccentBright),
          _BeltReadout(label: '通知封包', value: _text('belt_notifications', '0'), suffix: '筆', icon: Icons.sync_alt_outlined, accent: kAccentBright),
          _BeltReadout(label: '連線時長', value: connectedFor >= 0 ? (connectedFor / 60).toStringAsFixed(1) : '--', suffix: '分鐘', icon: Icons.timer_outlined, accent: kAccentBright),
        ]),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: Text(hrv, style: TextStyle(color: Colors.white.withValues(alpha: .55), fontSize: 11), overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 12),
          FilledButton.tonalIcon(
            onPressed: busy || (!calibrationEnabled && !canEnable) ? null : () => onCommand('preferences.configure', <String, dynamic>{'belt_calibration': !calibrationEnabled}),
            icon: Icon(calibrationEnabled ? Icons.link_off_outlined : Icons.link_outlined, size: 17),
            label: Text(calibrationEnabled ? '停用心跳帶' : '啟用心跳帶'),
          ),
        ]),
        if (_text('belt_last_error', '').isNotEmpty) ...[
          const SizedBox(height: 9),
          Text('錯誤：${_text('belt_last_error')}', style: const TextStyle(color: Color(0xffe77b78), fontSize: 11), maxLines: 2, overflow: TextOverflow.ellipsis),
        ],
      ]),
    );
  }
}

class _BeltStatusPill extends StatelessWidget {
  const _BeltStatusPill({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7), decoration: BoxDecoration(color: color.withValues(alpha: .1), border: Border.all(color: color.withValues(alpha: .28)), borderRadius: BorderRadius.circular(20)), child: Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)), const SizedBox(width: 7), Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700))]));
}

class _BeltReadout extends StatelessWidget {
  const _BeltReadout({required this.label, required this.value, required this.suffix, required this.icon, required this.accent});
  final String label;
  final String value;
  final String suffix;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 152,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: const BoxDecoration(color: kBackgroundDeep, border: Border(top: BorderSide(color: kAccentLine), left: BorderSide(color: kLine), right: BorderSide(color: kLine), bottom: BorderSide(color: kLine))),
          child: Row(children: [
            Icon(icon, size: 17, color: accent),
            const SizedBox(width: 9),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 10), overflow: TextOverflow.ellipsis),
              const SizedBox(height: 4),
              Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Flexible(child: Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800), overflow: TextOverflow.ellipsis)),
                if (suffix.isNotEmpty) ...[const SizedBox(width: 4), Text(suffix, style: TextStyle(color: Colors.white.withValues(alpha: .35), fontSize: 9))],
              ]),
            ])),
          ]),
        ),
      );
}

class MetricTile extends StatefulWidget {
  const MetricTile({required this.label, required this.value, required this.suffix, required this.icon, super.key});
  final String label;
  final String value;
  final String suffix;
  final IconData icon;

  @override
  State<MetricTile> createState() => _MetricTileState();
}

class _MetricTileState extends State<MetricTile> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        width: 218,
        padding: const EdgeInsets.all(17),
        transform: Matrix4.translationValues(0, _hovered ? -3 : 0, 0),
        decoration: BoxDecoration(
          color: _hovered ? kSurfaceElevated : kSurface,
          border: Border.all(color: _hovered ? kAccentLine : kLine),
          borderRadius: BorderRadius.circular(10),
          boxShadow: _hovered ? [BoxShadow(color: kAccent.withValues(alpha: .1), blurRadius: 22)] : [],
        ),
        child: Row(children: [
          Icon(widget.icon, size: 20, color: kAccentBright),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(widget.label, style: TextStyle(color: Colors.white.withValues(alpha: .5), fontSize: 11)),
            const SizedBox(height: 6),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(widget.value, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
              const SizedBox(width: 5),
              Padding(padding: const EdgeInsets.only(bottom: 3), child: Text(widget.suffix, style: TextStyle(fontSize: 10, color: Colors.white.withValues(alpha: .35))),
              ),
            ]),
          ])),
        ]),
      ),
    );
  }
}

class _QualityStrip extends StatelessWidget {
  const _QualityStrip({required this.metrics});
  final Map<String, dynamic> metrics;

  @override
  Widget build(BuildContext context) {
    final items = <String, double>{'臉部追蹤': ((metrics['fatigue_quality_score'] as num?)?.toDouble() ?? 0), 'rPPG 訊號': ((metrics['stress_quality_score'] as num?)?.toDouble() ?? 0), 'ROI 穩定度': ((metrics['stress_roi_area_stability'] as num?)?.toDouble() ?? 0)};
    return GlassPanel(child: Column(children: items.entries.map((entry) => Padding(padding: const EdgeInsets.symmetric(vertical: 7), child: Row(children: [SizedBox(width: 85, child: Text(entry.key, style: TextStyle(color: Colors.white.withValues(alpha: .62), fontSize: 12))), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: entry.value.clamp(0, 1), minHeight: 7, backgroundColor: Colors.white.withValues(alpha: .07), color: kAccent))), const SizedBox(width: 12), SizedBox(width: 44, child: Text('${(entry.value * 100).toStringAsFixed(0)}%', textAlign: TextAlign.right, style: const TextStyle(color: kAccentBright, fontSize: 12)))]))).toList()));
  }
}

class PlaybackView extends StatelessWidget {
  const PlaybackView({required this.recordings, required this.selected, required this.rows, required this.busy, required this.state, required this.onCommand, required this.onRefresh, required this.onOpen, required this.onClose, super.key});
  final List<Map<String, dynamic>> recordings;
  final Map<String, dynamic>? selected;
  final List<Map<String, dynamic>> rows;
  final bool busy;
  final Map<String, dynamic> state;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;
  final Future<void> Function() onRefresh;
  final Future<void> Function(Map<String, dynamic>) onOpen;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(30, 28, 30, 30),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('歷史回放', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800))),
          IconButton(onPressed: onRefresh, tooltip: '重新整理', icon: const Icon(Icons.refresh)),
        ]),
        const SizedBox(height: 7),
        Text('選擇一段錄影檢視完整指標與事件時間線。', style: TextStyle(color: Colors.white.withValues(alpha: .5), fontSize: 13)),
        const SizedBox(height: 24),
        _ReplayControlPanel(state: state, busy: busy, onCommand: onCommand),
        const SizedBox(height: 16),
        Expanded(
          child: selected == null
              ? (recordings.isEmpty
                  ? const EmptyState(icon: Icons.inbox_outlined, title: '尚無回放資料', message: '啟動一次監測工作階段後，錄影與指標會出現在這裡。')
                  : ListView.separated(
                      itemCount: recordings.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 9),
                      itemBuilder: (_, index) {
                        final item = recordings[index];
                        return GlassPanel(
                          child: ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.movie_outlined, color: kAccentBright),
                            title: Text(item['session_name']?.toString() ?? '未命名工作階段'),
                            subtitle: Text('${item['duration_str'] ?? '--'}  •  ${item['record_count'] ?? 0} 筆指標', style: TextStyle(color: Colors.white.withValues(alpha: .45))),
                            trailing: const Icon(Icons.chevron_right, color: Colors.white38),
                            onTap: () => onOpen(item),
                          ),
                        );
                      },
                    ))
              : _PlaybackDetail(recording: selected!, rows: rows, busy: busy, onClose: onClose),
        ),
      ]),
    );
  }
}

class _ReplayControlPanel extends StatefulWidget {
  const _ReplayControlPanel({required this.state, required this.busy, required this.onCommand});
  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  @override
  State<_ReplayControlPanel> createState() => _ReplayControlPanelState();
}

class _ReplayControlPanelState extends State<_ReplayControlPanel> {
  late final TextEditingController _pathController;
  late final FocusNode _pathFocusNode;

  @override
  void initState() {
    super.initState();
    _pathController = TextEditingController(text: widget.state['replay_dataset_dir']?.toString() ?? '');
    _pathFocusNode = FocusNode();
  }

  @override
  void didUpdateWidget(covariant _ReplayControlPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    final path = widget.state['replay_dataset_dir']?.toString() ?? '';
    if (_pathController.text != path && !_pathFocusNode.hasFocus) {
      _pathController.text = path;
    }
  }

  @override
  void dispose() {
    _pathController.dispose();
    _pathFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final running = widget.state['replay_running'] == true;
    final stopping = widget.state['replay_stopping'] == true;
    final jobs = (widget.state['replay_jobs'] as num?)?.toInt() ?? 2;
    final annotated = widget.state['replay_annotated'] == true;
    final total = (widget.state['replay_total'] as num?)?.toInt() ?? 0;
    final done = (widget.state['replay_done'] as num?)?.toInt() ?? 0;
    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('批次回測控制', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          const Spacer(),
          if (running) Text('$done / ${total > 0 ? total : '--'}', style: const TextStyle(color: kAccentBright, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: TextField(controller: _pathController, focusNode: _pathFocusNode, enabled: !running && !widget.busy, decoration: const InputDecoration(labelText: '影片資料夾', hintText: '輸入資料夾路徑', border: OutlineInputBorder(), isDense: true))),
          const SizedBox(width: 9),
          IconButton(onPressed: running || widget.busy ? null : () => widget.onCommand('replay.choose'), tooltip: '選擇資料夾', icon: const Icon(Icons.folder_open_outlined)),
          IconButton(onPressed: running || widget.busy ? null : () => widget.onCommand('replay.configure', <String, dynamic>{'path': _pathController.text}), tooltip: '套用路徑', icon: const Icon(Icons.check_circle_outline)),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          const Text('平行數'),
          const SizedBox(width: 10),
          DropdownButton<int>(value: <int>[1, 2, 3, 4].contains(jobs) ? jobs : 2, items: const [1, 2, 3, 4].map((value) => DropdownMenuItem<int>(value: value, child: Text('$value'))).toList(), onChanged: running || widget.busy ? null : (value) { if (value != null) widget.onCommand('replay.configure', <String, dynamic>{'jobs': value}); }),
          const SizedBox(width: 20),
          Expanded(child: SwitchListTile.adaptive(contentPadding: EdgeInsets.zero, dense: true, title: const Text('輸出標註影片'), value: annotated, onChanged: running || widget.busy ? null : (value) => widget.onCommand('replay.configure', <String, dynamic>{'annotated': value}))),
        ]),
        Row(children: [
          FilledButton.icon(onPressed: running || widget.busy ? null : () => widget.onCommand('replay.set', <String, dynamic>{'enabled': true, 'mode': 'single'}), icon: const Icon(Icons.play_arrow), label: const Text('開始批次')),
          const SizedBox(width: 9),
          OutlinedButton.icon(onPressed: running || widget.busy ? null : () => widget.onCommand('replay.set', <String, dynamic>{'enabled': true, 'mode': 'parallel'}), icon: const Icon(Icons.speed_outlined), label: const Text('平行驗證')),
          const SizedBox(width: 9),
          OutlinedButton.icon(onPressed: !running || stopping || widget.busy ? null : () => widget.onCommand('replay.set', <String, dynamic>{'enabled': false}), icon: const Icon(Icons.stop), label: Text(stopping ? '停止中' : '停止')),
        ]),
        const SizedBox(height: 9),
        Text(widget.state['replay_current']?.toString() ?? '目前影片：--', style: TextStyle(color: Colors.white.withValues(alpha: .55), fontSize: 11)),
        if ((widget.state['replay_parallel_status']?.toString() ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(widget.state['replay_parallel_status'].toString(), style: TextStyle(color: Colors.white.withValues(alpha: .42), fontSize: 10), maxLines: 2, overflow: TextOverflow.ellipsis)),
        if ((widget.state['replay_result']?.toString() ?? '').isNotEmpty && widget.state['replay_result'] != '摘要檔：--') Padding(padding: const EdgeInsets.only(top: 5), child: Text(widget.state['replay_result'].toString(), style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 10), maxLines: 3, overflow: TextOverflow.ellipsis)),
      ]),
    );
  }
}

class _PlaybackDetail extends StatelessWidget {
  const _PlaybackDetail({required this.recording, required this.rows, required this.busy, required this.onClose});
  final Map<String, dynamic> recording;
  final List<Map<String, dynamic>> rows;
  final bool busy;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        IconButton(onPressed: onClose, tooltip: '返回回放清單', icon: const Icon(Icons.arrow_back)),
        Expanded(child: Text(recording['session_name']?.toString() ?? '回放指標', style: Theme.of(context).textTheme.titleLarge)),
        Text('${recording['duration_str'] ?? '--'}  /  ${recording['record_count'] ?? 0} 筆', style: TextStyle(color: Colors.white.withValues(alpha: .5))),
      ]),
      const SizedBox(height: 12),
      if (busy) const LinearProgressIndicator(minHeight: 2),
      const SizedBox(height: 12),
      Expanded(
        child: rows.isEmpty && !busy
            ? const EmptyState(icon: Icons.query_stats, title: '沒有可顯示的指標', message: '這段錄影尚未產生可用的 metrics 資料。')
            : ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const SizedBox(height: 8),
                itemBuilder: (_, index) {
                  final row = rows[index];
                  return GlassPanel(
                    child: Row(children: [
                      SizedBox(width: 90, child: Text('${((row['timestamp'] as num?)?.toDouble() ?? 0).toStringAsFixed(1)} s', style: TextStyle(color: Colors.white.withValues(alpha: .5)))),
                      Expanded(child: Text('狀態 ${row['status'] ?? '--'}  •  EAR ${((row['ear'] as num?)?.toDouble() ?? 0).toStringAsFixed(2)}  •  BPM ${((row['bpm'] as num?)?.toDouble() ?? 0).toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600))),
                      Text('PERCLOS ${(((row['perclos'] as num?)?.toDouble() ?? 0) * 100).toStringAsFixed(1)}%', style: TextStyle(color: Colors.white.withValues(alpha: .55))),
                    ]),
                  );
                },
              ),
      ),
    ]);
  }
}

class SettingsView extends StatelessWidget {
  const SettingsView({required this.state, required this.busy, required this.onCommand, super.key});

  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  @override
  Widget build(BuildContext context) {
    final running = state['pipeline_running'] == true;
    final opacity = (state['overlay_opacity'] as num?)?.toDouble() ?? 55;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(30, 28, 30, 30),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('系統設定', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 7),
        Text('設定由 Flutter 主面板送往 Python engine，分析中可安全熱切換的項目會立即生效。', style: TextStyle(color: Colors.white.withValues(alpha: .5), fontSize: 13)),
        const SizedBox(height: 24),
        GlassPanel(child: Column(children: [
          _SettingSwitch(
            title: '行為警覺分析',
            subtitle: '頭部姿態、眨眼、哈欠、注視與疲勞融合',
            value: state['behavior_enabled'] == true,
            enabled: !busy && (state['rppg_enabled'] == true || state['behavior_enabled'] != true),
            onChanged: (value) => onCommand('analysis.configure', <String, dynamic>{'behavior_enabled': value}),
          ),
          const Divider(color: Colors.white12),
          _SettingSwitch(
            title: 'rPPG / HRV 分析',
            subtitle: '非接觸式心率、HRV 與訊號品質',
            value: state['rppg_enabled'] == true,
            enabled: !busy && (state['behavior_enabled'] == true || state['rppg_enabled'] != true),
            onChanged: (value) => onCommand('analysis.configure', <String, dynamic>{'rppg_enabled': value}),
          ),
          const Divider(color: Colors.white12),
          _SettingSwitch(title: '啟動時自動記錄', subtitle: '監測管線啟動後同步建立指標與影片記錄', value: state['auto_record'] == true, enabled: !busy, onChanged: (value) => onCommand('preferences.configure', <String, dynamic>{'auto_record': value})),
          const Divider(color: Colors.white12),
          _SettingSwitch(title: '心跳帶真值校準', subtitle: '僅校正 rPPG，不直接改變疲勞融合權重', value: state['belt_calibration'] == true, enabled: !busy, onChanged: (value) => onCommand('preferences.configure', <String, dynamic>{'belt_calibration': value})),
        ])),
        const SizedBox(height: 14),
        GlassPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('攝影機擷取', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          Row(children: [
            Expanded(child: _SettingDropdown(label: '解析度', value: state['resolution']?.toString(), values: const ['640×480', '800×600', '1280×720（720p）', '1280×800', '1920×1080（1080p）'], enabled: !busy && !running, onChanged: (value) => onCommand('camera.configure', <String, dynamic>{'resolution': value}))),
            const SizedBox(width: 12),
            Expanded(child: _SettingDropdown(label: '目標 FPS', value: state['fps']?.toString(), values: const ['15', '24', '30', '60'], enabled: !busy && !running, onChanged: (value) => onCommand('camera.configure', <String, dynamic>{'fps': value}))),
          ]),
          const SizedBox(height: 4),
          _SettingDropdown(label: '影像後端', value: state['backend']?.toString(), values: const ['ffmpeg'], enabled: !busy && !running, onChanged: (value) => onCommand('camera.configure', <String, dynamic>{'backend': value})),
          const SizedBox(height: 4),
          _SettingSwitch(title: '水平翻轉', subtitle: '修正鏡像攝影機方向', value: state['horizontal_flip'] == true, enabled: !busy && !running, onChanged: (value) => onCommand('camera.configure', <String, dynamic>{'horizontal_flip': value})),
        ])),
        const SizedBox(height: 14),
        GlassPanel(child: Column(children: [
          _SettingSwitch(title: '全部 Overlay', subtitle: '同步顯示或隱藏鏡頭與數值 Overlay', value: state['overlay_all'] == true, enabled: !busy, onChanged: (value) => onCommand('overlay.configure', <String, dynamic>{'all': value})),
          const Divider(color: Colors.white12),
          _SettingSwitch(title: '桌面鏡頭 Overlay', subtitle: '在 Tauri 視窗外顯示即時鏡頭疊圖', value: state['overlay_preview'] == true, enabled: !busy, onChanged: (value) => onCommand('preferences.configure', <String, dynamic>{'overlay_preview': value})),
          const Divider(color: Colors.white12),
          _SettingSwitch(title: '桌面數值 Overlay', subtitle: '顯示疲勞與生理訊號即時指標', value: state['overlay_metrics'] == true, enabled: !busy, onChanged: (value) => onCommand('preferences.configure', <String, dynamic>{'overlay_metrics': value})),
          const Divider(color: Colors.white12),
          _SettingSwitch(title: 'Overlay 點擊穿透', subtitle: '鎖定後不攔截桌面滑鼠操作', value: state['overlay_locked'] == true, enabled: !busy, onChanged: (value) => onCommand('preferences.configure', <String, dynamic>{'overlay_locked': value})),
          const SizedBox(height: 6),
          _OverlayOpacityControl(
            value: opacity,
            enabled: !busy,
            onChanged: (value) => onCommand('overlay.configure', <String, dynamic>{'opacity': value}),
          ),
        ])),
        const SizedBox(height: 18),
        Wrap(spacing: 10, runSpacing: 10, children: [
          FilledButton.icon(onPressed: busy ? null : () => onCommand('settings.save'), icon: const Icon(Icons.save_outlined), label: const Text('儲存設定')),
          OutlinedButton.icon(onPressed: busy || !running ? null : () => onCommand('baseline.start'), icon: const Icon(Icons.person_search_outlined), label: const Text('記錄清醒基線')),
          OutlinedButton.icon(onPressed: busy ? null : () => onCommand('settings.action', <String, dynamic>{'action': 'recordings'}), icon: const Icon(Icons.folder_open_outlined), label: const Text('開啟記錄目錄')),
          OutlinedButton.icon(onPressed: busy ? null : () => onCommand('settings.action', <String, dynamic>{'action': 'hotkeys'}), icon: const Icon(Icons.keyboard_outlined), label: const Text('快捷鍵')),
          OutlinedButton.icon(onPressed: busy ? null : () => onCommand('settings.action', <String, dynamic>{'action': 'profile'}), icon: const Icon(Icons.badge_outlined), label: const Text('使用者資料')),
          OutlinedButton.icon(onPressed: busy ? null : () => onCommand('settings.action', <String, dynamic>{'action': 'alarm'}), icon: const Icon(Icons.notifications_active_outlined), label: const Text('警報器')),
          OutlinedButton.icon(onPressed: busy ? null : () => onCommand('settings.action', <String, dynamic>{'action': 'web'}), icon: const Icon(Icons.open_in_browser_outlined), label: const Text('Web 儀表板')),
        ]),
        const SizedBox(height: 10),
        _SettingSwitch(title: '允許區域網存取 Web 儀表板', subtitle: '僅在受信任網路啟用未加密 LAN 廣播', value: state['web_allow_lan'] == true, enabled: !busy, onChanged: (value) => onCommand('settings.action', <String, dynamic>{'action': 'web_lan', 'enabled': value})),
        if (running) Padding(padding: const EdgeInsets.only(top: 14), child: Text('監測運作中：攝影機解析度、FPS 與 backend 需停止管線後調整。', style: TextStyle(color: const Color(0xffe0a35d).withValues(alpha: .9), fontSize: 12))),
      ]),
    );
  }
}

class _OverlayOpacityControl extends StatefulWidget {
  const _OverlayOpacityControl({required this.value, required this.enabled, required this.onChanged});

  final double value;
  final bool enabled;
  final ValueChanged<int> onChanged;

  @override
  State<_OverlayOpacityControl> createState() => _OverlayOpacityControlState();
}

class _OverlayOpacityControlState extends State<_OverlayOpacityControl> {
  late double _value;
  bool _dragging = false;

  @override
  void initState() {
    super.initState();
    _value = widget.value.clamp(0, 100).toDouble();
  }

  @override
  void didUpdateWidget(covariant _OverlayOpacityControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_dragging && oldWidget.value != widget.value) {
      _value = widget.value.clamp(0, 100).toDouble();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      const SizedBox(width: 102, child: Text('透明度', style: TextStyle(fontSize: 12))),
      Expanded(
        child: Slider(
          value: _value,
          min: 0,
          max: 100,
          divisions: 100,
          label: '${_value.toStringAsFixed(0)}%',
          onChangeStart: widget.enabled ? (_) => _dragging = true : null,
          onChanged: widget.enabled ? (value) => setState(() => _value = value) : null,
          onChangeEnd: widget.enabled
              ? (value) {
                  _dragging = false;
                  setState(() => _value = value);
                  widget.onChanged(value.round());
                }
              : null,
        ),
      ),
      SizedBox(width: 42, child: Text('${_value.toStringAsFixed(0)}%', textAlign: TextAlign.right)),
    ]);
  }
}

class _SettingDropdown extends StatelessWidget {
  const _SettingDropdown({required this.label, required this.value, required this.values, required this.enabled, required this.onChanged});
  final String label;
  final String? value;
  final List<String> values;
  final bool enabled;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final selected = value != null && values.contains(value) ? value : null;
    return DropdownButtonFormField<String>(
      initialValue: selected,
      decoration: InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true),
      items: values.map((item) => DropdownMenuItem<String>(value: item, child: Text(item))).toList(),
      onChanged: enabled ? (item) { if (item != null) onChanged(item); } : null,
    );
  }
}

class _SettingSwitch extends StatelessWidget {
  const _SettingSwitch({required this.title, required this.subtitle, required this.value, required this.enabled, required this.onChanged});
  final String title;
  final String subtitle;
  final bool value;
  final bool enabled;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
      subtitle: Text(subtitle, style: TextStyle(color: Colors.white.withValues(alpha: .42), fontSize: 11)),
      value: value,
      onChanged: enabled ? onChanged : null,
    );
  }
}

class GlassPanel extends StatelessWidget {
  const GlassPanel({required this.child, super.key});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(12);
    return Material(
      color: kSurface.withValues(alpha: .92),
      shape: RoundedRectangleBorder(borderRadius: radius, side: const BorderSide(color: kLine)),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Padding(padding: const EdgeInsets.all(20), child: child),
          const Positioned(
            top: 0,
            left: 12,
            right: 12,
            child: SizedBox(height: 1, child: ColoredBox(color: kAccentLine)),
          ),
        ],
      ),
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.message, required this.onRetry});
  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11), decoration: BoxDecoration(color: const Color(0xffb46d4d).withValues(alpha: .12), border: Border.all(color: const Color(0xffb46d4d).withValues(alpha: .35)), borderRadius: BorderRadius.circular(9)), child: Row(children: [const Icon(Icons.info_outline, size: 17, color: Color(0xffe0a35d)), const SizedBox(width: 10), Expanded(child: Text(message, style: const TextStyle(fontSize: 12))), TextButton(onPressed: onRetry, child: const Text('重試'))]));
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({required this.icon, required this.title, required this.message, super.key});
  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) => Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(icon, size: 42, color: Colors.white24), const SizedBox(height: 14), Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)), const SizedBox(height: 7), Text(message, textAlign: TextAlign.center, style: TextStyle(color: Colors.white.withValues(alpha: .45), fontSize: 12))]));
}

class StatusRingPainter extends CustomPainter {
  StatusRingPainter({required this.color, required this.progress});
  final Color color;
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide / 2 - 8;
    final base = Paint()..style = PaintingStyle.stroke..strokeWidth = 7..color = Colors.white.withValues(alpha: .08);
    final arc = Paint()..style = PaintingStyle.stroke..strokeCap = StrokeCap.round..strokeWidth = 7..color = color;
    canvas.drawCircle(center, radius, base);
    canvas.drawArc(Rect.fromCircle(center: center, radius: radius), -1.57, 6.28 * progress, false, arc);
  }

  @override
  bool shouldRepaint(covariant StatusRingPainter oldDelegate) => oldDelegate.progress != progress || oldDelegate.color != color;
}
