part of '../main.dart';

class PlaybackView extends StatelessWidget {
  const PlaybackView(
      {required this.recordings,
      required this.selected,
      required this.rows,
      required this.busy,
      required this.state,
      required this.onCommand,
      required this.onRefresh,
      required this.onOpen,
      required this.onClose,
      required this.onPickReplayFolder,
      required this.offset,
      required this.total,
      required this.startTimestamp,
      required this.onPage,
      super.key});
  final List<Map<String, dynamic>> recordings;
  final Map<String, dynamic>? selected;
  final List<Map<String, dynamic>> rows;
  final bool busy;
  final Map<String, dynamic> state;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;
  final Future<void> Function() onRefresh;
  final Future<void> Function(Map<String, dynamic>) onOpen;
  final VoidCallback onClose;
  final Future<String?> Function() onPickReplayFolder;
  final int offset;
  final int total;
  final double startTimestamp;
  final Future<void> Function(int) onPage;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => CustomScrollView(
        key:
            PageStorageKey(selected == null ? 'recordings' : 'playback-detail'),
        slivers: [
          SliverPadding(
            padding: EdgeInsets.fromLTRB(constraints.maxWidth < 600 ? 18 : 30,
                28, constraints.maxWidth < 600 ? 18 : 30, 30),
            sliver: SliverMainAxisGroup(slivers: [
              SliverToBoxAdapter(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Expanded(
                          child: Text('歷史回放',
                              style: Theme.of(context)
                                  .textTheme
                                  .headlineSmall
                                  ?.copyWith(fontWeight: FontWeight.w800))),
                      IconButton(
                          onPressed: busy ? null : onRefresh,
                          tooltip: '重新整理',
                          icon: const Icon(Icons.refresh)),
                    ]),
                    const SizedBox(height: 7),
                    const Text('檢視監測記錄，或從影片資料夾啟動離線回測。',
                        style: TextStyle(color: kMutedInk, fontSize: 13)),
                    const SizedBox(height: 24),
                    _ReplayControlPanel(
                        state: state,
                        busy: busy,
                        onCommand: onCommand,
                        onPickReplayFolder: onPickReplayFolder),
                    const SizedBox(height: 24),
                    if (selected == null) ...[
                      Text('監測記錄 · ${recordings.length} 段',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 12),
                    ],
                  ],
                ),
              ),
              if (selected != null)
                _PlaybackDetail(
                    recording: selected!,
                    rows: rows,
                    busy: busy,
                    offset: offset,
                    total: total,
                    startTimestamp: startTimestamp,
                    onPage: onPage,
                    onClose: onClose)
              else if (recordings.isEmpty)
                const SliverToBoxAdapter(
                  child: EmptyState(
                      icon: Icons.inbox_outlined,
                      title: '尚無回放資料',
                      message: '開始監測並記錄後，即可在這裡檢視工作階段。'),
                )
              else
                SliverList.builder(
                  itemCount: recordings.length,
                  itemBuilder: (context, index) {
                    final item = recordings[index];
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: GlassPanel(
                        child: ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.movie_outlined,
                              color: kAccentBright),
                          title: Text(
                              item['session_name']?.toString() ?? '未命名工作階段',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis),
                          subtitle: Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                                '${item['duration_str'] ?? '--'}  ·  ${item['record_count'] ?? 0} 筆指標',
                                style: const TextStyle(color: kMutedInk)),
                          ),
                          trailing:
                              const Icon(Icons.chevron_right, color: kMutedInk),
                          onTap: busy ? null : () => onOpen(item),
                        ),
                      ),
                    );
                  },
                ),
            ]),
          ),
        ],
      ),
    );
  }
}

class _ReplayControlPanel extends StatefulWidget {
  const _ReplayControlPanel(
      {required this.state,
      required this.busy,
      required this.onCommand,
      required this.onPickReplayFolder});
  final Map<String, dynamic> state;
  final bool busy;
  final Future<void> Function(String, [Map<String, dynamic>?]) onCommand;
  final Future<String?> Function() onPickReplayFolder;

  @override
  State<_ReplayControlPanel> createState() => _ReplayControlPanelState();
}

class _ReplayControlPanelState extends State<_ReplayControlPanel> {
  late final TextEditingController _pathController;
  late final FocusNode _pathFocusNode;

