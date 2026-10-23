import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'models/platform_contract.dart';
import 'services/backend_service.dart';
import 'services/tauri_bridge.dart';
import 'widgets/live_preview.dart';

part 'views/settings_view.dart';
part 'views/playback_view.dart';
part 'widgets/panel_layout.dart';
part 'views/belt_view.dart';
part 'views/settings_dialogs.dart';

// 面板共用色票，警示狀態仍沿用既有嚴重度對應。
const kAccent = Color(0xff65d6bc);
const kAccentBright = Color(0xffb1ecde);
const kAccentDeep = Color(0xff206d60);
const kInk = Color(0xffedf2f7);
const kMutedInk = Color(0xffa7b4c5);
const kBackground = Color(0xff0c111b);
const kBackgroundDeep = Color(0xff080c14);
const kSurface = Color(0xff141d2b);
const kSurfaceElevated = Color(0xff1c293b);
const kLine = Color(0xff2a374a);
const kAccentLine = Color(0xff42695f);

(String, Color) fatiguePresentation(Map<String, dynamic> metrics,
    {String fallback = '--'}) {
  final status = metrics['status']?.toString() ?? '';
  final fusion = metrics['fusion_state_zh']?.toString().trim() ?? '';
  final waiting = status == 'CALIBRATING' ||
      (status == 'NO_FACE' && metrics['behavior_enabled'] != false);
  final urgent =
      status == 'MICROSLEEP' || (status == 'CRITICAL' && fusion != '極度危險');
  final value = !waiting && !urgent && fusion.isNotEmpty ? fusion : status;
  return switch (value) {
    'OK' || '清醒' => ('清醒', kAccent),
    'LOW_VIGILANCE' || '輕度疲勞' => ('輕度疲勞', const Color(0xffe9c46a)),
    'DROWSY' || '中度疲勞' => ('中度疲勞', const Color(0xfff4a261)),
    'CRITICAL' || '高度疲勞' => ('高度疲勞', const Color(0xffe77b78)),
    'MICROSLEEP' || '極度危險' => ('極度危險', const Color(0xffef5350)),
    'NO_FACE' => ('未偵測到臉部', kMutedInk),
    'CALIBRATING' => ('校準中', kMutedInk),
    _ => (value.isEmpty ? fallback : value, kAccent),
  };
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const FatigueMonitorApp());
}

class FatigueMonitorApp extends StatelessWidget {
  const FatigueMonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    const ink = kInk;
    final capabilities = currentPlatformCapabilities(
      isWeb: kIsWeb,
      isAndroid: defaultTargetPlatform == TargetPlatform.android,
      isIos: defaultTargetPlatform == TargetPlatform.iOS,
      isWindows: defaultTargetPlatform == TargetPlatform.windows,
      isMacos: defaultTargetPlatform == TargetPlatform.macOS,
      isLinux: defaultTargetPlatform == TargetPlatform.linux,
    );
    return MaterialApp(
      title: '疲勞監測操作台',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: kBackground,
        colorScheme: ColorScheme.fromSeed(
          seedColor: kAccent,
          brightness: Brightness.dark,
          surface: kSurface,
        ),
        dividerColor: kLine,
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          fillColor: kBackground,
          contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          labelStyle: TextStyle(color: kMutedInk, fontSize: 13),
          border: OutlineInputBorder(
              borderRadius: BorderRadius.all(Radius.circular(10)),
              borderSide: BorderSide(color: kLine)),
          enabledBorder:
              OutlineInputBorder(borderSide: BorderSide(color: kLine)),
          focusedBorder: OutlineInputBorder(
              borderSide: BorderSide(color: kAccentLine, width: 1.2)),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size(44, 44),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            textStyle:
                const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            foregroundColor: kInk,
            minimumSize: const Size(44, 42),
            side: const BorderSide(color: kLine),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            textStyle:
                const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
          ),
        ),
        tooltipTheme:
            const TooltipThemeData(waitDuration: Duration(milliseconds: 450)),
        snackBarTheme:
            const SnackBarThemeData(behavior: SnackBarBehavior.floating),
        fontFamilyFallback: const [
          'PingFang TC',
          'Microsoft JhengHei',
          'sans-serif'
        ],
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: ink, height: 1.5),
          bodySmall: TextStyle(color: kMutedInk, height: 1.5),
          titleMedium: TextStyle(color: ink, fontWeight: FontWeight.w700),
        ),
      ),
      home: capabilities.requiresNativeRuntime
          ? MobileRuntimeUnavailableShell(capabilities: capabilities)
          : Uri.base.queryParameters['overlay'] == '1'
              ? const OverlayShell()
              : const MonitorShell(),
    );
  }
}

class MobileRuntimeUnavailableShell extends StatelessWidget {
  const MobileRuntimeUnavailableShell({required this.capabilities, super.key});

