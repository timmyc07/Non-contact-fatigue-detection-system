import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'services/backend_service.dart';
import 'services/tauri_bridge.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const FatigueMonitorApp());
}

class FatigueMonitorApp extends StatelessWidget {
  const FatigueMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    const ink = Color(0xffe7edf2);
    return MaterialApp(
      title: '疲勞監測操作台',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.transparent,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff58c6a9),
          brightness: Brightness.dark,
          surface: const Color(0xff10171b),
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
  Map<String, dynamic> _metrics = <String, dynamic>{};
  List<Map<String, dynamic>> _recordings = <Map<String, dynamic>>[];
  String? _error;
  bool _connected = false;
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
    _loadRecordings();
  }

  Future<void> _loadRecordings() async {
    try {
      final values = await _backend.recordings();
      if (mounted) setState(() => _recordings = values);
    } catch (error) {
      if (mounted) setState(() => _error = '無法讀取回放資料：$error');
    }
  }

  @override
  void dispose() {
    _metricsSubscription?.cancel();
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
          color: Color(0xff0a0f13),
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xff111a1e), Color(0xff080c0f)],
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
    if (_selectedSection == 1) return PlaybackView(recordings: _recordings, onRefresh: _loadRecordings);
    if (_selectedSection == 2) return const SettingsView();
    return DashboardView(
      metrics: _metrics,
      connected: _connected,
      error: _error,
      onRetry: _loadRecordings,
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
        onPanStart: (_) => onDrag(),
        behavior: HitTestBehavior.opaque,
        child: Container(
          height: 56,
          padding: const EdgeInsets.only(left: 20, right: 10),
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(.25),
            border: Border(bottom: BorderSide(color: Colors.white.withOpacity(.08))),
          ),
          child: Row(
            children: [
              Container(width: 28, height: 28, decoration: BoxDecoration(color: const Color(0xff58c6a9).withOpacity(.16), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.visibility_outlined, size: 17, color: Color(0xff73ddbf))),
              const SizedBox(width: 12),
              const Text('疲勞監測操作台', style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: .2)),
              const SizedBox(width: 12),
              Text('NON-CONTACT / LIVE', style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(.42), letterSpacing: 1.4)),
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
          decoration: BoxDecoration(color: _hovered ? (widget.isClose ? const Color(0xffd35f63).withOpacity(.8) : Colors.white.withOpacity(.1)) : Colors.transparent, borderRadius: BorderRadius.circular(7)),
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
      (Icons.history, '歷史回放'),
      (Icons.tune, '系統設定'),
    ];
    return Container(
      width: 222,
      padding: const EdgeInsets.fromLTRB(14, 20, 14, 16),
      decoration: BoxDecoration(border: Border(right: BorderSide(color: Colors.white.withOpacity(.07)))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('CONTROL ROOM', style: TextStyle(fontSize: 10, letterSpacing: 1.8, color: Colors.white.withOpacity(.35))),
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
              child: Row(children: [Icon(alwaysOnTop ? Icons.push_pin : Icons.push_pin_outlined, size: 17, color: alwaysOnTop ? const Color(0xff58c6a9) : Colors.white54), const SizedBox(width: 10), Text('固定在最上層', style: TextStyle(fontSize: 12, color: alwaysOnTop ? Colors.white : Colors.white54))]),
            ),
          ),
          const SizedBox(height: 14),
          Text('ENGINE ONLINE', style: TextStyle(fontSize: 10, letterSpacing: 1.2, color: Colors.white.withOpacity(.3))),
          const SizedBox(height: 6),
          Row(children: [Container(width: 7, height: 7, decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xff58c6a9))), const SizedBox(width: 7), Text('Python backend', style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(.55)))]),
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
    return Material(
      color: selected ? const Color(0xff58c6a9).withOpacity(.14) : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12), child: Row(children: [Icon(icon, size: 18, color: selected ? const Color(0xff73ddbf) : Colors.white54), const SizedBox(width: 11), Text(label, style: TextStyle(fontSize: 13, fontWeight: selected ? FontWeight.w700 : FontWeight.w500, color: selected ? Colors.white : Colors.white60))])),
      ),
    );
  }
}

class DashboardView extends StatelessWidget {
  const DashboardView({required this.metrics, required this.connected, required this.error, required this.onRetry, super.key});
  final Map<String, dynamic> metrics;
  final bool connected;
  final String? error;
  final Future<void> Function() onRetry;

  double _number(String key, [double fallback = 0]) => (metrics[key] as num?)?.toDouble() ?? fallback;
  String _text(String key, [String fallback = '--']) => metrics[key]?.toString() ?? fallback;