  @override
  void initState() {
    super.initState();
    _pathController = TextEditingController(
        text: widget.state['replay_dataset_dir']?.toString() ?? '');
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

  Future<void> _pickFolder() async {
    try {
      final path = await widget.onPickReplayFolder();
      if (!mounted || path == null || path.isEmpty) return;
      _pathController.text = path;
      await widget
          .onCommand('replay.configure', <String, dynamic>{'path': path});
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          content: Text('無法選擇資料夾：$error'),
          backgroundColor: const Color(0xff8f3f4d),
        ));
    }
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
        Wrap(spacing: 16, runSpacing: 8, children: [
          const Text('批次回測',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          if (running)
            Text(
                '${stopping ? '停止中' : '處理中'} · $done / ${total > 0 ? total : '--'}',
                style: const TextStyle(
                    color: kAccentBright, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 6),
        const Text('選擇影片來源，沿用即時監測的分析流程。',
            style: TextStyle(color: kMutedInk, fontSize: 12)),
        const SizedBox(height: 12),
        TextField(
            controller: _pathController,
            focusNode: _pathFocusNode,
            enabled: !running && !widget.busy,
            decoration: const InputDecoration(
                labelText: '影片資料夾',
                hintText: '輸入資料夾路徑',
                border: OutlineInputBorder(),
                isDense: true)),
        const SizedBox(height: 4),
        Wrap(spacing: 6, children: [
          IconButton(
              onPressed: running || widget.busy ? null : _pickFolder,
              tooltip: '選擇資料夾',
              icon: const Icon(Icons.folder_open_outlined)),
          IconButton(
              onPressed: running || widget.busy
                  ? null
                  : () => widget.onCommand('replay.configure',
                      <String, dynamic>{'path': _pathController.text}),
              tooltip: '套用路徑',
              icon: const Icon(Icons.check_circle_outline)),
        ]),
        const SizedBox(height: 8),
        LayoutBuilder(builder: (context, constraints) {
          final jobsControl = Row(mainAxisSize: MainAxisSize.min, children: [
            const Text('平行數'),
            const SizedBox(width: 16),
            DropdownButton<int>(
                value: <int>[1, 2, 3, 4].contains(jobs) ? jobs : 2,
                items: const [1, 2, 3, 4]
                    .map((value) => DropdownMenuItem<int>(
                        value: value, child: Text('$value')))
                    .toList(),
                onChanged: running || widget.busy
                    ? null
                    : (value) {
                        if (value != null) {
                          widget.onCommand('replay.configure',
                              <String, dynamic>{'jobs': value});
                        }
                      }),
          ]);
          final annotatedControl = SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              title: const Text('輸出標註影片'),
              value: annotated,
              onChanged: running || widget.busy
                  ? null
                  : (value) => widget.onCommand('replay.configure',
                      <String, dynamic>{'annotated': value}));
          if (constraints.maxWidth < 560) {
            return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [jobsControl, annotatedControl]);
          }
          return Row(children: [
            jobsControl,
            const SizedBox(width: 28),
            Expanded(child: annotatedControl),
          ]);
        }),
        const SizedBox(height: 12),
        Wrap(spacing: 10, runSpacing: 10, children: [
          FilledButton.icon(
              onPressed: running || widget.busy
                  ? null
                  : () => widget.onCommand('replay.set',
                      <String, dynamic>{'enabled': true, 'mode': 'single'}),
              icon: const Icon(Icons.play_arrow),
              label: const Text('開始批次')),
          OutlinedButton.icon(
              onPressed: running || widget.busy
                  ? null
                  : () => widget.onCommand('replay.set',
                      <String, dynamic>{'enabled': true, 'mode': 'parallel'}),
              icon: const Icon(Icons.speed_outlined),
              label: const Text('平行驗證')),
          OutlinedButton.icon(
              onPressed: !running || stopping || widget.busy
                  ? null
                  : () => widget.onCommand(
                      'replay.set', <String, dynamic>{'enabled': false}),
              icon: const Icon(Icons.stop),
              label: Text(stopping ? '停止中' : '停止')),
        ]),
        if (running) ...[
          const SizedBox(height: 16),
          LinearProgressIndicator(
              value: total > 0 ? (done / total).clamp(0, 1) : null,
              semanticsLabel: '批次回測進度',
              semanticsValue: '$done / $total'),
        ],
        const SizedBox(height: 12),
        Text(widget.state['replay_current']?.toString() ?? '目前影片：--',
            style: const TextStyle(color: kMutedInk, fontSize: 12)),
        if ((widget.state['replay_parallel_status']?.toString() ?? '')
            .isNotEmpty)
          Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(widget.state['replay_parallel_status'].toString(),
                  style: const TextStyle(color: kMutedInk, fontSize: 12),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis)),
        if ((widget.state['replay_result']?.toString() ?? '').isNotEmpty &&
            widget.state['replay_result'] != '摘要檔：--')
          Padding(
              padding: const EdgeInsets.only(top: 5),
              child: Text(widget.state['replay_result'].toString(),
                  style: const TextStyle(color: kMutedInk, fontSize: 12),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis)),
      ]),
    );
  }
}