  final PlatformCapabilities capabilities;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBackgroundDeep,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.phone_android, size: 48, color: kAccentBright),
                const SizedBox(height: 20),
                const Text(
                  '此行動平台尚未可用',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 12),
                Text(
                  capabilities.unavailableReason,
                  style: const TextStyle(color: kMutedInk, height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class DesktopNotice {
  const DesktopNotice(
      {required this.id, required this.level, required this.message});

  final int id;
  final String level;
  final String message;
}

DesktopNotice? parseDesktopNotice(dynamic raw) {
  if (raw is! Map || raw['id'] is! int || raw['message'] is! String) {
    return null;
  }
  final message = (raw['message'] as String).trim();
  if (message.isEmpty) return null;
  final rawLevel = raw['level'];
  final level = rawLevel == 'info' || rawLevel == 'error' ? rawLevel : 'error';
  return DesktopNotice(
    id: raw['id'] as int,
    level: level,
    message: message,
  );
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
  late final Stream<String> _previewFrames;
  Timer? _statePoller;
  final _metrics = ValueNotifier<Map<String, dynamic>>(<String, dynamic>{});
  Map<String, dynamic> _engineState = <String, dynamic>{};
  List<Map<String, dynamic>> _recordings = <Map<String, dynamic>>[];
  Map<String, dynamic>? _selectedRecording;
  List<Map<String, dynamic>> _playbackRows = <Map<String, dynamic>>[];
  int _playbackOffset = 0;
  int _playbackTotal = 0;
  int _playbackRequestId = 0;
  double _playbackStart = 0;
  bool _playbackBusy = false;
  bool _stateRefreshInFlight = false;
  String? _error;
  bool _connected = false;
  bool _commandBusy = false;
  bool _alwaysOnTop = false;
  int? _lastDesktopNoticeId;
  int _selectedSection = 0;
  Map<String, dynamic>? _pendingOverlaySync;
  bool _overlaySyncInFlight = false;
  bool _overlaySyncDisposed = false;
  bool _overlaySyncErrorShown = false;
  bool _overlayWindowStateInitialized = false;
  bool _lastOverlayVisible = false;
  bool _lastOverlayLocked = true;
  bool _overlayWindowExists = false;
  bool _acceptedOverlayGeometryInitialized = false;
  Map<String, dynamic>? _acceptedOverlayGeometry;

  @override
  void initState() {
    super.initState();
    _previewFrames = _backend.previewFrames;
    _metricsSubscription = _backend.connectMetrics().listen(
      (packet) {
        if (!mounted) return;
        _metrics.value = packet;
        if (!_connected) setState(() => _connected = true);
      },
      onError: (_) {
        if (mounted) setState(() => _connected = false);
      },
    );
    _refreshEngineState();
    _statePoller = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _refreshEngineState(silent: true),
    );
    _loadRecordings();
  }

  Future<void> _refreshEngineState({bool silent = false}) async {
    if (_stateRefreshInFlight) return;
    _stateRefreshInFlight = true;
    try {
      final state = await _backend.controlState();
      if (!mounted) return;
      _showNewDesktopNotice(state);
      _requestOverlaySync(state);
      if (!_connected ||
          jsonEncode(state) != jsonEncode(_engineState) ||
          (!silent && _error != null)) {
        setState(() {
          _engineState = state;
          _connected = true;
          if (!silent) _error = null;
        });
      }
    } catch (error) {
      _hideOverlayWindow();
      if (!mounted) return;
      setState(() {
        _connected = false;
        if (!silent) _error = '監測服務暫時無法連線，請稍後重試。';
      });
    } finally {
      _stateRefreshInFlight = false;
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
      final shellActionIssue = await _dispatchShellAction(state);
      if (mounted) {
        _showNewDesktopNotice(state);
        _requestOverlaySync(state);
        setState(() => _engineState = state);
        final message =
            shellActionIssue ?? _commandSuccessMessage(command, args);
        if (message != null) {
          _showCommandMessage(message, isError: shellActionIssue != null);
        }
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

  Future<String?> _dispatchShellAction(Map<String, dynamic> state) async {
    final rawResult = state['command_result'];
    if (rawResult is! Map) return null;
    final rawAction = rawResult['shell_action'];
    if (rawAction is! Map) return null;
    final kind = rawAction['kind'];
    final target = rawAction['target'];
    if (kind is! String || target is! String || target.isEmpty) {
      return '引擎已完成指令，但外部資源資訊無效';
    }
    if (!_bridge.isAvailable) {
      return '引擎已完成指令；請在 Tauri 桌面面板中開啟外部資源';
    }
    try {
      switch (kind) {
        case 'open_path':
          await _bridge.openExternalPath(target);
        case 'open_url':
          await _bridge.openExternalUrl(target);
        default:
          return '引擎回傳了不支援的外部操作';
      }
    } catch (error) {
      return '外部資源開啟失敗：$error';
    }
    return null;
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
        'web' => '已開啟診斷服務',
        'web_lan' => '診斷服務區域網設定已更新',
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

  void _showNewDesktopNotice(Map<String, dynamic> state) {
    final notice = parseDesktopNotice(state['desktop_notice']);
    if (notice == null || notice.id <= (_lastDesktopNoticeId ?? -1)) return;
    _lastDesktopNoticeId = notice.id;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _showCommandMessage(notice.message, isError: notice.level != 'info');
      }
    });
  }

  void _requestOverlaySync(Map<String, dynamic> state) {
    final running = state['pipeline_running'] == true;
    final preview = state['overlay_preview'] == true;
    final metrics = state['overlay_metrics'] == true;
    _queueOverlaySync(
      visible: running && (preview || metrics),
      locked: state['overlay_locked'] == true,
      geometry: overlayGeometryFromState(state),
    );
  }

  void _hideOverlayWindow() {
    _queueOverlaySync(
      visible: false,
      locked: true,
      syncGeometry: false,
      readGeometry: false,
      persistGeometry: false,
    );
  }

  void _queueOverlaySync({
    required bool visible,
    required bool locked,
    Map<String, dynamic>? geometry,
    bool syncGeometry = true,
    bool readGeometry = true,
    bool persistGeometry = true,
  }) {
    _pendingOverlaySync = <String, dynamic>{
      'visible': visible,
      'locked': locked,
      'geometry': geometry,
      'syncGeometry': syncGeometry,
      'readGeometry': readGeometry,
      'persistGeometry': persistGeometry,
    };
    if (_overlaySyncInFlight) return;
    _overlaySyncInFlight = true;
    unawaited(_drainOverlaySync());
  }

  Future<void> _drainOverlaySync() async {
    while (_pendingOverlaySync != null) {
      final desired = _pendingOverlaySync!;
      _pendingOverlaySync = null;
      if (!_bridge.isAvailable) continue;
      try {
        final visible = desired['visible'] == true;
        final locked = desired['locked'] == true;
        final savedGeometry = desired['geometry'] as Map<String, dynamic>?;
        final windowStateChanged = !_overlayWindowStateInitialized ||
            visible != _lastOverlayVisible ||
            locked != _lastOverlayLocked;
        final geometryNeedsApply = overlayGeometryNeedsApply(
          syncGeometry: desired['syncGeometry'] == true,
          acceptedInitialized: _acceptedOverlayGeometryInitialized,
          savedGeometry: savedGeometry,
          acceptedGeometry: _acceptedOverlayGeometry,
          visible: visible,
          windowExists: _overlayWindowExists,
        );
        if (windowStateChanged || geometryNeedsApply) {
          await _bridge.setOverlayWindow(
            visible: visible,
            locked: locked,
            geometry: geometryNeedsApply ? savedGeometry : null,
            resetGeometry: overlayGeometryResetRequested(
              geometryNeedsApply: geometryNeedsApply,
              savedGeometry: savedGeometry,
            ),
          );
          _overlayWindowStateInitialized = true;
          _lastOverlayVisible = visible;
          _lastOverlayLocked = locked;
        }

        Map<String, dynamic>? actualGeometry;
        if (desired['readGeometry'] == true) {
          actualGeometry = await _bridge.getOverlayGeometry();
          _overlayWindowExists = actualGeometry != null;
        }
        if (actualGeometry != null &&
            desired['persistGeometry'] == true &&
            !overlayGeometryEquals(actualGeometry, savedGeometry)) {
          final state = await _backend.command(
            'overlay.configure',
            <String, dynamic>{'geometry': actualGeometry},
          );
          if (mounted && !_overlaySyncDisposed) {
            setState(() => _engineState = state);
          }
          _acceptedOverlayGeometry = overlayGeometryFromState(state);
          _acceptedOverlayGeometryInitialized = true;
        } else if (actualGeometry != null) {
          _acceptedOverlayGeometry = savedGeometry;
          _acceptedOverlayGeometryInitialized = true;
        }
        _overlaySyncErrorShown = false;
      } catch (error) {
        if (!_overlaySyncErrorShown && mounted && !_overlaySyncDisposed) {
          _overlaySyncErrorShown = true;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && !_overlaySyncDisposed) {
              _showCommandMessage('Overlay window sync failed: $error',
                  isError: true);
            }
          });
        }
      }
    }
    _overlaySyncInFlight = false;
    if (_pendingOverlaySync != null) {
      _overlaySyncInFlight = true;
      unawaited(_drainOverlaySync());
    }
  }

  Future<void> _loadRecordings() async {
    try {
      final values = await _backend.recordings();
      if (mounted) {
        setState(() {
          _recordings = values;
          _error = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = '無法載入歷史記錄，請確認監測服務連線後重試。');
    }
  }

  Future<void> _openRecording(Map<String, dynamic> recording,
      {int offset = 0}) async {
    final path = recording['path']?.toString();
    if (path == null || path.isEmpty) return;
    final requestId = ++_playbackRequestId;
    setState(() {
      _selectedRecording = recording;
      _playbackRows = <Map<String, dynamic>>[];
      _playbackBusy = true;
      _playbackOffset = offset;
      if (offset == 0) {
        _playbackTotal = 0;
        _playbackStart = 0;
      }
    });
    try {
      final payload = await _backend.playback(path, limit: 200, offset: offset);
      if (mounted && requestId == _playbackRequestId) {
        setState(() {
          _error = null;
          _playbackRows = (payload['data'] as List?)
                  ?.whereType<Map>()
                  .map((row) => Map<String, dynamic>.from(row))
                  .toList() ??
              <Map<String, dynamic>>[];
          _playbackTotal = (payload['total'] as num?)?.toInt() ?? 0;
          if (offset == 0 && _playbackRows.isNotEmpty) {
            _playbackStart =
                (_playbackRows.first['timestamp'] as num?)?.toDouble() ?? 0;
          }
        });
      }
    } catch (error) {
      if (mounted && requestId == _playbackRequestId) {
        setState(() => _error = '無法載入這段記錄的指標，請稍後重試。');
      }
    } finally {
      if (mounted && requestId == _playbackRequestId) {
        setState(() => _playbackBusy = false);
      }
    }
  }

  @override
  void dispose() {
    _overlaySyncDisposed = true;
    _hideOverlayWindow();
    _metricsSubscription?.cancel();
    _metrics.dispose();
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
      body: ColoredBox(
        color: kBackground,
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
                child: LayoutBuilder(
                    builder: (context, constraints) => Row(
                          children: [
                            NavigationRailPanel(
                              compact: constraints.maxWidth < 1120 ||
                                  MediaQuery.textScalerOf(context).scale(1) >
                                      1.3,
                              connected: _connected,
                              selectedIndex: _selectedSection,
                              onSelected: (value) =>
                                  setState(() => _selectedSection = value),
                              alwaysOnTop: _alwaysOnTop,
                              onAlwaysOnTop: () async {
                                try {
                                  final value =
                                      await _bridge.toggleAlwaysOnTop();
                                  if (mounted) {
                                    setState(() => _alwaysOnTop = value);
                                  }
                                } catch (_) {}
                              },
                            ),
                            Expanded(
                                child: Column(children: [
                              if (_error != null)
                                Padding(
                                  padding:
                                      const EdgeInsets.fromLTRB(24, 16, 24, 0),
                                  child: _InlineNotice(
                                      message: _error!,
                                      onRetry: _selectedSection == 2
                                          ? () => _selectedRecording == null
                                              ? _loadRecordings()
                                              : _openRecording(
                                                  _selectedRecording!,
                                                  offset: _playbackOffset)
                                          : _refreshEngineState),
                                ),
                              Expanded(child: _content()),
                            ])),
                          ],
                        )),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content() {
    if (_selectedSection == 1) {
      return ValueListenableBuilder<Map<String, dynamic>>(
          valueListenable: _metrics,
          builder: (context, metrics, _) => ChestBeltView(
                metrics: metrics,
                state: _engineState,
                busy: _commandBusy,
                onCommand: _runCommand,
              ));
    }
    if (_selectedSection == 2) {
      return PlaybackView(
        recordings: _recordings,
        selected: _selectedRecording,
        rows: _playbackRows,
        busy: _playbackBusy || _commandBusy,
        state: _engineState,
        onCommand: _runCommand,
        onRefresh: _loadRecordings,
        onOpen: _openRecording,
        offset: _playbackOffset,
        total: _playbackTotal,
        startTimestamp: _playbackStart,
        onPage: (offset) => _openRecording(_selectedRecording!, offset: offset),
        onClose: () => setState(() {
          _playbackRequestId++;
          _selectedRecording = null;
          _playbackBusy = false;
        }),
        onPickReplayFolder: _bridge.pickReplayFolder,
      );
    }
    if (_selectedSection == 3) {
      return SettingsView(
        state: _engineState,
        busy: _commandBusy,
        onCommand: _runCommand,
      );
    }
    return ValueListenableBuilder<Map<String, dynamic>>(
        valueListenable: _metrics,
        builder: (context, metrics, _) => DashboardView(
              metrics: metrics,
              engineState: _engineState,
              previewFrames: _previewFrames,
              connected: _connected,
              busy: _commandBusy,
              error: null,
              onRetry: _refreshEngineState,
              onCommand: _runCommand,
            ));
  }
}

class OverlayShell extends StatefulWidget {
  const OverlayShell({
    this.initialMetrics = const <String, dynamic>{},
    this.initialState = const <String, dynamic>{},
    super.key,
  });

  final Map<String, dynamic> initialMetrics;
  final Map<String, dynamic> initialState;

  @override
  State<OverlayShell> createState() => _OverlayShellState();
}

double overlayOpacityPercent(Map<String, dynamic> state) {
  return ((state['overlay_opacity'] as num?)?.toDouble() ?? 55)
      .clamp(0, 100)
      .toDouble();
}

Map<String, dynamic>? overlayGeometryFromState(Map<String, dynamic> state) {
  final raw = state['overlay_geometry'];
  if (raw is! Map) return null;
  final geometry = Map<String, dynamic>.from(raw);
  if (geometry.keys
          .toSet()
          .difference({'x', 'y', 'width', 'height'}).isNotEmpty ||
      !{'x', 'y', 'width', 'height'}.every(geometry.containsKey) ||
      geometry.values.any((value) => value is! int)) {
    return null;
  }
  return geometry;
}

bool overlayGeometryEquals(
  Map<String, dynamic>? left,
  Map<String, dynamic>? right,
) {
  if (left == null || right == null) return left == right;
  return const {'x', 'y', 'width', 'height'}
      .every((key) => left[key] == right[key]);
}

bool overlayGeometryNeedsApply({
  required bool syncGeometry,
  required bool acceptedInitialized,
  required Map<String, dynamic>? savedGeometry,
  required Map<String, dynamic>? acceptedGeometry,
  required bool visible,
  required bool windowExists,
}) {
  if (!syncGeometry || (!visible && !windowExists)) return false;
  return !acceptedInitialized ||
      !overlayGeometryEquals(savedGeometry, acceptedGeometry);
}

bool overlayGeometryResetRequested({
  required bool geometryNeedsApply,
  required Map<String, dynamic>? savedGeometry,
}) {
  return geometryNeedsApply && savedGeometry == null;
}

String formatOverlayValue(String key, Object? rawValue) {
  if (rawValue == null) return '--';
  if (key == 'status') {
    final text = rawValue.toString().trim();
    return text.isEmpty ? '--' : text;
  }

  final value = rawValue is num
      ? rawValue.toDouble()
      : double.tryParse(rawValue.toString());
  if (value == null || !value.isFinite) return '--';
  switch (key) {
    case 'fps':
      return value > 0 ? value.toStringAsFixed(1) : '--';
    case 'stress_bpm':
      return value > 0 ? value.toStringAsFixed(1) : '--';
    case 'perclos':
      return '${value.clamp(0, 100).toStringAsFixed(1)}%';
    default:
      return rawValue.toString();
  }
}

class _OverlayShellState extends State<OverlayShell> {
  final _backend = BackendService();
  final _bridge = TauriBridge.instance;
  StreamSubscription<Map<String, dynamic>>? _metricsSubscription;
  late final Stream<String> _previewFrames;
  Timer? _poller;
  Map<String, dynamic> _metrics = <String, dynamic>{};
  Map<String, dynamic> _state = <String, dynamic>{};
  bool _hiddenAfterDisconnect = false;
  bool _refreshInFlight = false;

  @override
  void initState() {
    super.initState();
    _metrics = Map<String, dynamic>.from(widget.initialMetrics);
    _state = Map<String, dynamic>.from(widget.initialState);
    _previewFrames = _backend.previewFrames;
    _metricsSubscription = _backend.connectMetrics().listen((packet) {
      if (mounted) setState(() => _metrics = packet);
    });
    _refresh();
    _poller = Timer.periodic(const Duration(seconds: 1), (_) => _refresh());
  }

  Future<void> _refresh() async {
    if (_refreshInFlight) return;
    _refreshInFlight = true;
    try {
      final state = await _backend.controlState();
      Map<String, dynamic>? metrics;
      try {
        metrics = await _backend.metricsSnapshot();
      } catch (_) {
        // Socket.IO remains the primary stream when the snapshot is unavailable.
      }
      if (mounted) {
        _hiddenAfterDisconnect = false;
        setState(() {
          _state = state;
          if (metrics != null && metrics.isNotEmpty) _metrics = metrics;
        });
      }
    } catch (_) {
      if (!_hiddenAfterDisconnect) {
        _hiddenAfterDisconnect = true;
        unawaited(_hideOverlayWindow());
      }
    } finally {
      _refreshInFlight = false;
    }
  }

  Future<void> _hideOverlayWindow() async {
    if (!_bridge.isAvailable) return;
    try {
      await _bridge.setOverlayWindow(visible: false, locked: true);
    } catch (_) {}
  }

  @override
  void dispose() {
    unawaited(_hideOverlayWindow());
    _metricsSubscription?.cancel();
    _poller?.cancel();
    unawaited(_backend.dispose());
    super.dispose();
  }

  Future<void> _drag() async {
    try {
      await _bridge.startDragging();
    } catch (_) {}
  }

  String _metricText(String key) => formatOverlayValue(key, _metrics[key]);

  @override
  Widget build(BuildContext context) {
    final previewOn = _state['overlay_preview'] == true;
    final metricsOn = _state['overlay_metrics'] == true;
    final locked = _state['overlay_locked'] == true;
    final opacity = overlayOpacityPercent(_state);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onPanStart: locked ? null : (_) => _drag(),
        child: Opacity(
          opacity: opacity / 100,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: const Color(0xe6151b2b),
              border: Border.all(color: kAccentBright.withValues(alpha: .75)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  Row(children: [
                    Icon(locked ? Icons.lock_outline : Icons.open_with,
                        size: 16, color: kAccentBright),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        'NCFD 監測 Overlay',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                    ),
                    SizedBox(
                      width: 76,
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerRight,
                        child: Text(
                          'FPS ${_metricText('fps')}',
                          maxLines: 1,
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ),
                    ),
                  ]),
                  if (previewOn) ...[
                    const SizedBox(height: 8),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: ColoredBox(
                          color: kBackgroundDeep,
                          child: LivePreviewImage(
                              frames: _previewFrames,
                              placeholder: Center(
                                child: Icon(
                                  _state['pipeline_running'] == true
                                      ? Icons.videocam_outlined
                                      : Icons.videocam_off_outlined,
                                  color: Colors.white24,
                                  size: 30,
                                ),
                              )),
                        ),
                      ),
                    ),
                  ],
                  if (metricsOn) ...[
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: _OverlayMetric(
                            label: 'BPM',
                            value: _metricText('stress_bpm'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: _OverlayMetric(
                            label: 'PERCLOS',
                            value: _metricText('perclos'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: _OverlayMetric(
                            label: '狀態',
                            value: fatiguePresentation(_metrics).$1,
                            color: fatiguePresentation(_metrics).$2,
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _OverlayMetric extends StatelessWidget {
  const _OverlayMetric(
      {required this.label, required this.value, this.color = kAccentBright});

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall,
        ),
        const SizedBox(height: 2),
        SizedBox(
          width: double.infinity,
          height: 28,
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              value,
              maxLines: 1,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: color),
            ),
          ),
        ),
      ],
    );
  }
}

class AppTitleBar extends StatelessWidget {
  const AppTitleBar(
      {required this.onDrag,
      required this.onMinimize,
      required this.onMaximize,
      required this.onClose,
      super.key});
  final VoidCallback onDrag;
  final VoidCallback onMinimize;
  final VoidCallback onMaximize;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => Container(
        height: 52,
        padding: const EdgeInsets.only(left: 18, right: 10),
        decoration: const BoxDecoration(
            color: kBackgroundDeep,
            border: Border(bottom: BorderSide(color: kLine))),
        child: Row(children: [
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onPanStart: (_) => onDrag(),
              onDoubleTap: onMaximize,
              child: Row(children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                      color: kAccent.withValues(alpha: .12),
                      borderRadius: BorderRadius.circular(8)),
                  child: const Icon(Icons.radar, size: 18, color: kAccent),
                ),
                const SizedBox(width: 12),
                const Flexible(
                    child: Text('疲勞監測操作台',
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600))),
                if (MediaQuery.sizeOf(context).width > 700) ...[
                  const SizedBox(width: 18),
                  const Text('FATIGUE MONITOR',
                      style: TextStyle(
                          fontSize: 10, color: kMutedInk, letterSpacing: 1.4)),
                ],
              ]),
            ),
          ),
          WindowButton(
              icon: Icons.remove, tooltip: '最小化', onPressed: onMinimize),
          WindowButton(
              icon: Icons.crop_square,
              tooltip: '最大化或還原',
              onPressed: onMaximize),
          WindowButton(
              icon: Icons.close,
              tooltip: '關閉',
              isClose: true,
              onPressed: onClose),
        ]),
      );
}