  @override
  Widget build(BuildContext context) {
    final fatigue = _text('status', connected ? '等待資料' : '尚未連線');
    final fatigueColor = fatigue.contains('警') || fatigue.contains('疲') ? const Color(0xffe77b78) : const Color(0xff58c6a9);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(30, 26, 30, 34),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('即時監測', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)), const SizedBox(height: 7), Text('以臉部行為與 rPPG 訊號交叉檢視操作者狀態。', style: TextStyle(color: Colors.white.withOpacity(.5), fontSize: 13))])),
          _ConnectionPill(connected: connected),
        ]),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 16), child: _InlineNotice(message: error!, onRetry: onRetry)),
        const SizedBox(height: 24),
        Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Expanded(flex: 5, child: _StatusPanel(status: fatigue, color: fatigueColor, metrics: metrics)),
          const SizedBox(width: 16),
          Expanded(flex: 3, child: _SignalPanel(bpm: _number('stress_bpm'), sqi: _number('stress_sqi'), fps: _number('fps'))),
        ]),
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

class _ConnectionPill extends StatelessWidget {
  const _ConnectionPill({required this.connected});
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final color = connected ? const Color(0xff58c6a9) : const Color(0xffe0a35d);
    return Container(padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7), decoration: BoxDecoration(color: color.withOpacity(.1), border: Border.all(color: color.withOpacity(.28)), borderRadius: BorderRadius.circular(20)), child: Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)), const SizedBox(width: 7), Text(connected ? '資料串流中' : '等待後端', style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700))]));
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
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [Text('CURRENT STATE', style: TextStyle(color: Colors.white.withOpacity(.38), fontSize: 10, letterSpacing: 1.5)), const SizedBox(height: 8), Text(status, style: TextStyle(color: color, fontSize: 26, fontWeight: FontWeight.w800)), const SizedBox(height: 9), Text(calibrated ? '臉部追蹤與個人基線已就緒' : '正在等待臉部與校準資料', style: TextStyle(color: Colors.white.withOpacity(.55), fontSize: 12))])),
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
    return GlassPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('PHYSIOLOGY / rPPG', style: TextStyle(color: Colors.white.withOpacity(.38), fontSize: 10, letterSpacing: 1.4)), const Spacer(), Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Text(bpm > 0 ? bpm.toStringAsFixed(0) : '--', style: const TextStyle(fontSize: 38, fontWeight: FontWeight.w800)), const SizedBox(width: 8), Padding(padding: const EdgeInsets.only(bottom: 7), child: Text('BPM', style: TextStyle(color: Colors.white.withOpacity(.45), fontSize: 12)))]), const SizedBox(height: 10), Row(children: [Text('SQI ${(sqi * 100).toStringAsFixed(0)}%', style: const TextStyle(color: Color(0xff73ddbf), fontSize: 12)), const Spacer(), Text('${fps.toStringAsFixed(1)} FPS', style: TextStyle(color: Colors.white.withOpacity(.45), fontSize: 11))])])));
  }
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
    return MouseRegion(onEnter: (_) => setState(() => _hovered = true), onExit: (_) => setState(() => _hovered = false), child: AnimatedContainer(duration: const Duration(milliseconds: 160), width: 218, padding: const EdgeInsets.all(17), transform: Matrix4.translationValues(0, _hovered ? -3 : 0, 0), decoration: BoxDecoration(color: _hovered ? const Color(0xff1a282b) : const Color(0xff121b1f), border: Border.all(color: _hovered ? const Color(0xff58c6a9).withOpacity(.45) : Colors.white.withOpacity(.07)), borderRadius: BorderRadius.circular(10), boxShadow: _hovered ? [BoxShadow(color: const Color(0xff58c6a9).withOpacity(.1), blurRadius: 22)] : []), child: Row(children: [Icon(widget.icon, size: 20, color: const Color(0xff73ddbf)), const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(widget.label, style: TextStyle(color: Colors.white.withOpacity(.5), fontSize: 11)), const SizedBox(height: 6), Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Text(widget.value, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)), const SizedBox(width: 5), Padding(padding: const EdgeInsets.only(bottom: 3), child: Text(widget.suffix, style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(.35)))])]))]));
  }
}

class _QualityStrip extends StatelessWidget {
  const _QualityStrip({required this.metrics});
  final Map<String, dynamic> metrics;

  @override
  Widget build(BuildContext context) {
    final items = <String, double>{'臉部追蹤': ((metrics['fatigue_quality_score'] as num?)?.toDouble() ?? 0), 'rPPG 訊號': ((metrics['stress_quality_score'] as num?)?.toDouble() ?? 0), 'ROI 穩定度': ((metrics['stress_roi_area_stability'] as num?)?.toDouble() ?? 0)};
    return GlassPanel(child: Column(children: items.entries.map((entry) => Padding(padding: const EdgeInsets.symmetric(vertical: 7), child: Row(children: [SizedBox(width: 85, child: Text(entry.key, style: TextStyle(color: Colors.white.withOpacity(.62), fontSize: 12))), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: entry.value.clamp(0, 1), minHeight: 7, backgroundColor: Colors.white.withOpacity(.07), color: const Color(0xff58c6a9)))), const SizedBox(width: 12), SizedBox(width: 44, child: Text('${(entry.value * 100).toStringAsFixed(0)}%', textAlign: TextAlign.right, style: const TextStyle(color: Color(0xff73ddbf), fontSize: 12)))]))).toList()));
  }
}