class _PlaybackDetail extends StatelessWidget {
  const _PlaybackDetail(
      {required this.recording,
      required this.rows,
      required this.busy,
      required this.offset,
      required this.total,
      required this.startTimestamp,
      required this.onPage,
      required this.onClose});
  final Map<String, dynamic> recording;
  final List<Map<String, dynamic>> rows;
  final bool busy;
  final VoidCallback onClose;
  final int offset;
  final int total;
  final double startTimestamp;
  final Future<void> Function(int) onPage;

  @override
  Widget build(BuildContext context) {
    return SliverMainAxisGroup(slivers: [
      SliverToBoxAdapter(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              IconButton(
                  onPressed: onClose,
                  tooltip: '返回回放清單',
                  icon: const Icon(Icons.arrow_back)),
              const SizedBox(width: 4),
              Expanded(
                  child: Text(recording['session_name']?.toString() ?? '回放指標',
                      style: Theme.of(context).textTheme.titleLarge)),
            ]),
            const SizedBox(height: 6),
            Text(
                '${recording['duration_str'] ?? '--'}  ·  ${recording['record_count'] ?? 0} 筆指標',
                style: const TextStyle(color: kMutedInk)),
            const SizedBox(height: 16),
            if (busy) ...[
              const LinearProgressIndicator(minHeight: 2),
              const SizedBox(height: 10),
              const Text('正在讀取監測指標…', style: TextStyle(color: kMutedInk)),
              const SizedBox(height: 14),
            ],
          ],
        ),
      ),
      if (rows.isEmpty && !busy)
        const SliverToBoxAdapter(
          child: EmptyState(
              icon: Icons.query_stats,
              title: '沒有可顯示的指標',
              message: '這段記錄尚未產生可用的監測指標。'),
        )
      else
        SliverList.builder(
          itemCount: rows.length,
          itemBuilder: (_, index) {
            final row = rows[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: GlassPanel(
                child: Wrap(
                  spacing: 24,
                  runSpacing: 10,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                        '${(((row['timestamp'] as num?)?.toDouble() ?? startTimestamp) - startTimestamp).toStringAsFixed(1)} s',
                        style: const TextStyle(
                            color: kAccentBright, fontWeight: FontWeight.w700)),
                    Text('狀態 ${row['status'] ?? '--'}',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text(
                        'EAR ${((row['ear'] as num?)?.toDouble() ?? 0).toStringAsFixed(2)}',
                        style: const TextStyle(color: kMutedInk)),
                    Text(
                        'BPM ${((row['bpm'] as num?)?.toDouble() ?? 0).toStringAsFixed(0)}',
                        style: const TextStyle(color: kMutedInk)),
                    Text(
                        'PERCLOS ${(((row['perclos'] as num?)?.toDouble() ?? 0) * 100).toStringAsFixed(1)}%',
                        style: const TextStyle(color: kMutedInk)),
                  ],
                ),
              ),
            );
          },
        ),
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                  '${rows.isEmpty ? 0 : offset + 1}–${offset + rows.length} / $total 筆'),
              TextButton(
                  onPressed: busy || offset == 0
                      ? null
                      : () => onPage((offset - 200).clamp(0, total)),
                  child: const Text('上一頁')),
              TextButton(
                  onPressed: busy || offset + rows.length >= total
                      ? null
                      : () => onPage(offset + rows.length),
                  child: const Text('下一頁')),
            ],
          ),
        ),
      ),
    ]);
  }
}