class WindowButton extends StatefulWidget {
  const WindowButton(
      {required this.icon,
      required this.tooltip,
      required this.onPressed,
      this.isClose = false,
      super.key});
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
          duration: MediaQuery.disableAnimationsOf(context)
              ? Duration.zero
              : const Duration(milliseconds: 140),
          width: 42,
          height: 34,
          decoration: BoxDecoration(
              color: _hovered
                  ? (widget.isClose
                      ? const Color(0xffd35f63).withValues(alpha: .8)
                      : kAccent.withValues(alpha: .14))
                  : Colors.transparent,
              border: _hovered && !widget.isClose
                  ? Border.all(color: kAccentLine)
                  : null,
              borderRadius: BorderRadius.circular(7)),
          child: IconButton(
              onPressed: widget.onPressed,
              icon: Icon(widget.icon, size: 16),
              splashRadius: 18),
        ),
      ),
    );
  }
}

class NavigationRailPanel extends StatelessWidget {
  const NavigationRailPanel(
      {required this.selectedIndex,
      required this.onSelected,
      required this.alwaysOnTop,
      required this.onAlwaysOnTop,
      this.compact = false,
      this.connected = false,
      super.key});
  final bool compact;
  final bool connected;
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
      width: compact ? 76 : 208,
      padding:
          EdgeInsets.fromLTRB(compact ? 10 : 16, 24, compact ? 10 : 16, 16),
      decoration: const BoxDecoration(
          color: kBackgroundDeep,
          border: Border(right: BorderSide(color: kLine))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!compact)
            Text('工作空間',
                style: TextStyle(
                    fontSize: 10, letterSpacing: 1.8, color: kMutedInk)),
          const SizedBox(height: 16),
          for (var index = 0; index < items.length; index++) ...[
            _NavItem(
                icon: items[index].$1,
                label: items[index].$2,
                selected: selectedIndex == index,
                compact: compact,
                onTap: () => onSelected(index)),
            const SizedBox(height: 5),
          ],
          const Spacer(),
          Tooltip(
              message: '固定在最上層',
              excludeFromSemantics: !compact,
              child: InkWell(
                onTap: onAlwaysOnTop,
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                  child: Row(children: [
                    Icon(alwaysOnTop ? Icons.push_pin : Icons.push_pin_outlined,
                        size: 17,
                        color: alwaysOnTop ? kAccentBright : Colors.white54),
                    if (!compact) const SizedBox(width: 10),
                    if (!compact)
                      Flexible(
                          child: Text('固定在最上層',
                              style: TextStyle(
                                  fontSize: 12,
                                  color: alwaysOnTop ? kInk : kMutedInk)))
                  ]),
                ),
              )),
          const SizedBox(height: 14),
          if (!compact)
            Text('本機監測',
                style: TextStyle(
                    fontSize: 10, letterSpacing: 1.2, color: kMutedInk)),
          const SizedBox(height: 6),
          Row(children: [
            Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: connected ? kAccent : kMutedInk)),
            if (!compact) const SizedBox(width: 7),
            if (!compact)
              Flexible(
                  child: Text(connected ? '引擎已連線' : '等待引擎連線',
                      style: TextStyle(fontSize: 11, color: kMutedInk)))
          ]),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem(
      {required this.icon,
      required this.label,
      required this.selected,
      required this.onTap,
      this.compact = false});
  final bool compact;
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
        selected: selected,
        button: true,
        label: compact ? label : null,
        child: Tooltip(
            excludeFromSemantics: compact,
            message: compact ? label : '',
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: selected
                    ? kAccent.withValues(alpha: .14)
                    : Colors.transparent,
                border: selected ? Border.all(color: kAccentLine) : null,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Material(
                color: Colors.transparent,
                borderRadius: BorderRadius.circular(8),
                child: InkWell(
                  onTap: onTap,
                  borderRadius: BorderRadius.circular(8),
                  child: Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 12),
                      child: Row(children: [
                        Icon(icon,
                            size: 18,
                            color: selected ? kAccentBright : Colors.white54),
                        if (!compact) const SizedBox(width: 11),
                        if (!compact)
                          Flexible(
                              child: Text(label,
                                  style: TextStyle(
                                      fontSize: 13,
                                      fontWeight: selected
                                          ? FontWeight.w700
                                          : FontWeight.w500,
                                      color: selected ? kInk : kMutedInk)))
                      ])),
                ),
              ),
            )));
  }
}

