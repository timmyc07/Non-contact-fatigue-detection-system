part of '../main.dart';

class SettingsView extends StatelessWidget {
  const SettingsView(
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
    final transitioning = state['analysis_transitioning'] == true ||
        state['auto_capture_starting'] == true;
    final cleanupPending = state['pipeline_cleanup_pending'] == true;
    final dirty = state['settings_dirty'] == true;
    final settingsKnown = state['settings_dirty'] is bool;
    final opacity = (state['overlay_opacity'] as num?)?.toDouble() ?? 55;
    final hotkeysSupported =
        (state['hotkey_registration'] as Map?)?['supported'] == true;
    return PanelPage(
      title: '系統設定',
      description: '調整監測、桌面顯示與個人偏好。變更會立即套用，儲存後於下次啟動沿用。',
      trailing: Wrap(
          spacing: 14,
          runSpacing: 10,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Semantics(
                liveRegion: true,
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(
                      !settingsKnown
                          ? Icons.sync
                          : dirty
                              ? Icons.edit_outlined
                              : Icons.check_circle_outline,
                      size: 16,
                      color: dirty ? const Color(0xffe9c46a) : kAccent),
                  const SizedBox(width: 7),
                  Text(
                      !settingsKnown
                          ? '等待設定同步'
                          : dirty
                              ? '有未儲存的變更'
                              : '設定已儲存',
                      style: TextStyle(
                          fontSize: 12,
                          color: dirty ? const Color(0xffe9c46a) : kMutedInk)),
                ])),
            FilledButton.icon(
                onPressed: busy || transitioning ? null : () => onCommand('settings.save'),
                icon: const Icon(Icons.save_outlined, size: 18),
                label: const Text('儲存設定')),
          ]),
      children: [
        LayoutBuilder(builder: (context, constraints) {
          final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
          final width = constraints.maxWidth;
          final sectionWidth =
              width / textScale >= 920 ? (width - 16) / 2 : width;
          return Wrap(spacing: 16, runSpacing: 16, children: [
            for (final section in <Widget>[
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const PanelSectionTitle(
                        title: '分析與記錄', subtitle: '依使用需求選擇分析項目，可在監測中調整。'),
                    if (transitioning)
                      const Text('正在切換分析，完成後即可調整。',
                          style: TextStyle(color: kMutedInk, fontSize: 12)),
                    _SettingSwitch(
                      title: '行為警覺分析',
                      subtitle: '頭部姿態、眨眼、哈欠、注視與疲勞融合',
                      value: state['behavior_enabled'] == true,
                      enabled: !busy && !transitioning,
                      onChanged: (value) => onCommand('analysis.configure',
                          <String, dynamic>{'behavior_enabled': value}),
                    ),
                    const Divider(),
                    _SettingSwitch(
                      title: 'rPPG / HRV 分析',
                      subtitle: '非接觸式心率、HRV 與訊號品質',
                      value: state['rppg_enabled'] == true,
                      enabled: !busy && !transitioning,
                      onChanged: (value) => onCommand('analysis.configure',
                          <String, dynamic>{'rppg_enabled': value}),
                    ),
                    const Divider(),
                    _SettingSwitch(
                        title: '啟動時自動記錄',
                        subtitle: '監測管線啟動後同步建立指標與影片記錄',
                        value: state['auto_record'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand('preferences.configure',
                            <String, dynamic>{'auto_record': value})),
                    const Divider(),
                    _SettingSwitch(
                        title: '心跳帶真值校準',
                        subtitle: '僅校正 rPPG，不直接改變疲勞融合權重',
                        value: state['belt_calibration'] == true,
                        enabled: !busy && (!transitioning || state['belt_calibration'] == true),
                        onChanged: (value) => onCommand('preferences.configure',
                            <String, dynamic>{'belt_calibration': value})),
                  ])),
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    PanelSectionTitle(
                        title: '攝影機擷取',
                        subtitle: running
                            ? '監測運作中，請先停止監測再調整擷取設定。'
                            : '擷取設定會在下次啟動監測時使用。'),
                    _SettingDropdown(
                        label: '解析度',
                        value: state['resolution']?.toString(),
                        values: const [
                          '640×480',
                          '800×600',
                          '1280×720（720p）',
                          '1280×800',
                          '1920×1080（1080p）'
                        ],
                        enabled: !busy && !running && !cleanupPending,
                        onChanged: (value) => onCommand('camera.configure',
                            <String, dynamic>{'resolution': value})),
                    const SizedBox(height: 18),
                    _SettingDropdown(
                        label: '目標 FPS（固定）',
                        value: state['fps']?.toString(),
                        values: const ['30'],
                        enabled: false,
                        onChanged: (value) => onCommand('camera.configure',
                            <String, dynamic>{'fps': value})),
                    const SizedBox(height: 18),
                    _SettingDropdown(
                        label: '影像後端',
                        value: state['backend']?.toString(),
                        values: const ['ffmpeg'],
                        enabled: !busy && !running && !cleanupPending,
                        onChanged: (value) => onCommand('camera.configure',
                            <String, dynamic>{'backend': value})),
                    const SizedBox(height: 10),
                    _SettingSwitch(
                        title: '水平翻轉',
                        subtitle: '修正鏡像攝影機方向',
                        value: state['horizontal_flip'] == true,
                        enabled: !busy && !running && !cleanupPending,
                        onChanged: (value) => onCommand('camera.configure',
                            <String, dynamic>{'horizontal_flip': value})),
                  ])),
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const PanelSectionTitle(
                        title: '桌面 Overlay', subtitle: '在其他工作視窗上持續查看監測資訊。'),
                    _SettingSwitch(
                        title: '全部 Overlay',
                        subtitle: '同步顯示或隱藏鏡頭與數值 Overlay',
                        value: state['overlay_all'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand('overlay.configure',
                            <String, dynamic>{'all': value})),
                    const Divider(),
                    _SettingSwitch(
                        title: '桌面鏡頭 Overlay',
                        subtitle: '顯示即時鏡頭與影像標註',
                        value: state['overlay_preview'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand('preferences.configure',
                            <String, dynamic>{'overlay_preview': value})),
                    const Divider(),
                    _SettingSwitch(
                        title: '桌面數值 Overlay',
                        subtitle: '顯示疲勞與生理訊號即時指標',
                        value: state['overlay_metrics'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand('preferences.configure',
                            <String, dynamic>{'overlay_metrics': value})),
                    const Divider(),
                    _SettingSwitch(
                        title: 'Overlay 點擊穿透',
                        subtitle: '鎖定後不攔截桌面滑鼠操作',
                        value: state['overlay_locked'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand('preferences.configure',
                            <String, dynamic>{'overlay_locked': value})),
                    const Divider(),
                    _OverlayOpacityControl(
                      value: opacity,
                      enabled: !busy,
                      onChanged: (value) => onCommand('overlay.configure',
                          <String, dynamic>{'opacity': value}),
                    ),
                  ])),
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const PanelSectionTitle(
                        title: '個人化與警報', subtitle: '管理個人資料、清醒基線與提醒方式。'),
                    Wrap(spacing: 10, runSpacing: 10, children: [
                      OutlinedButton.icon(
                        onPressed: busy || !running || transitioning
                              ? null
                              : () => onCommand('baseline.start'),
                          icon: const Icon(Icons.person_search_outlined),
                          label: const Text('記錄清醒基線')),
                      OutlinedButton.icon(
                          onPressed: busy || !hotkeysSupported
                              ? null
                              : () =>
                                  _showHotkeysDialog(context, state, onCommand),
                          icon: const Icon(Icons.keyboard_outlined),
                          label: const Text('快捷鍵')),
                      OutlinedButton.icon(
                          onPressed: busy
                              ? null
                              : () => _showUserProfileDialog(
                                  context, state, onCommand),
                          icon: const Icon(Icons.badge_outlined),
                          label: const Text('使用者資料')),
                      OutlinedButton.icon(
                          onPressed: busy
                              ? null
                              : () =>
                                  _showAlarmDialog(context, state, onCommand),
                          icon: const Icon(Icons.notifications_active_outlined),
                          label: const Text('警報器')),
                    ]),
                    const SizedBox(height: 14),
                    Text(running ? '請在清醒且臉部穩定可見時記錄個人基線。' : '開始監測後，即可記錄個人清醒基線。',
                        style: const TextStyle(
                            color: kMutedInk, fontSize: 12, height: 1.5)),
                    if (!hotkeysSupported) ...[
                      const SizedBox(height: 8),
                      const Text('此平台目前不支援全域快捷鍵。',
                          style: TextStyle(
                              color: kMutedInk, fontSize: 12, height: 1.5)),
                    ],
                  ])),
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const PanelSectionTitle(
                        title: '資料與連線', subtitle: '查看本機記錄與管理診斷服務。'),
                    Wrap(spacing: 10, runSpacing: 10, children: [
                      OutlinedButton.icon(
                          onPressed: busy
                              ? null
                              : () => onCommand('settings.action',
                                  <String, dynamic>{'action': 'recordings'}),
                          icon: const Icon(Icons.folder_open_outlined),
                          label: const Text('開啟記錄目錄')),
                      OutlinedButton.icon(
                          onPressed: busy
                              ? null
                              : () => onCommand('settings.action',
                                  <String, dynamic>{'action': 'web'}),
                          icon: const Icon(Icons.open_in_browser_outlined),
                          label: const Text('診斷服務')),
                    ]),
                    const SizedBox(height: 12),
                    const Divider(),
                    _SettingSwitch(
                        title: '允許區域網存取診斷服務',
                        subtitle: '僅在受信任網路啟用未加密 LAN 廣播',
                        value: state['web_allow_lan'] == true,
                        enabled: !busy,
                        onChanged: (value) => onCommand(
                                'settings.action', <String, dynamic>{
                              'action': 'web_lan',
                              'enabled': value
                            })),
                  ])),
              GlassPanel(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const PanelSectionTitle(
                        title: '重設設定', subtitle: '恢復指定項目的預設值，執行前會再次確認。'),
                    Wrap(spacing: 10, runSpacing: 10, children: [
                      OutlinedButton.icon(
                          onPressed: busy || transitioning || !hotkeysSupported
                              ? null
                              : () => _confirmSettingsReset(
                                  context, const ['hotkeys'], onCommand),
                          icon: const Icon(Icons.restore),
                          label: const Text('重設快捷鍵')),
                      OutlinedButton.icon(
                          onPressed: busy || transitioning
                              ? null
                              : () => _confirmSettingsReset(
                                  context, const ['user_profile'], onCommand),
                          icon: const Icon(Icons.restore),
                          label: const Text('重設使用者資料')),
                      OutlinedButton.icon(
                          onPressed: busy || transitioning
                              ? null
                              : () => _confirmSettingsReset(
                                  context, const ['alarm'], onCommand),
                          icon: const Icon(Icons.restore),
                          label: const Text('重設警報器')),
                    ]),
                    const SizedBox(height: 14),
                    const Divider(),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xffefa5a2),
                            side: const BorderSide(color: Color(0x66efa5a2))),
                        onPressed: busy || transitioning || cleanupPending
                            ? null
                            : () => _confirmSettingsReset(
                                context,
                                const [
                                  'hotkeys',
                                  'user_profile',
                                  'alarm',
                                  'camera',
                                  'toggles',
                                  'overlay',
                                  'web',
                                  'replay'
                                ],
                                onCommand),
                        icon: const Icon(Icons.restore_page),
                        label: const Text('全部重設')),
                  ])),
            ])
              SizedBox(width: sectionWidth, child: section),
          ]);
        }),
      ],
    );
  }
}
