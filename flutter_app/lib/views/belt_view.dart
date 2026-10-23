part of '../main.dart';

class ChestBeltView extends StatelessWidget {
  const ChestBeltView(
      {required this.metrics,
      required this.state,
      required this.busy,
      required this.onCommand,
      super.key});
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
    final config = state['belt_config'] is Map
        ? Map<String, dynamic>.from(state['belt_config'] as Map)
        : <String, dynamic>{};
    return PanelPage(
      title: '心跳帶設備',
      description: '心跳帶真值僅用於 rPPG 校準與訊號檢視，不納入疲勞融合分數。',
      children: [
        HeartRateBeltPanel(
            metrics: metrics,
            engineState: state,
            busy: busy,
            onCommand: onCommand),
        const SizedBox(height: 16),
        LayoutBuilder(builder: (context, constraints) {
          final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
          final width = constraints.maxWidth;
          final cardWidth = width / textScale >= 800 ? (width - 16) / 2 : width;
          return Wrap(spacing: 16, runSpacing: 16, children: [
            SizedBox(
                width: cardWidth,
                child: GlassPanel(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                      const PanelSectionTitle(
                          title: 'rPPG 校準', subtitle: '檢視心跳帶與影像心率的配對及校正狀態。'),
                      _BeltDetailRow(
                          label: '校準偏移',
                          value:
                              '${_number('calib_offset_bpm').toStringAsFixed(1)} BPM'),
                      _BeltDetailRow(
                          label: '原始殘差',
                          value:
                              '${_number('calib_raw_residual_bpm').toStringAsFixed(1)} BPM'),
                      _BeltDetailRow(
                          label: '校正後殘差',
                          value:
                              '${_number('calib_residual_bpm').toStringAsFixed(1)} BPM'),
                      _BeltDetailRow(
                          label: '信心 / 狀態',
                          value:
                              '${_text('calib_confidence')} / ${metrics['calib_converged'] == true ? '已收斂' : '暖機中'}'),
                      _BeltDetailRow(
                          label: '配對數', value: _text('calib_pairs_used', '0')),
                    ]))),
            SizedBox(
                width: cardWidth,
                child: GlassPanel(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                      const PanelSectionTitle(
                          title: '設備偏好', subtitle: '目前使用的裝置識別與資料記錄方式。'),
                      _BeltDetailRow(
                          label: '名稱前綴',
                          value: config['name_prefix']?.toString().isNotEmpty ==
                                  true
                              ? config['name_prefix'].toString()
                              : '未指定'),
                      _BeltDetailRow(
                          label: '指定位址',
                          value:
                              config['address']?.toString().isNotEmpty == true
                                  ? config['address'].toString()
                                  : '自動掃描'),
                      _BeltDetailRow(
                          label: '參數自適應',
                          value: config['rppg_param_tuning_enabled'] == true
                              ? '開啟'
                              : '關閉'),
                      _BeltDetailRow(
                          label: '同步錄製',
                          value:
                              config['capture_enabled'] == true ? '開啟' : '關閉'),
                      const SizedBox(height: 8),
                      const Text('此處僅供檢視。變更設備識別或同步錄製方式，需由管理者調整後重新啟動。',
                          style: TextStyle(
                              color: kMutedInk, fontSize: 12, height: 1.5)),
                    ]))),
          ]);
        }),
      ],
    );
  }
}

class _BeltDetailRow extends StatelessWidget {
  const _BeltDetailRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: LayoutBuilder(builder: (context, constraints) {
        final labelText =
            Text(label, style: const TextStyle(color: kMutedInk, fontSize: 12));
        final valueText =
            Text(value, style: const TextStyle(fontSize: 13, height: 1.5));
        if (constraints.maxWidth /
                (MediaQuery.textScalerOf(context).scale(14) / 14) <
            360) {
          return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [labelText, const SizedBox(height: 3), valueText]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 2, child: labelText),
          const SizedBox(width: 14),
          Expanded(flex: 3, child: valueText),
        ]);
      }));
}

class HeartRateBeltPanel extends StatelessWidget {
  const HeartRateBeltPanel(
      {required this.metrics,
      required this.engineState,
      required this.busy,
      required this.onCommand,
      super.key});
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> engineState;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;

  double _number(String key, [double fallback = 0]) =>
      (metrics[key] as num?)?.toDouble() ?? fallback;
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
    final canEnable = engineState['pipeline_running'] == true &&
        engineState['rppg_enabled'] == true &&
        engineState['analysis_transitioning'] != true &&
        engineState['auto_capture_starting'] != true;
    final contactSupported = metrics['belt_contact_supported'] == true;
    final contactDetected = metrics['belt_contact_detected'] == true;
    final contact =
        contactSupported ? (contactDetected ? '已接觸' : '未接觸') : '未提供';
    final battery = _number('belt_battery', -1);
    final rssi = _number('belt_rssi');
    final signalAge = _number('belt_signal_age_sec', -1);
    final connectedFor = _number('belt_connected_duration_sec', -1);
    final hrv = [
      'RMSSD ${_number('belt_hrv_rmssd') > 0 ? _number('belt_hrv_rmssd').toStringAsFixed(1) : '--'} ms',
      'SDNN ${_number('belt_hrv_sdnn') > 0 ? _number('belt_hrv_sdnn').toStringAsFixed(1) : '--'} ms',
      'LF/HF ${_number('belt_hrv_lf_hf') > 0 ? _number('belt_hrv_lf_hf').toStringAsFixed(2) : '--'}',
    ];