class DashboardView extends StatelessWidget {
  const DashboardView({
    required this.metrics,
    required this.engineState,
    required this.previewFrames,
    required this.connected,
    required this.busy,
    required this.error,
    required this.onRetry,
    required this.onCommand,
    super.key,
  });
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> engineState;
  final Stream<String> previewFrames;
  final bool connected;
  final bool busy;
  final String? error;
  final Future<void> Function() onRetry;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  double _number(String key, [double fallback = 0]) =>
      (metrics[key] as num?)?.toDouble() ?? fallback;
  String _text(String key, [String fallback = '--']) =>
      metrics[key]?.toString() ?? fallback;
  bool get _focus => engineState['monitor_focus'] == true;

  @override
  Widget build(BuildContext context) {
    final (fatigue, fatigueColor) =
        fatiguePresentation(metrics, fallback: connected ? '等待資料' : '尚未連線');
    return PanelPage(
      title: '即時監測',
      description: '專注當下狀態，掌握每一個重要訊號。',
      trailing: _ConnectionPill(connected: connected),
      children: [
        if (error != null)
          Padding(
              padding: const EdgeInsets.only(top: 16),
              child: _InlineNotice(message: error!, onRetry: onRetry)),
        if (_focus)
          _FocusDashboard(
            previewFrames: previewFrames,
            running: engineState['pipeline_running'] == true,
            status: fatigue,
            statusColor: fatigueColor,
            connected: connected,
            busy: busy,
            onExit: () =>
                onCommand('monitor.layout', <String, dynamic>{'focus': false}),
          )
        else ...[
          LayoutBuilder(builder: (context, constraints) {
            final panels = [
              _StatusPanel(
                  status: fatigue, color: fatigueColor, metrics: metrics),
              _SignalPanel(
                  bpm: _number('stress_bpm'),
                  sqi: _number('stress_sqi'),
                  fps: _number('fps')),
            ];
            if (constraints.maxWidth < 640 ||
                MediaQuery.textScalerOf(context).scale(1) > 1.3) {
              return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    panels.first,
                    const SizedBox(height: 12),
                    panels.last
                  ]);
            }
            return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(flex: 3, child: panels.first),
              const SizedBox(width: 16),
              Expanded(flex: 2, child: panels.last),
            ]);
          }),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final preview = CameraPreview(
                  frames: previewFrames,
                  running: engineState['pipeline_running'] == true);
              final controls = DesktopControlPanel(
                  state: engineState, busy: busy, onCommand: onCommand);
              if (constraints.maxWidth < 780 ||
                  MediaQuery.textScalerOf(context).scale(1) > 1.3) {
                return Column(
                    children: [preview, const SizedBox(height: 16), controls]);
              }
              return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: preview),
                    const SizedBox(width: 16),
                    SizedBox(width: 300, child: controls),
                  ]);
            },
          ),
          const SizedBox(height: 16),
          LayoutBuilder(builder: (context, constraints) {
            final columns = constraints.maxWidth >= 800
                ? 4
                : constraints.maxWidth >= 400
                    ? 2
                    : 1;
            final width = (constraints.maxWidth - 12 * (columns - 1)) / columns;
            final tiles = [
              MetricTile(
                  label: '眼瞼閉合 EAR',
                  value: metrics['ear'] is num
                      ? _number('ear').toStringAsFixed(2)
                      : '--',
                  suffix: 'ratio',
                  icon: Icons.remove_red_eye_outlined),
              MetricTile(
                  label: 'PERCLOS',
                  value: metrics['perclos'] is num
                      ? _number('perclos').toStringAsFixed(1)
                      : '--',
                  suffix: '%',
                  icon: Icons.timer_outlined),
              MetricTile(
                  label: '眨眼次數',
                  value: _text('blink_count'),
                  suffix: '次',
                  icon: Icons.visibility_off_outlined),
              MetricTile(
                  label: '頭部俯仰',
                  value: metrics['head_pitch'] is num
                      ? _number('head_pitch').toStringAsFixed(1)
                      : '--',
                  suffix: 'deg',
                  icon: Icons.threed_rotation),
            ];
            return Wrap(spacing: 12, runSpacing: 12, children: [
              for (final tile in tiles) SizedBox(width: width, child: tile)
            ]);
          }),
          const SizedBox(height: 20),
          const PanelSectionTitle(title: '訊號品質', subtitle: '檢視追蹤穩定度與訊號可信度'),
          _QualityStrip(metrics: metrics),
          const SizedBox(height: 16),
          HeartRateBeltPanel(
              metrics: metrics,
              engineState: engineState,
              busy: busy,
              onCommand: onCommand),
        ],
      ],
    );
  }
}