class PlaybackView extends StatelessWidget {
  const PlaybackView({required this.recordings, required this.onRefresh, super.key});
  final List<Map<String, dynamic>> recordings;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    return Padding(padding: const EdgeInsets.fromLTRB(30, 28, 30, 30), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [Expanded(child: Text('歷史回放', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800))), IconButton(onPressed: onRefresh, tooltip: '重新整理', icon: const Icon(Icons.refresh))]), const SizedBox(height: 7), Text('選擇一段錄影檢視完整指標與事件時間線。', style: TextStyle(color: Colors.white.withOpacity(.5), fontSize: 13)), const SizedBox(height: 24), Expanded(child: recordings.isEmpty ? const EmptyState(icon: Icons.inbox_outlined, title: '尚無回放資料', message: '啟動一次監測工作階段後，錄影與指標會出現在這裡。') : ListView.separated(itemCount: recordings.length, separatorBuilder: (_, __) => const SizedBox(height: 9), itemBuilder: (_, index) { final item = recordings[index]; return GlassPanel(child: ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.movie_outlined, color: Color(0xff73ddbf)), title: Text(item['session_name']?.toString() ?? '未命名工作階段'), subtitle: Text('${item['duration_str'] ?? '--'}  •  ${item['record_count'] ?? 0} 筆指標', style: TextStyle(color: Colors.white.withOpacity(.45))), trailing: const Icon(Icons.chevron_right, color: Colors.white38))); }))]));
  }
}

class SettingsView extends StatelessWidget {
  const SettingsView({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(padding: const EdgeInsets.fromLTRB(30, 28, 30, 30), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('系統設定', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)), const SizedBox(height: 7), Text('演算法與裝置設定仍由 Python 主程式管理。', style: TextStyle(color: Colors.white.withOpacity(.5), fontSize: 13)), const SizedBox(height: 24), GlassPanel(child: Column(children: const [ListTile(contentPadding: EdgeInsets.zero, leading: Icon(Icons.memory_outlined, color: Color(0xff73ddbf)), title: Text('分析引擎'), subtitle: Text('MediaPipe Face Landmarker + rPPG')), Divider(color: Colors.white12), ListTile(contentPadding: EdgeInsets.zero, leading: Icon(Icons.wifi_tethering, color: Color(0xff73ddbf)), title: Text('資料服務'), subtitle: Text('本機 Flask / Socket.IO，預設 127.0.0.1:5000'))]))]));
  }
}

class GlassPanel extends StatelessWidget {
  const GlassPanel({required this.child, super.key});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(12);
    return ClipRRect(
      borderRadius: radius,
      child: BackdropFilter(
        filter: ui.ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(.045),
            border: Border.all(color: Colors.white.withOpacity(.09)),
            borderRadius: radius,
          ),
          child: child,
        ),
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
    return Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11), decoration: BoxDecoration(color: const Color(0xffb46d4d).withOpacity(.12), border: Border.all(color: const Color(0xffb46d4d).withOpacity(.35)), borderRadius: BorderRadius.circular(9)), child: Row(children: [const Icon(Icons.info_outline, size: 17, color: Color(0xffe0a35d)), const SizedBox(width: 10), Expanded(child: Text(message, style: const TextStyle(fontSize: 12))), TextButton(onPressed: onRetry, child: const Text('重試'))]));
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({required this.icon, required this.title, required this.message, super.key});
  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) => Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(icon, size: 42, color: Colors.white24), const SizedBox(height: 14), Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)), const SizedBox(height: 7), Text(message, textAlign: TextAlign.center, style: TextStyle(color: Colors.white.withOpacity(.45), fontSize: 12))]));
}

class StatusRingPainter extends CustomPainter {
  StatusRingPainter({required this.color, required this.progress});
  final Color color;
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide / 2 - 8;
    final base = Paint()..style = PaintingStyle.stroke..strokeWidth = 7..color = Colors.white.withOpacity(.08);
    final arc = Paint()..style = PaintingStyle.stroke..strokeCap = StrokeCap.round..strokeWidth = 7..color = color;
    canvas.drawCircle(center, radius, base);
    canvas.drawArc(Rect.fromCircle(center: center, radius: radius), -1.57, 6.28 * progress, false, arc);
  }

  @override
  bool shouldRepaint(covariant StatusRingPainter oldDelegate) => oldDelegate.progress != progress || oldDelegate.color != color;
}