    return GlassPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          width: double.infinity,
          child: Wrap(
              spacing: 16,
              runSpacing: 12,
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                _BeltStatusPill(label: stateLabel, color: stateColor),
                FilledButton.tonalIcon(
                  onPressed: busy || (!calibrationEnabled && !canEnable)
                      ? null
                      : () => onCommand(
                              'preferences.configure', <String, dynamic>{
                            'belt_calibration': !calibrationEnabled
                          }),
                  icon: Icon(
                      calibrationEnabled
                          ? Icons.link_off_outlined
                          : Icons.link_outlined,
                      size: 17),
                  label: Text(calibrationEnabled ? '停用心跳帶' : '啟用心跳帶'),
                ),
              ]),
        ),
        const SizedBox(height: 16),
        Text(_text('belt_device_name', '未偵測到心跳帶'),
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(
            '${_text('belt_device_address')}  ·  ${_text('belt_sensor_location', '位置未知')}',
            style:
                const TextStyle(color: kMutedInk, fontSize: 12, height: 1.5)),
        if (!calibrationEnabled && !canEnable) ...[
          const SizedBox(height: 10),
          const Text('請先啟動監測並開啟 rPPG 分析，再啟用心跳帶。',
              style: TextStyle(color: kMutedInk, fontSize: 12, height: 1.5)),
        ],
        const SizedBox(height: 18),
        LayoutBuilder(builder: (context, constraints) {
          final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
          final columns =
              (constraints.maxWidth / (180 * textScale)).floor().clamp(1, 4);
          final width = (constraints.maxWidth - (columns - 1) * 10) / columns;
          return Wrap(spacing: 10, runSpacing: 10, children: [
            for (final readout in <Widget>[
              _BeltReadout(
                  label: '心率',
                  value: _number('belt_bpm') > 0
                      ? _number('belt_bpm').toStringAsFixed(0)
                      : '--',
                  suffix: 'BPM',
                  icon: Icons.favorite_outline,
                  accent: stateColor),
              _BeltReadout(
                  label: '擷取訊號',
                  value: signalAge >= 0 ? signalAge.toStringAsFixed(1) : '--',
                  suffix: '秒前',
                  icon: Icons.graphic_eq_outlined,
                  accent: connected ? kAccentBright : kMutedInk),
              _BeltReadout(
                  label: '感測器接觸',
                  value: contact,
                  suffix: '',
                  icon: Icons.sensors_outlined,
                  accent: contact == '未接觸'
                      ? const Color(0xffe77b78)
                      : kAccentBright),
              _BeltReadout(
                  label: '電量',
                  value: battery >= 0 ? battery.toStringAsFixed(0) : '--',
                  suffix: battery >= 0 ? '%' : '',
                  icon: Icons.battery_5_bar_outlined,
                  accent: kAccentBright),
              _BeltReadout(
                  label: 'RSSI',
                  value: rssi != 0 ? rssi.toStringAsFixed(0) : '--',
                  suffix: 'dBm',
                  icon: Icons.wifi_tethering_outlined,
                  accent: kAccentBright),
              _BeltReadout(
                  label: 'RR 樣本',
                  value: _text('belt_rr_count', '0'),
                  suffix: '筆',
                  icon: Icons.timeline_outlined,
                  accent: kAccentBright),
              _BeltReadout(
                  label: '通知封包',
                  value: _text('belt_notifications', '0'),
                  suffix: '筆',
                  icon: Icons.sync_alt_outlined,
                  accent: kAccentBright),
              _BeltReadout(
                  label: '連線時長',
                  value: connectedFor >= 0
                      ? (connectedFor / 60).toStringAsFixed(1)
                      : '--',
                  suffix: '分鐘',
                  icon: Icons.timer_outlined,
                  accent: kAccentBright),
            ])
              SizedBox(width: width, child: readout),
          ]);
        }),
        const SizedBox(height: 16),
        const Divider(),
        const SizedBox(height: 8),
        const Text('心率變異 HRV',
            style: TextStyle(color: kMutedInk, fontSize: 12)),
        const SizedBox(height: 8),
        Wrap(spacing: 24, runSpacing: 10, children: [
          for (final reading in hrv)
            Text(reading, style: const TextStyle(fontSize: 13, height: 1.5)),
        ]),
        if (_text('belt_last_error', '').isNotEmpty) ...[
          const SizedBox(height: 9),
          Text('錯誤：${_text('belt_last_error')}',
              style: const TextStyle(
                  color: Color(0xffe77b78), fontSize: 12, height: 1.5)),
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
  Widget build(BuildContext context) => Container(
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
        Text(label,
            style: TextStyle(
                color: color, fontSize: 11, fontWeight: FontWeight.w700))
      ]));
}

class _BeltReadout extends StatelessWidget {
  const _BeltReadout(
      {required this.label,
      required this.value,
      required this.suffix,
      required this.icon,
      required this.accent});
  final String label;
  final String value;
  final String suffix;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
            color: kBackgroundDeep,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: kLine)),
        child: Row(children: [
          Icon(icon, size: 17, color: accent),
          const SizedBox(width: 9),
          Expanded(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                Text(label,
                    style: const TextStyle(color: kMutedInk, fontSize: 11)),
                const SizedBox(height: 5),
                Wrap(
                    spacing: 4,
                    runSpacing: 2,
                    crossAxisAlignment: WrapCrossAlignment.end,
                    children: [
                      Text(value,
                          style: const TextStyle(
                              fontSize: 20, fontWeight: FontWeight.w700)),
                      if (suffix.isNotEmpty)
                        Text(suffix,
                            style: const TextStyle(
                                color: kMutedInk, fontSize: 11)),
                    ]),
              ])),
        ]),
      );
}