class _FocusDashboard extends StatelessWidget {
  const _FocusDashboard({
    required this.previewFrames,
    required this.running,
    required this.status,
    required this.statusColor,
    required this.connected,
    required this.busy,
    required this.onExit,
  });

  final Stream<String> previewFrames;
  final bool running;
  final String status;
  final Color statusColor;
  final bool connected;
  final bool busy;
  final VoidCallback onExit;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Text(
              'FOCUS PREVIEW',
              style:
                  TextStyle(color: kMutedInk, fontSize: 10, letterSpacing: 1.4),
            ),
            const Spacer(),
            Tooltip(
              message: '切回分割模式',
              child: IconButton(
                onPressed: busy ? null : onExit,
                icon: const Icon(Icons.fullscreen_exit),
                color: kAccentBright,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        CameraPreview(frames: previewFrames, running: running),
        const SizedBox(height: 12),
        GlassPanel(
          child: Wrap(
            spacing: 20,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.monitor_heart_outlined,
                      size: 18, color: statusColor),
                  const SizedBox(width: 8),
                  Text(status,
                      style: TextStyle(
                          color: statusColor, fontWeight: FontWeight.w700)),
                ],
              ),
              _ConnectionPill(connected: connected),
              Text(running ? '正在擷取即時影像' : '擷取尚未啟動',
                  style: TextStyle(color: kMutedInk, fontSize: 12)),
            ],
          ),
        ),
      ],
    );
  }
}

class CameraPreview extends StatelessWidget {
  const CameraPreview({required this.frames, required this.running, super.key});
  final Stream<String> frames;
  final bool running;

  @override
  Widget build(BuildContext context) {
    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('LIVE CAMERA',
              style: TextStyle(
                  color: kMutedInk, fontSize: 10, letterSpacing: 1.4)),
          const Spacer(),
          _BeltStatusPill(
              label: running ? '即時影像' : '待機',
              color: running ? kAccent : kMutedInk),
        ]),
        const SizedBox(height: 14),
        LayoutBuilder(
            builder: (context, constraints) => SizedBox(
                  width: double.infinity,
                  height: (constraints.maxWidth * 9 / 16).clamp(160, 300),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: ColoredBox(
                      color: kBackgroundDeep,
                      child: LivePreviewImage(
                          frames: frames,
                          placeholder: Center(
                              child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                Icon(
                                    running
                                        ? Icons.videocam_outlined
                                        : Icons.videocam_off_outlined,
                                    color: Colors.white24,
                                    size: 34),
                                const SizedBox(height: 10),
                                Text(running ? '等待影像串流' : '選擇攝影機，開始你的監測工作階段',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                        color: kMutedInk, fontSize: 12))
                              ]))),
                    ),
                  ),
                )),
      ]),
    );
  }
}

class DesktopControlPanel extends StatelessWidget {
  const DesktopControlPanel(
      {required this.state,
      required this.busy,
      required this.onCommand,
      super.key});
  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  @override
  Widget build(BuildContext context) {
    final running = state['pipeline_running'] == true;
    final recording = state['recording'] == true;
    final focus = state['monitor_focus'] == true;
    final capturing = state['auto_capture_active'] == true;
    final autoDuration = (state['auto_capture_seconds'] as num?)?.toInt() ?? 60;
    final includeBelt = state['auto_capture_include_belt'] == true;
    final cameraRows =
        (state['cameras'] as List?)?.whereType<Map>().toList() ?? <Map>[];
    final cameraIndexes =
        cameraRows.map((row) => row['index']).whereType<int>().toSet();
    final selectedRaw = state['selected_camera_index'];
    final selected = selectedRaw is int && cameraIndexes.contains(selectedRaw)
        ? selectedRaw
        : null;
    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('SYSTEM CONTROL',
            style:
                TextStyle(color: kMutedInk, fontSize: 10, letterSpacing: 1.4)),
        const SizedBox(height: 14),
        DropdownButtonFormField<int>(
          isExpanded: true,
          initialValue: selected,
          decoration: const InputDecoration(
              labelText: '攝影機', border: OutlineInputBorder(), isDense: true),
          items: cameraRows
              .map((row) => DropdownMenuItem<int>(
                  value: row['index'] as int,
                  child: Text(
                      row['label']?.toString() ?? 'Camera ${row['index']}',
                      overflow: TextOverflow.ellipsis)))
              .toList(),
          onChanged: busy || running
              ? null
              : (value) {
                  if (value != null) {
                    onCommand(
                        'camera.select', <String, dynamic>{'index': value});
                  }
                },
        ),
        if (cameraRows.isEmpty) ...[
          const SizedBox(height: 8),
          Text(
            '尚未偵測到攝影機。請確認系統相機權限與裝置連線。',
            style: TextStyle(color: kMutedInk, fontSize: 12),
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: busy
                  ? null
                  : () async {
                      try {
                        await TauriBridge.instance.openCameraPrivacySettings();
                      } catch (_) {
                        // Browser development and unsupported shells have no
                        // native privacy-settings command.
                      }
                    },
              icon: const Icon(Icons.lock_outline, size: 17),
              label: const Text('開啟相機權限設定'),
            ),
          ),
        ],
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: busy || (!running && selected == null)
              ? null
              : () => onCommand(
                  'pipeline.set', <String, dynamic>{'enabled': !running}),
          icon: Icon(running ? Icons.stop_circle_outlined : Icons.play_arrow),
          label: Text(running ? '停止監測' : '開始監測'),
          style: FilledButton.styleFrom(
              minimumSize: const Size.fromHeight(44),
              backgroundColor: running ? const Color(0xffb75255) : kAccentDeep),
        ),
        const SizedBox(height: 9),
        Align(
          alignment: Alignment.centerLeft,
          child: Tooltip(
              message: '切換右側數值欄顯示',
              child: SegmentedButton<bool>(
                  showSelectedIcon: false,
                  expandedInsets: EdgeInsets.zero,
                  segments: const [
                    ButtonSegment<bool>(
                        value: false, label: Text('總覽', maxLines: 1)),
                    ButtonSegment<bool>(
                        value: true, label: Text('專注', maxLines: 1))
                  ],
                  selected: <bool>{focus},
                  onSelectionChanged: busy
                      ? null
                      : (values) => onCommand('monitor.layout',
                          <String, dynamic>{'focus': values.first}))),
        ),
        const SizedBox(height: 9),
        OutlinedButton.icon(
          onPressed: busy || (!running && !recording)
              ? null
              : () => onCommand(
                  'recording.set', <String, dynamic>{'enabled': !recording}),
          icon: Icon(recording ? Icons.stop : Icons.fiber_manual_record,
              color: recording ? const Color(0xffe77b78) : null),
          label: Text(recording ? '停止記錄' : '開始記錄'),
        ),
        const SizedBox(height: 9),
        ExpansionTile(
            tilePadding: EdgeInsets.zero,
            childrenPadding: const EdgeInsets.only(top: 12),
            shape: const Border(),
            collapsedShape: const Border(),
            title: const Text('自動採集', style: TextStyle(fontSize: 13)),
            subtitle: Text(capturing ? '正在採集 · $autoDuration 秒' : '設定時長與同步來源',
                style: const TextStyle(color: kMutedInk, fontSize: 11)),
            initiallyExpanded: capturing,
            children: [
              DropdownButtonFormField<int>(
                isExpanded: true,
                initialValue:
                    <int>[30, 60, 120, 300, 600].contains(autoDuration)
                        ? autoDuration
                        : 60,
                decoration: const InputDecoration(
                    labelText: '自動採集秒數',
                    border: OutlineInputBorder(),
                    isDense: true),
                items: const [30, 60, 120, 300, 600]
                    .map((seconds) => DropdownMenuItem<int>(
                        value: seconds, child: Text('$seconds 秒')))
                    .toList(),
                onChanged: busy || capturing
                    ? null
                    : (value) {
                        if (value != null) {
                          onCommand('auto_capture.configure', <String, dynamic>{
                            'duration_seconds': value,
                            'include_belt': includeBelt
                          });
                        }
                      },
              ),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('同步心跳帶真值'),
                value: includeBelt,
                onChanged: busy || capturing
                    ? null
                    : (value) => onCommand(
                            'auto_capture.configure', <String, dynamic>{
                          'duration_seconds': autoDuration,
                          'include_belt': value
                        }),
              ),
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () => onCommand('auto_capture.set', <String, dynamic>{
                          'enabled': !capturing,
                          'duration_seconds': autoDuration,
                          'include_belt': includeBelt
                        }),
                icon: Icon(capturing
                    ? Icons.timer_off_outlined
                    : Icons.timer_outlined),
                label: Text(capturing ? '停止自動採集' : '開始自動採集'),
              ),
            ]),
        const SizedBox(height: 8),
        TextButton.icon(
            onPressed:
                busy || running ? null : () => onCommand('camera.refresh'),
            icon: const Icon(Icons.refresh, size: 17),
            label: const Text('刷新攝影機')),
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
    return Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
        decoration: BoxDecoration(
            color: color.withValues(alpha: .1),
            border: Border.all(color: color.withValues(alpha: .28)),
            borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 7),
          Text(connected ? '引擎已連線' : '等待後端',
              style: TextStyle(
                  color: color, fontSize: 11, fontWeight: FontWeight.w700))
        ]));
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel(
      {required this.status, required this.color, required this.metrics});
  final String status;
  final Color color;
  final Map<String, dynamic> metrics;

  @override
  Widget build(BuildContext context) => GlassPanel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('CURRENT STATE',
              style: TextStyle(
                  color: kMutedInk, fontSize: 10, letterSpacing: 1.2)),
          const SizedBox(height: 10),
          Row(children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                  color: color.withValues(alpha: .12),
                  borderRadius: BorderRadius.circular(10)),
              child: Icon(
                  metrics['calibrated'] == true
                      ? Icons.shield_outlined
                      : Icons.radar,
                  color: color,
                  size: 24),
            ),
            const SizedBox(width: 12),
            Expanded(
                child: Text(status,
                    style: TextStyle(
                        color: color,
                        fontSize: 22,
                        fontWeight: FontWeight.w700))),
          ]),
          const SizedBox(height: 10),
          Text(metrics['calibrated'] == true ? '臉部追蹤與個人基線已就緒' : '等待臉部與校準資料',
              style: const TextStyle(color: kMutedInk, fontSize: 12)),
        ]),
      );
}

class _SignalPanel extends StatelessWidget {
  const _SignalPanel({required this.bpm, required this.sqi, required this.fps});
  final double bpm;
  final double sqi;
  final double fps;

  @override
  Widget build(BuildContext context) => GlassPanel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('PHYSIOLOGY / rPPG',
              style: TextStyle(
                  color: kMutedInk, fontSize: 10, letterSpacing: 1.2)),
          const SizedBox(height: 10),
          Wrap(
              spacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                const Icon(Icons.monitor_heart_outlined,
                    color: kAccent, size: 24),
                Text(bpm > 0 ? bpm.toStringAsFixed(0) : '--',
                    style: const TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.w600,
                        height: 1.25)),
                const Text('BPM',
                    style: TextStyle(color: kMutedInk, fontSize: 12)),
              ]),
          const SizedBox(height: 10),
          Wrap(spacing: 16, runSpacing: 4, children: [
            Text('SQI ${(sqi * 100).toStringAsFixed(0)}%',
                style: const TextStyle(color: kAccentBright, fontSize: 12)),
            Text('${fps.toStringAsFixed(1)} FPS',
                style: const TextStyle(color: kMutedInk, fontSize: 12)),
          ]),
        ]),
      );
}

class MetricTile extends StatelessWidget {
  const MetricTile(
      {required this.label,
      required this.value,
      required this.suffix,
      required this.icon,
      super.key});
  final String label;
  final String value;
  final String suffix;
  final IconData icon;

  @override
  Widget build(BuildContext context) => GlassPanel(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(icon, size: 16, color: kMutedInk),
            const SizedBox(width: 8),
            Expanded(
                child: Text(label,
                    style: const TextStyle(color: kMutedInk, fontSize: 12))),
          ]),
          const SizedBox(height: 12),
          Wrap(
              spacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(value,
                    style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w600,
                        height: 1.2)),
                Text(suffix,
                    style: const TextStyle(fontSize: 11, color: kMutedInk)),
              ]),
        ]),
      );
}

class _QualityStrip extends StatelessWidget {
  const _QualityStrip({required this.metrics});
  final Map<String, dynamic> metrics;

  @override
  Widget build(BuildContext context) {
    final items = <String, double>{
      '臉部追蹤': ((metrics['fatigue_quality_score'] as num?)?.toDouble() ?? 0),
      'rPPG 訊號': ((metrics['stress_quality_score'] as num?)?.toDouble() ?? 0),
      'ROI 穩定度':
          ((metrics['stress_roi_area_stability'] as num?)?.toDouble() ?? 0)
    };
    return GlassPanel(
        child: Column(
            children: items.entries
                .map((entry) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 7),
                    child: Row(children: [
                      SizedBox(
                          width: 85,
                          child: Text(entry.key,
                              style:
                                  TextStyle(color: kMutedInk, fontSize: 12))),
                      Expanded(
                          child: ClipRRect(
                              borderRadius: BorderRadius.circular(4),
                              child: LinearProgressIndicator(
                                  value: entry.value.clamp(0, 1),
                                  minHeight: 7,
                                  backgroundColor:
                                      Colors.white.withValues(alpha: .07),
                                  color: kAccent))),
                      const SizedBox(width: 12),
                      SizedBox(
                          width: 44,
                          child: Text(
                              '${(entry.value * 100).toStringAsFixed(0)}%',
                              textAlign: TextAlign.right,
                              style: const TextStyle(
                                  color: kAccentBright, fontSize: 12)))
                    ])))
                .toList()));
  }
}

class _OverlayOpacityControl extends StatefulWidget {
  const _OverlayOpacityControl(
      {required this.value, required this.enabled, required this.onChanged});

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
      const SizedBox(
          width: 102, child: Text('透明度', style: TextStyle(fontSize: 12))),
      Expanded(
        child: Slider(
          value: _value,
          min: 0,
          max: 100,
          divisions: 100,
          label: '${_value.toStringAsFixed(0)}%',
          onChangeStart: widget.enabled ? (_) => _dragging = true : null,
          onChanged:
              widget.enabled ? (value) => setState(() => _value = value) : null,
          onChangeEnd: widget.enabled
              ? (value) {
                  _dragging = false;
                  setState(() => _value = value);
                  widget.onChanged(value.round());
                }
              : null,
        ),
      ),
      SizedBox(
          width: 42,
          child: Text('${_value.toStringAsFixed(0)}%',
              textAlign: TextAlign.right)),
    ]);
  }
}

class _SettingDropdown extends StatelessWidget {
  const _SettingDropdown(
      {required this.label,
      required this.value,
      required this.values,
      required this.enabled,
      required this.onChanged});
  final String label;
  final String? value;
  final List<String> values;
  final bool enabled;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final selected = value != null && values.contains(value) ? value : null;
    return DropdownButtonFormField<String>(
      isExpanded: true,
      initialValue: selected,
      decoration: InputDecoration(
          labelText: label, border: const OutlineInputBorder(), isDense: true),
      items: values
          .map((item) => DropdownMenuItem<String>(
              value: item, child: Text(item, overflow: TextOverflow.ellipsis)))
          .toList(),
      onChanged: enabled
          ? (item) {
              if (item != null) onChanged(item);
            }
          : null,
    );
  }
}

class _SettingSwitch extends StatelessWidget {
  const _SettingSwitch(
      {required this.title,
      required this.subtitle,
      required this.value,
      required this.enabled,
      required this.onChanged});
  final String title;
  final String subtitle;
  final bool value;
  final bool enabled;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(title,
          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
      subtitle:
          Text(subtitle, style: TextStyle(color: kMutedInk, fontSize: 12)),
      value: value,
      onChanged: enabled ? onChanged : null,
    );
  }
}

class GlassPanel extends StatelessWidget {
  const GlassPanel(
      {required this.child,
      this.padding = const EdgeInsets.all(18),
      super.key});
  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(12);
    return Material(
      color: kSurface,
      shape: RoundedRectangleBorder(
          borderRadius: radius, side: const BorderSide(color: kLine)),
      child: Padding(padding: padding, child: child),
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.message, required this.onRetry});
  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        decoration: BoxDecoration(
            color: const Color(0xffb46d4d).withValues(alpha: .12),
            border: Border.all(
                color: const Color(0xffb46d4d).withValues(alpha: .35)),
            borderRadius: BorderRadius.circular(9)),
        child: Row(children: [
          const Icon(Icons.info_outline, size: 17, color: Color(0xffe0a35d)),
          const SizedBox(width: 10),
          Expanded(child: Text(message, style: const TextStyle(fontSize: 12))),
          TextButton(onPressed: onRetry, child: const Text('重試'))
        ]));
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState(
      {required this.icon,
      required this.title,
      required this.message,
      super.key});
  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) => Center(
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(icon, size: 42, color: Colors.white24),
        const SizedBox(height: 14),
        Text(title,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 7),
        Text(message,
            textAlign: TextAlign.center,
            style: TextStyle(color: kMutedInk, fontSize: 12))
      ]));
}
