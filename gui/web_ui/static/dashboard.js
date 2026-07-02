/**
 * rPPG Web儀表板 - Socket.IO客戶端邏輯
 * 處理實時數據同步、雙波形圖表和完整回放功能
 *
 * 效能優化 v2:
 *  - overlay canvas 繪製垂直指示線（不再觸發 chart.update）
 *  - DOM 元素快取，seekTo() 零 getElementById 查詢
 *  - requestAnimationFrame 播放迴圈，與螢幕刷新率同步
 */

// ============ Tab 切換 ============
function switchTab(tabName, evt) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    const tab = document.getElementById('tab-' + tabName);
    if (tab) tab.classList.add('active');
    const src = evt ? evt.currentTarget : (window.event ? window.event.currentTarget : null);
    if (src) src.classList.add('active');
    setTimeout(() => {
        if (pulseWaveformChart) pulseWaveformChart.resize();
        if (psdSpectrumChart) psdSpectrumChart.resize();
        if (pbChartHR) { pbChartHR.resize(); syncOverlaySize(pbChartHR, _overlayHR); }
        if (pbChartEye) { pbChartEye.resize(); syncOverlaySize(pbChartEye, _overlayEye); }
    }, 100);
}

// ============ 子分頁切換（歷史回放內：本地 / 雲端） ============
function switchSubTab(name) {
    document.querySelectorAll('.sub-tab-panel').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.sub-tab-btn').forEach(el => el.classList.remove('active'));
    const panel = document.getElementById('sub-panel-' + name);
    if (panel) panel.classList.add('active');
    const btn = document.getElementById('sub-tab-' + name + '-btn');
    if (btn) btn.classList.add('active');
    setTimeout(() => {
        if (pbChartHR) { pbChartHR.resize(); syncOverlaySize(pbChartHR, _overlayHR); }
        if (pbChartEye) { pbChartEye.resize(); syncOverlaySize(pbChartEye, _overlayEye); }
    }, 100);
}

// ============ 即時監測 ============
let socket = null;
let isConnected = false;
let lastMetricsTime = 0;
let pulseWaveformChart = null;
let psdSpectrumChart = null;

function extractMetricsPayload(data) {
    if (!data) return null;
    const packet = data.metrics || data;
    return packet && typeof packet === 'object' ? packet : null;
}

function applyLiveMetrics(packet) {
    const m = extractMetricsPayload(packet);
    if (!m) return;
    const running = m.pipeline_running !== false;
    lastMetricsTime = Date.now();
    updatePipelineStatus(running, m);
    updateMetricsDisplay(m);
    updateDualWaveforms(m);
}

function initSocket() {
    if (socket) {
        socket.removeAllListeners();
        socket.disconnect();
        socket = null;
    }
    socket = io({
        transports: ['polling', 'websocket'],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
    });
    socket.on('connect', () => {
        isConnected = true;
        updateConnectionStatus(true);
        socket.emit('request_metrics');
    });
    socket.on('disconnect', () => {
        isConnected = false;
        updateConnectionStatus(false);
        updatePipelineStatus(false);
    });
    socket.on('connect_error', () => {
        isConnected = false;
        updateConnectionStatus(false);
    });
    socket.on('metrics_update', (data) => {
        applyLiveMetrics(data);
    });
    socket.on('metrics_history', (data) => {
        const history = Array.isArray(data && data.data) ? data.data : [];
        const latest = data && data.latest ? data.latest : history[history.length - 1];
        applyLiveMetrics(latest);
    });
    // 鏡頭幀串流（目標 30 FPS JPEG）
    socket.on('frame_update', (data) => {
        if (data.frame) {
            _updatePreviewFrame(data.frame);
        }
    });
}

// ============ 鏡頭預覽 ============
let _previewImg = null;
let _previewPlaceholder = null;
let _previewFpsBadge = null;
let _previewFrameCount = 0;
let _previewFpsLast = performance.now();

function _updatePreviewFrame(b64) {
    // 頁面隱藏時跳過幀更新，避免無意義的 DOM 操作
    if (document.hidden) return;

    if (!_previewImg) {
        _previewImg = document.getElementById('preview-frame');
        _previewPlaceholder = document.getElementById('preview-placeholder');
        _previewFpsBadge = document.getElementById('preview-fps');
    }
    if (!_previewImg) return;

    _previewImg.src = `data:image/jpeg;base64,${b64}`;
    _previewImg.style.display = '';
    if (_previewPlaceholder) _previewPlaceholder.style.display = 'none';
    if (_previewFpsBadge) _previewFpsBadge.style.display = '';

    // 計算實際接收幀率
    _previewFrameCount++;
    const now = performance.now();
    if (now - _previewFpsLast >= 1000) {
        if (_previewFpsBadge) _previewFpsBadge.textContent = _previewFrameCount + ' fps';
        _previewFrameCount = 0;
        _previewFpsLast = now;
    }
}

function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    if (connected) {
        el.classList.remove('disconnected'); el.classList.add('connected');
        el.innerHTML = '<span class="status-dot"></span><span>已連接</span>';
    } else {
        el.classList.remove('connected'); el.classList.add('disconnected');
        el.innerHTML = '<span class="status-dot"></span><span>已斷開</span>';
    }
}

function updatePipelineStatus(running, m) {
    const bar = document.getElementById('system-status-bar');
    const icon = document.getElementById('pipeline-icon');
    const text = document.getElementById('pipeline-status-text');
    const info = document.getElementById('system-info-text');
    if (!bar) return;
    if (running && m) {
        if (m.face_detected && m.calibrated) {
            bar.style.background = 'rgba(34,197,94,0.15)'; bar.style.borderColor = 'rgba(34,197,94,0.3)';
            icon.style.color = '#22c55e'; text.textContent = '系統運行中 — 已校準，正在分析';
        } else if (m.face_detected) {
            bar.style.background = 'rgba(245,158,11,0.15)'; bar.style.borderColor = 'rgba(245,158,11,0.3)';
            icon.style.color = '#f59e0b';
            text.textContent = `系統運行中 — 校準中 (${m.calib_samples||0}/${m.calib_target||0})`;
        } else {
            bar.style.background = 'rgba(245,158,11,0.15)'; bar.style.borderColor = 'rgba(245,158,11,0.3)';
            icon.style.color = '#f59e0b'; text.textContent = '系統運行中 — 未偵測到臉部';
        }
        info.textContent = `FPS: ${m.fps?m.fps.toFixed(1):'--'} | rPPG: ${m.stress_enabled?'ON':'OFF'}`;
    } else {
        bar.style.background = 'rgba(239,68,68,0.15)'; bar.style.borderColor = 'rgba(239,68,68,0.3)';
        icon.style.color = '#ef4444'; text.textContent = '等待系統啟動...'; info.textContent = '';
    }
}

function updateMetricsDisplay(m) {
    setVal('ear-value', m.ear, v => v.toFixed(2));
    setVal('perclos-value', m.perclos, v => v.toFixed(1) + '%');
    setVal('blink-value', m.blink_count, v => v);
    const face = document.getElementById('face-status');
    if (face) {
        if (m.face_detected) {
            face.textContent = m.calibrated ? '已校準' : `校準中 ${m.calib_samples||0}/${m.calib_target||0}`;
            face.style.color = m.calibrated ? '#22c55e' : '#f59e0b';
        } else { face.textContent = '未偵測'; face.style.color = '#ef4444'; }
    }
    const eye = document.getElementById('eye-status');
    if (eye && m.status) { eye.textContent = m.status; eye.style.color = statusColor(m.status); }
    setVal('bpm-value', m.stress_bpm, v => v > 0 ? Math.round(v) : '--');
    setVal('rmssd-value', m.stress_rmssd, v => v > 0 ? v.toFixed(1) : '--');
    setVal('sdnn-value', m.stress_sdnn, v => v > 0 ? v.toFixed(1) : '--');
    setVal('lf-hf-value', m.stress_lf_hf, v => v > 0 ? v.toFixed(2) : '--');
    const lfhfWarn = document.getElementById('lf-hf-warn');
    if (lfhfWarn) { lfhfWarn.style.display = m.stress_lf_hf_window_ok ? 'none' : 'inline'; }
    setVal('sqi-value', m.stress_sqi, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-quality-value', m.stress_quality_score, v => v > 0 ? v.toFixed(2) : '--');
    setVal('fatigue-quality-value', m.fatigue_quality_score, v => v > 0 ? v.toFixed(2) : '--');
    setVal('peak-freq-value', m.stress_peak_freq, v => v > 0 ? v.toFixed(3) : '--');
    setVal('rppg-roi-valid-value', m.stress_roi_valid_count, v => v != null ? v : '--');
    setVal('fatigue-blend-calib-value', m.fatigue_blend_calib_progress, v => (v * 100).toFixed(0) + '%');
    setVal('rppg-roll-value', m.stress_pose_roll_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    setVal('rppg-yaw-value', m.stress_pose_yaw_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    setVal('rppg-pitch-value', m.stress_pose_pitch_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    setVal('rppg-forehead-weight-value', m.stress_roi_weight_forehead, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-lcheek-weight-value', m.stress_roi_weight_l_cheek, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-rcheek-weight-value', m.stress_roi_weight_r_cheek, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-glabella-weight-value', m.stress_roi_weight_glabella, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-jitter-value', m.stress_landmark_jitter_norm, v => v >= 0 ? v.toFixed(4) : '--');
    setVal('rppg-area-stability-value', m.stress_roi_area_stability, v => v > 0 ? v.toFixed(2) : '--');
    setVal('rppg-smoothing-value', m.stress_roi_smoothing_applied, v => v ? 'ON' : 'OFF');
    setVal('rppg-canonical-value', m.stress_canonical_roi_warp_used, v => v ? 'ON' : 'OFF');
    // v12: HRV 信心值 + IBI 偽影比例
    const confEl = document.getElementById('hrv-confidence-value');
    if (confEl && m.stress_hrv_confidence) {
        const conf = m.stress_hrv_confidence;
        confEl.textContent = conf === 'HIGH' ? '✓ 高' : conf === 'MEDIUM' ? '△ 中' : '✗ 低';
        confEl.style.color = conf === 'HIGH' ? '#22c55e' : conf === 'MEDIUM' ? '#f59e0b' : '#ef4444';
    }
    setVal('ibi-artifact-value', m.stress_ibi_artifact_ratio, v => v != null ? (v * 100).toFixed(1) + '%' : '--');
    const ss = document.getElementById('stress-enabled-status');
    if (ss) {
        if (m.stress_enabled) { ss.textContent = m.stress_has_face ? '運行中' : '等待臉部'; ss.style.color = m.stress_has_face ? '#22c55e' : '#f59e0b'; }
        else { ss.textContent = '未啟用'; ss.style.color = '#94a3b8'; }
    }
    // 生理來源（rPPG / 手錶）與心跳帶校準狀態可視化
    const physioSourceLabel = m.fatigue_mode === 'watch' ? '手錶' : 'rPPG';
    const srcColor = m.fatigue_mode === 'watch' ? '#3b82f6' : '#22c55e';
    ['physio-source-compact', 'physio-source-value'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = physioSourceLabel; el.style.color = srcColor; }
    });
    const cardSrc = document.getElementById('physio-card-source');
    if (cardSrc) cardSrc.textContent = physioSourceLabel;
    const beltStateMap = {
        connected: '已連線', scanning: '掃描中', connecting: '連線中',
        reconnecting: '重連中', error: '錯誤', idle: '待命', stopped: '停止',
    };
    const beltEl = document.getElementById('belt-status-value');
    if (beltEl) {
        if (m.belt_enabled) {
            let text = beltStateMap[m.belt_state] || m.belt_state || '--';
            if (m.belt_state === 'connected' && m.belt_device_name) text = m.belt_device_name;
            if (m.belt_state === 'connected' && !m.belt_contact_ok) text += '（接觸不良）';
            if (m.belt_state === 'connected' && m.belt_stale) text += '（無心率資料）';
            const beltOk = m.belt_contact_ok && !m.belt_stale;
            beltEl.textContent = text;
            beltEl.style.color = m.belt_state === 'connected' ? (beltOk ? '#22c55e' : '#f59e0b')
                : (m.belt_state === 'error' ? '#ef4444' : '#f59e0b');
        } else { beltEl.textContent = '--'; beltEl.style.color = '#94a3b8'; }
    }
    // rPPG 真值校準（心跳帶為參考，只調 rPPG、不進疲勞分數）
    const calibEl = document.getElementById('belt-calib-value');
    if (calibEl) {
        if (m.calib_active) {
            const off = (m.calib_offset_bpm >= 0 ? '+' : '') + Number(m.calib_offset_bpm).toFixed(1);
            let text = `校正 ${off} BPM`;
            let color = '#22c55e';
            if (m.calib_diverged) { text += '｜rPPG 偏差大，校正中'; color = '#f59e0b'; }
            else if (m.calib_converged) { text += `｜已收斂（信心 ${m.calib_confidence}）`; }
            else { text += `｜收斂中（${m.calib_pairs_used} 配對）`; color = '#f59e0b'; }
            calibEl.textContent = text;
            calibEl.style.color = color;
        } else { calibEl.textContent = '--'; calibEl.style.color = '#94a3b8'; }
    }
    ['belt-battery-compact', 'belt-battery-value'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (m.belt_enabled && m.belt_battery >= 0) {
            el.textContent = m.belt_battery + '%';
            el.style.color = m.belt_battery <= 15 ? '#ef4444' : m.belt_battery <= 30 ? '#f59e0b' : '#22c55e';
        } else { el.textContent = '--'; el.style.color = '#94a3b8'; }
    });
    const fs = document.getElementById('fusion-state');
    if (fs && m.fusion_state_zh) { fs.textContent = m.fusion_state_zh; fs.style.color = statusColor(m.fusion_state_zh); }
    setVal('fusion-confidence', m.fusion_confidence, v => (v*100).toFixed(0)+'%');
    setVal('stress-prob', m.stress_prob, v => (v*100).toFixed(0)+'%');
    setVal('fps-value', m.fps, v => v.toFixed(1));
    // 行為警覺指標
    const _deg = v => (v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '°' : '--');
    setVal('head-pitch-value', m.head_pitch, _deg);
    setVal('head-yaw-value',   m.head_yaw,   _deg);
    setVal('head-roll-value',  m.head_roll,  _deg);
    const ew = document.getElementById('early-warning');
    if (ew) {
        if (m.early_warning) { ew.textContent = '警示'; ew.style.color = '#ef4444'; }
        else { ew.textContent = '正常'; ew.style.color = '#22c55e'; }
    }
    setVal('blink-rate', m.blink_rate_pm, v => v > 0 ? v.toFixed(1) : '--');
    const msAlert = document.getElementById('microsleep-alert');
    if (msAlert) {
        if (m.microsleep_alert) { msAlert.textContent = '警示'; msAlert.style.color = '#ef4444'; }
        else { msAlert.textContent = '正常'; msAlert.style.color = '#22c55e'; }
    }
    setVal('microsleep-count', m.microsleep_count, v => v != null ? v : '--');
    setVal('yawn-count',       m.yawn_count,       v => v != null ? v : '--');
    setVal('mar-value',        m.mar,              v => v != null ? v.toFixed(3) : '--');
    setVal('gaze-stability-value', m.gaze_stability_index, v => v != null ? v.toFixed(2) : '--');
    setVal('fixation-duration', m.fixation_duration, v => v > 0 ? v.toFixed(1) : '--');
    setVal('saccade-freq', m.saccade_freq_pm, v => v > 0 ? v.toFixed(1) : '--');
    const sq = document.getElementById('squinting-status');
    if (sq) {
        if (m.is_squinting) { sq.textContent = '有'; sq.style.color = '#f59e0b'; }
        else { sq.textContent = '無'; sq.style.color = '#22c55e'; }
    }
    const fr = document.getElementById('frowning-status');
    if (fr) {
        if (m.is_frowning) { fr.textContent = '有'; fr.style.color = '#f59e0b'; }
        else { fr.textContent = '無'; fr.style.color = '#22c55e'; }
    }
    const it = document.getElementById('iris-trend');
    if (it) {
        const t = m.iris_ratio_trend;
        if (t == null) { it.textContent = '--'; it.style.color = '#94a3b8'; }
        else if (Math.abs(t) < 0.005) { it.textContent = '平穩'; it.style.color = '#94a3b8'; }
        else if (t > 0) { it.textContent = `擴張 +${t.toFixed(3)}`; it.style.color = '#22c55e'; }
        else { it.textContent = `收縮 ${t.toFixed(3)}`; it.style.color = '#f59e0b'; }
    }
    const gmf = document.getElementById('gaze-mental-fatigue');
    if (gmf) {
        if (m.gaze_mental_fatigue) { gmf.textContent = '● 注視固定'; gmf.style.color = '#ef4444'; }
        else { gmf.textContent = '○ 正常'; gmf.style.color = '#22c55e'; }
    }
    // 預覽區域的精簡指標
    setVal('bpm-large', m.stress_bpm, v => v > 0 ? Math.round(v) : '--');
    setVal('sqi-compact', m.stress_sqi, v => v > 0 ? v.toFixed(2) : '--');
    const sc = document.getElementById('stress-enabled-compact');
    if (sc) {
        if (m.stress_enabled) {
            if (!m.stress_warmup_done && m.stress_warmup_progress < 1.0) {
                sc.textContent = '暖機中'; sc.style.color = '#f59e0b';
            } else {
                sc.textContent = m.stress_has_face ? '運行中' : '等待臉部';
                sc.style.color = m.stress_has_face ? '#22c55e' : '#f59e0b';
            }
        } else { sc.textContent = '未啟用'; sc.style.color = '#94a3b8'; }
    }
    // rPPG 暖機進度條
    const wc = document.getElementById('warmup-bar-container');
    if (wc) {
        const prog = m.stress_warmup_progress || 0;
        const done = m.stress_warmup_done || false;
        if (m.stress_enabled && !done && prog < 1.0) {
            wc.style.display = 'block';
            const pct = Math.round(prog * 100);
            document.getElementById('warmup-pct').textContent = pct + '%';
            document.getElementById('warmup-fill').style.width = pct + '%';
        } else {
            wc.style.display = 'none';
        }
    }
    // 預覽區精簡疲勞指標
    const pvFs = document.getElementById('pv-fusion-state');
    if (pvFs && m.fusion_state_zh) { pvFs.textContent = m.fusion_state_zh; pvFs.style.color = statusColor(m.fusion_state_zh); }
    setVal('pv-fusion-confidence', m.fusion_confidence, v => (v*100).toFixed(0)+'%');
    const pvEye = document.getElementById('pv-eye-status');
    if (pvEye && m.status) { pvEye.textContent = m.status; pvEye.style.color = statusColor(m.status); }
    setVal('pv-stress-prob', m.stress_prob, v => (v*100).toFixed(0)+'%');
}

function setVal(id, val, fmt) {
    const el = document.getElementById(id);
    if (el && val != null) el.textContent = fmt(val);
}

function updateDualWaveforms(m) {
    if (m.stress_waveform && m.stress_waveform.length > 0) {
        const wf = m.stress_waveform, labels = wf.map((_,i) => i);
        if (!pulseWaveformChart) initPulseChart(labels, wf);
        else { pulseWaveformChart.data.labels = labels; pulseWaveformChart.data.datasets[0].data = wf; pulseWaveformChart.update('none'); }
    }
    if (m.stress_psd_freqs && m.stress_psd_freqs.length > 0 && m.stress_psd_values && m.stress_psd_values.length > 0) {
        const fl = m.stress_psd_freqs.map(f => f.toFixed(2)), pd = m.stress_psd_values;
        if (!psdSpectrumChart) initPsdChart(fl, pd);
        else { psdSpectrumChart.data.labels = fl; psdSpectrumChart.data.datasets[0].data = pd; psdSpectrumChart.update('none'); }
    }
}

function initPulseChart(labels, data) {
    const ctx = document.getElementById('pulseWaveformChart');
    if (!ctx) return;
    pulseWaveformChart = new Chart(ctx.getContext('2d'), {
        type:'line', data:{ labels, datasets:[{ label:'脈搏波形', data, borderColor:'#667eea', backgroundColor:'rgba(102,126,234,0.1)', borderWidth:2, fill:true, tension:0.3, pointRadius:0 }] },
        options:{ responsive:true, maintainAspectRatio:false, animation:false,
            plugins:{legend:{labels:{color:'#94a3b8'}}},
            scales:{ y:{ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,0.05)'}}, x:{ticks:{color:'#94a3b8',maxTicksLimit:10},grid:{color:'rgba(255,255,255,0.05)'}} }
        }
    });
}
function initPsdChart(labels, data) {
    const ctx = document.getElementById('psdSpectrumChart');
    if (!ctx) return;
    psdSpectrumChart = new Chart(ctx.getContext('2d'), {
        type:'line', data:{ labels, datasets:[{ label:'PSD 頻譜', data, borderColor:'#764ba2', backgroundColor:'rgba(118,75,162,0.1)', borderWidth:2, fill:true, tension:0.3, pointRadius:0 }] },
        options:{ responsive:true, maintainAspectRatio:false, animation:false,
            plugins:{legend:{labels:{color:'#94a3b8'}}},
            scales:{ y:{title:{display:true,text:'功率 (dB)',color:'#94a3b8'},ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,0.05)'}}, x:{title:{display:true,text:'頻率 (Hz)',color:'#94a3b8'},ticks:{color:'#94a3b8',maxTicksLimit:10},grid:{color:'rgba(255,255,255,0.05)'}} }
        }
    });
}

function statusColor(s) {
    if (!s) return '#f8fafc';
    const l = s.toLowerCase();
    if (l.includes('ok')||l.includes('正常')||l.includes('清醒')) return '#22c55e';
    if (l.includes('low_vigilance')||l.includes('低警覺')) return '#f59e0b';
    if (l.includes('critical')||l.includes('microsleep')||l.includes('危急')||l.includes('微睡眠')) return '#ef4444';
    if (l.includes('壓力')||l.includes('疲勞')||l.includes('輕度')||l.includes('tired')) return '#f59e0b';
    if (l.includes('昏睡')||l.includes('嚴重')||l.includes('危險')||l.includes('drowsy')) return '#ef4444';
    return '#f8fafc';
}

// 3秒超時偵測
setInterval(() => { if (lastMetricsTime > 0 && Date.now() - lastMetricsTime > 3000) updatePipelineStatus(false); }, 2000);

// ============ 回放功能 ============
let pbData = [];       // 所有數據點
let pbIndex = 0;       // 當前索引
let pbPlaying = false;
let pbAnimId = null;   // rAF handle
let pbChartHR = null;
let pbChartEye = null;

// --- 影片回放 ---
let pbVideoEl = null;           // <video> 元素快取
let pbVideoAvailable = false;   // 當前錄製是否有對應影片
let _recordingsList = [];       // 儲存錄製列表（含影片資訊）
let _allRecordings = [];
const VIDEO_SYNC_THRESHOLD = 0.08;  // 影片同步容忍偏差（秒）
const recordingState = {
    search: '',
    sort: 'desc',
    page: 1,
    pageSize: 8,
};

// --- overlay canvas（用於繪製垂直指示線，不觸發 chart.update） ---
let _overlayHR = null;
let _overlayEye = null;

// --- DOM 元素快取（seekTo 零查詢） ---
const _pb = {};
function _cachePbDom() {
    const ids = [
        'pb-slider', 'pb-time-current', 'pb-idx',
        'pb-ear', 'pb-perclos', 'pb-blink', 'pb-face',
        'pb-head-pitch', 'pb-head-yaw', 'pb-head-roll',
        'pb-early-warning', 'pb-blink-rate',
        'pb-microsleep-alert', 'pb-microsleep-count',
        'pb-yawn-count', 'pb-mar',
        'pb-fixation-duration', 'pb-saccade-freq',
        'pb-squinting-status', 'pb-frowning-status', 'pb-iris-trend',
        'pb-gaze-stability', 'pb-gaze-mental',
        'pb-bpm', 'pb-rmssd', 'pb-sdnn', 'pb-lfhf', 'pb-sqi', 'pb-prob',
        'pb-rppg-quality', 'pb-fatigue-quality', 'pb-roi-valid', 'pb-blend-calib',
        'pb-rppg-roll', 'pb-rppg-yaw', 'pb-rppg-pitch',
        'pb-rppg-fw', 'pb-rppg-lw', 'pb-rppg-rw', 'pb-rppg-gw',
        'pb-rppg-jitter', 'pb-rppg-area-stability', 'pb-rppg-smoothing', 'pb-rppg-canonical',
        'pb-fstate', 'pb-fconf', 'pb-estatus', 'pb-timestamp',
        'pb-play-icon', 'pb-speed', 'pb-time-total', 'pb-total',
        'pb-controls', 'pb-data', 'pb-loading'
    ];
    ids.forEach(id => { _pb[id] = document.getElementById(id); });
}

// --- 數值穩定化：防止微小變化導致數字閃爍 ---
// 每個指標有各自的變化閾值，只有超過閾值才更新顯示
const _displayed = {};  // key → 當前顯示的原始數值
const _displayThresholds = {
    'pb-ear': 0.005,    // EAR ±0.005 才更新（顯示 2 位小數）
    'pb-perclos': 0.3,  // PERCLOS ±0.3% 才更新
    'pb-bpm': 1.0,      // BPM ±1 才更新（顯示整數）
    'pb-rmssd': 0.5,    // RMSSD ±0.5ms 才更新
    'pb-sdnn': 0.5,     // SDNN ±0.5ms 才更新
    'pb-lfhf': 0.02,    // LF/HF ±0.02 才更新
    'pb-sqi': 0.02,     // SQI ±0.02 才更新
    'pb-rppg-quality': 0.02,
    'pb-fatigue-quality': 0.02,
    'pb-blend-calib': 1.0,
    'pb-prob': 1.5,     // 壓力概率 ±1.5% 才更新（顯示整數百分比）
    'pb-fconf': 1.5,    // 信心度 ±1.5% 才更新
    'pb-head-pitch': 0.2,
    'pb-head-yaw': 0.2,
    'pb-head-roll': 0.2,
    'pb-rppg-roll': 0.2,
    'pb-rppg-yaw': 0.2,
    'pb-rppg-pitch': 0.2,
    'pb-blink-rate': 0.2,
    'pb-fixation-duration': 0.2,
    'pb-saccade-freq': 0.2,
    'pb-mar': 0.01,
    'pb-gaze-stability': 0.02,
    'pb-rppg-fw': 0.02,
    'pb-rppg-lw': 0.02,
    'pb-rppg-rw': 0.02,
    'pb-rppg-gw': 0.02,
    'pb-rppg-jitter': 0.0005,
    'pb-rppg-area-stability': 0.02,
};

/**
 * 穩定化顯示 — 只有數值變化超過閾值才更新 DOM。
 * @param {string} key   - DOM 快取鍵（也用於穩定化追蹤）
 * @param {number|null} rawVal - 原始數值
 * @param {function} fmt  - 格式化函數 (rawVal → string)
 * @param {number} [threshold] - 覆寫閾值（可選）
 */
function _stableSet(key, rawVal, fmt, threshold) {
    const el = _pb[key];
    if (!el) return;
    if (rawVal == null) return;

    const thr = threshold !== undefined ? threshold : (_displayThresholds[key] || 0);
    const prev = _displayed[key];

    // 首次顯示、或從有效→無效（'--'）/無效→有效、或差異超過閾值
    const formatted = fmt(rawVal);
    if (prev === undefined || formatted === '--' || _displayed[key + '_text'] === '--'
        || Math.abs(rawVal - prev) >= thr) {
        _displayed[key] = rawVal;
        _displayed[key + '_text'] = formatted;
        el.textContent = formatted;
    }
}

/** 重置穩定化狀態（切換錄製檔或清除時） */
function _resetDisplayState() {
    for (const k in _displayed) delete _displayed[k];
}

// 刷新錄製列表（僅本地）
async function refreshRecordingList() {
    try {
        const json = await fetch('/api/recordings').then(r => r.json());
        const items = json.success ? (json.data || []) : [];
        const search = recordingState.search.trim().toLowerCase();
        const filtered = search
            ? items.filter(item => (item.session_name || '').toLowerCase().includes(search))
            : items;
        filtered.sort((a, b) => {
            const l = a.created || 0, r = b.created || 0;
            return recordingState.sort === 'asc' ? l - r : r - l;
        });
        _allRecordings = filtered;
        renderRecordingPage();
    } catch (e) { console.error('刷新列表失敗:', e); }
}

function renderRecordingPage() {
    const totalPages = Math.max(1, Math.ceil(_allRecordings.length / recordingState.pageSize));
    recordingState.page = Math.min(recordingState.page, totalPages);
    const start = (recordingState.page - 1) * recordingState.pageSize;
    const items = _allRecordings.slice(start, start + recordingState.pageSize);
    renderRecordingList(items);
    const pageInfo = document.getElementById('recording-page-info');
    if (pageInfo) pageInfo.textContent = `第 ${recordingState.page} / ${totalPages} 頁，共 ${_allRecordings.length} 筆`;
    const prev = document.getElementById('recording-prev-page-btn');
    const next = document.getElementById('recording-next-page-btn');
    if (prev) prev.disabled = recordingState.page <= 1;
    if (next) next.disabled = recordingState.page >= totalPages;
}

function createBadge(iconClass, label, unavailable = false) {
    const badge = document.createElement('span');
    badge.className = unavailable ? 'video-badge unavailable' : 'video-badge';
    const icon = document.createElement('i');
    icon.className = iconClass;
    badge.appendChild(icon);
    badge.append(` ${label}`);
    return badge;
}

function createRecordingTextRow(iconClass, text) {
    const row = document.createElement('span');
    const icon = document.createElement('i');
    icon.className = iconClass;
    row.appendChild(icon);
    row.append(` ${text}`);
    return row;
}

function applySafeThumbnail(img, url) {
    if (!url) return false;
    try {
        const parsed = new URL(url, window.location.origin);
        if (!['http:', 'https:'].includes(parsed.protocol)) return false;
        img.src = parsed.toString();
        return true;
    } catch (error) {
        console.warn('不合法的縮圖 URL', url, error);
        return false;
    }
}

function renderRecordingList(list) {
    const el = document.getElementById('recording-list');
    _recordingsList = list || [];
    el.replaceChildren();
    if (!list || list.length === 0) {
        const empty = document.createElement('div');
        empty.style.textAlign = 'center';
        empty.style.color = 'var(--md-sys-color-on-surface-variant)';
        empty.style.padding = '20px';
        const main = document.createElement('div');
        main.textContent = '沒有錄製檔案';
        empty.appendChild(main);
        el.appendChild(empty);
        return;
    }

    list.forEach((recording, index) => {
        const item = document.createElement('div');
        item.className = 'recording-item';
        item.dataset.idx = String(index);

        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.gap = '14px';
        row.style.alignItems = 'flex-start';

        const body = document.createElement('div');
        body.style.flex = '1';
        body.style.minWidth = '0';

        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.alignItems = 'center';
        header.style.gap = '10px';
        header.style.marginBottom = '6px';
        header.style.flexWrap = 'wrap';

        const dbIcon = document.createElement('i');
        dbIcon.className = 'fas fa-database';
        dbIcon.style.color = 'var(--md-sys-color-primary)';
        header.appendChild(dbIcon);

        const title = document.createElement('span');
        title.style.fontWeight = '600';
        title.style.color = 'var(--md-sys-color-on-surface)';
        title.textContent = recording.session_name || recording.created_str;
        header.appendChild(title);
        header.appendChild(createBadge(recording.has_video ? 'fas fa-video' : 'fas fa-video-slash', recording.has_video ? '有影片' : '無影片', !recording.has_video));

        const meta = document.createElement('div');
        meta.style.display = 'flex';
        meta.style.gap = '20px';
        meta.style.fontSize = '0.85rem';
        meta.style.color = 'var(--md-sys-color-on-surface-variant)';
        meta.style.flexWrap = 'wrap';
        meta.appendChild(createRecordingTextRow('fas fa-clock', recording.created_str));
        meta.appendChild(createRecordingTextRow('fas fa-stopwatch', recording.duration_str || `${(recording.duration_sec || 0).toFixed(1)} 秒`));
        meta.appendChild(createRecordingTextRow('fas fa-list-ol', `${recording.record_count || 0} 筆`));

        const filename = document.createElement('div');
        filename.style.marginTop = '6px';
        filename.style.fontSize = '0.8rem';
        filename.style.opacity = '0.6';
        filename.style.wordBreak = 'break-all';
        filename.textContent = recording.filename || recording.remote_video_path || '';

        body.appendChild(header);
        body.appendChild(meta);
        body.appendChild(filename);
        row.appendChild(body);

        // 已連線 File Browser 且為本地錄製：顯示上傳按鈕
        if (_fbConnected && recording.filename) {
            const recName = String(recording.filename).replace(/\.db$/, '');
            const uploadBtn = document.createElement('button');
            uploadBtn.title = '上傳至 File Browser 雲端';
            uploadBtn.style.cssText = 'flex-shrink:0;background:none;border:1px solid var(--md-sys-color-outline);border-radius:6px;padding:6px 12px;cursor:pointer;color:var(--md-sys-color-on-surface);display:flex;align-items:center;gap:4px;font-size:0.82rem;align-self:center;white-space:nowrap;';
            uploadBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">cloud_upload</span> 上傳';
            uploadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                fbUploadRecording(recName, uploadBtn);
            });
            row.appendChild(uploadBtn);
        }

        item.appendChild(row);
        item.addEventListener('click', () => selectRecording(index));
        el.appendChild(item);
    });
}

async function selectRecording(idx) {
    document.querySelectorAll('#recording-list .recording-item').forEach((el, i) => {
        el.classList.toggle('active', i === idx);
    });
    stopPlayback();

    _pb['pb-loading'].style.display = 'block';
    _pb['pb-controls'].style.display = 'none';
    _pb['pb-data'].style.display = 'none';

    const rec = _recordingsList[idx];
    // 顯示共用回放區（本地標籤）
    _showSharedPlayback(rec?.session_name || rec?.filename || `錄製 ${idx + 1}`, false);

    let dbPath = rec?.path;
    const videoSection = document.getElementById('pb-video-section');
    const videoPlaceholder = document.getElementById('pb-video-placeholder');
    if (!pbVideoEl) pbVideoEl = document.getElementById('pb-video');

    try {
        let videoUrl = null;
        try {
            videoUrl = await resolveRecordingVideoUrl(rec);
        } catch (error) {
            console.warn('取得影片 URL 失敗', error);
        }

        if (videoUrl) {
            pbVideoAvailable = true;
            pbVideoEl.src = videoUrl;
            pbVideoEl.onerror = () => {
                pbVideoAvailable = false;
                pbVideoEl.style.display = 'none';
                videoPlaceholder.style.display = 'flex';
                console.warn('影片載入失敗');
            };
            pbVideoEl.load();
            pbVideoEl.style.display = 'block';
            videoPlaceholder.style.display = 'none';
            videoSection.style.display = 'block';
        } else {
            pbVideoAvailable = false;
            pbVideoEl.removeAttribute('src');
            pbVideoEl.style.display = 'none';
            videoPlaceholder.style.display = 'flex';
            videoSection.style.display = 'block';
        }

        if (!dbPath && rec?.remote_db_path) {
            const cacheRes = await fetch('/api/cloud-recordings/cache-db', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ object_path: rec.remote_db_path }),
            });
            const cacheJson = await cacheRes.json();
            if (!cacheJson.success || !cacheJson.db_path) {
                throw new Error(cacheJson.error || '下載資料庫失敗');
            }
            dbPath = cacheJson.db_path;
        }

        if (!dbPath) {
            pbData = [];
            clearPlaybackDataView();
            return;
        }

        const res = await fetch(`/api/playback/full?db_path=${encodeURIComponent(dbPath)}`);
        const json = await res.json();
        if (!json.success || !json.data || json.data.length === 0) {
            throw new Error(json.error || '資料庫為空');
        }
        pbData = json.data;
        pbIndex = 0;
        _resetDisplayState();
        initPlaybackUI();
    } catch (error) {
        alert(`載入失敗: ${error.message}`);
    } finally {
        _pb['pb-loading'].style.display = 'none';
    }
}

async function resolveRecordingVideoUrl(rec) {
    if (!rec || !rec.has_video) {
        return null;
    }
    if (rec.video_route) {
        return rec.video_route;
    }
    if (rec.video_filename) {
        return `/api/video/${encodeURIComponent(rec.video_filename)}`;
    }
    if (rec.cloud_video_path || rec.remote_video_path) {
        const response = await fetch('/api/cloud-recordings/signed-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ object_path: rec.cloud_video_path || rec.remote_video_path }),
        });
        const json = await response.json();
        if (!json.success) {
            throw new Error(json.error || '建立影片 signed URL 失敗');
        }
        return json.url || null;
    }
    return rec.remote_video_url || null;
}

function clearPlaybackDataView() {
    _pb['pb-controls'].style.display = 'none';
    _pb['pb-data'].style.display = 'none';
}

function initPlaybackUI() {
    // 顯示控制區和數據區
    _pb['pb-controls'].style.display = 'block';
    _pb['pb-data'].style.display = 'block';

    // 設定進度條
    _pb['pb-slider'].max = pbData.length - 1;
    _pb['pb-slider'].value = 0;

    // 計算總時長
    const t0 = pbData[0].t;
    const tEnd = pbData[pbData.length - 1].t;
    _pb['pb-time-total'].textContent = fmtDuration(tEnd - t0);
    _pb['pb-total'].textContent = pbData.length;

    // 建立趨勢圖
    buildTrendCharts();

    // 顯示第一筆
    seekTo(0);
}

function seekTo(idx) {
    if (idx < 0) idx = 0;
    if (idx >= pbData.length) idx = pbData.length - 1;
    pbIndex = idx;
    const d = pbData[idx];
    const t0 = pbData[0].t;

    // 更新進度條 — 使用快取的 DOM 引用
    _pb['pb-slider'].value = idx;
    _pb['pb-time-current'].textContent = fmtDuration(d.t - t0);
    _pb['pb-idx'].textContent = idx + 1;

    // 更新數值卡片 — 穩定化顯示，微小變化不更新避免閃爍
    _stableSet('pb-ear', d.ear, v => v.toFixed(2));
    _stableSet('pb-perclos', d.perclos, v => v.toFixed(1) + '%');
    _setElText(_pb['pb-blink'], d.blink, v => v);  // 整數，無需穩定化

    const faceEl = _pb['pb-face'];
    if (faceEl) {
        if (d.face) { faceEl.textContent = d.cal ? '已校準' : '校準中'; faceEl.style.color = d.cal ? '#22c55e' : '#f59e0b'; }
        else { faceEl.textContent = '未偵測'; faceEl.style.color = '#ef4444'; }
    }
    const _deg = v => (v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '°' : '--');
    _stableSet('pb-head-pitch', d.head_pitch, _deg);
    _stableSet('pb-head-yaw', d.head_yaw, _deg);
    _stableSet('pb-head-roll', d.head_roll, _deg);
    const pbEarly = _pb['pb-early-warning'];
    if (pbEarly) {
        if (d.early_warning) { pbEarly.textContent = '警示'; pbEarly.style.color = '#ef4444'; }
        else { pbEarly.textContent = '正常'; pbEarly.style.color = '#22c55e'; }
    }
    _stableSet('pb-blink-rate', d.blink_rate_pm, v => v > 0 ? v.toFixed(1) : '--');
    const pbMsAlert = _pb['pb-microsleep-alert'];
    if (pbMsAlert) {
        if (d.microsleep_alert) { pbMsAlert.textContent = '警示'; pbMsAlert.style.color = '#ef4444'; }
        else { pbMsAlert.textContent = '正常'; pbMsAlert.style.color = '#22c55e'; }
    }
    _setElText(_pb['pb-microsleep-count'], d.microsleep_count, v => v != null ? v : '--');
    _setElText(_pb['pb-yawn-count'], d.yawn_count, v => v != null ? v : '--');
    _stableSet('pb-mar', d.mar, v => v != null ? v.toFixed(3) : '--');
    _stableSet('pb-fixation-duration', d.fixation_duration, v => v > 0 ? v.toFixed(1) : '--');
    _stableSet('pb-saccade-freq', d.saccade_freq_pm, v => v > 0 ? v.toFixed(1) : '--');
    const pbSq = _pb['pb-squinting-status'];
    if (pbSq) {
        if (d.is_squinting) { pbSq.textContent = '有'; pbSq.style.color = '#f59e0b'; }
        else { pbSq.textContent = '無'; pbSq.style.color = '#22c55e'; }
    }
    const pbFr = _pb['pb-frowning-status'];
    if (pbFr) {
        if (d.is_frowning) { pbFr.textContent = '有'; pbFr.style.color = '#f59e0b'; }
        else { pbFr.textContent = '無'; pbFr.style.color = '#22c55e'; }
    }
    const pbIris = _pb['pb-iris-trend'];
    if (pbIris) {
        const t = d.iris_ratio_trend;
        if (t == null) { pbIris.textContent = '--'; pbIris.style.color = '#94a3b8'; }
        else if (Math.abs(t) < 0.005) { pbIris.textContent = '平穩'; pbIris.style.color = '#94a3b8'; }
        else if (t > 0) { pbIris.textContent = `擴張 +${t.toFixed(3)}`; pbIris.style.color = '#22c55e'; }
        else { pbIris.textContent = `收縮 ${t.toFixed(3)}`; pbIris.style.color = '#f59e0b'; }
    }
    _stableSet('pb-gaze-stability', d.gaze_stability_index, v => v != null ? v.toFixed(2) : '--');
    const pbGaze = _pb['pb-gaze-mental'];
    if (pbGaze) {
        if (d.gaze_mental_fatigue) { pbGaze.textContent = '● 注視固定'; pbGaze.style.color = '#ef4444'; }
        else { pbGaze.textContent = '○ 正常'; pbGaze.style.color = '#22c55e'; }
    }
    _stableSet('pb-bpm', d.bpm, v => v > 0 ? Math.round(v) : '--');
    _stableSet('pb-rmssd', d.rmssd, v => v > 0 ? v.toFixed(1) : '--');
    _stableSet('pb-sdnn', d.sdnn, v => v > 0 ? v.toFixed(1) : '--');
    _stableSet('pb-lfhf', d.lf_hf, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-sqi', d.sqi, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-rppg-quality', d.rppg_quality_score, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-fatigue-quality', d.fatigue_quality_score, v => v > 0 ? v.toFixed(2) : '--');
    _setElText(_pb['pb-roi-valid'], d.rppg_roi_valid_count, v => v != null ? v : '--');
    _stableSet('pb-blend-calib', d.fatigue_blend_calib_progress * 100, v => v.toFixed(0) + '%');
    _stableSet('pb-prob', d.prob * 100, v => v > 0 ? v.toFixed(0) + '%' : '--');
    _stableSet('pb-rppg-roll', d.rppg_pose_roll_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    _stableSet('pb-rppg-yaw', d.rppg_pose_yaw_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    _stableSet('pb-rppg-pitch', d.rppg_pose_pitch_deg, v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}°`);
    _stableSet('pb-rppg-fw', d.rppg_roi_weight_forehead, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-rppg-lw', d.rppg_roi_weight_l_cheek, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-rppg-rw', d.rppg_roi_weight_r_cheek, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-rppg-gw', d.rppg_roi_weight_glabella, v => v > 0 ? v.toFixed(2) : '--');
    _stableSet('pb-rppg-jitter', d.rppg_landmark_jitter_norm, v => v >= 0 ? v.toFixed(4) : '--');
    _stableSet('pb-rppg-area-stability', d.rppg_roi_area_stability, v => v > 0 ? v.toFixed(2) : '--');
    _setElText(_pb['pb-rppg-smoothing'], d.rppg_roi_smoothing_applied, v => v ? 'ON' : 'OFF');
    _setElText(_pb['pb-rppg-canonical'], d.rppg_canonical_roi_warp_used, v => v ? 'ON' : 'OFF');

    // 文字狀態 — 只在實際改變時更新
    const fsEl = _pb['pb-fstate'];
    if (fsEl) {
        const newState = d.f_state || '--';
        if (fsEl.textContent !== newState) {
            fsEl.textContent = newState;
            fsEl.style.color = statusColor(newState);
        }
    }
    _stableSet('pb-fconf', d.f_conf * 100, v => v > 0 ? v.toFixed(0) + '%' : '--');


    const esEl = _pb['pb-estatus'];
    if (esEl) {
        const newStatus = d.status || '--';
        if (esEl.textContent !== newStatus) {
            esEl.textContent = newStatus;
            esEl.style.color = statusColor(newStatus);
        }
    }

    const tsEl = _pb['pb-timestamp'];
    if (tsEl) tsEl.textContent = new Date(d.t * 1000).toLocaleString('zh-TW');

    // 更新圖表上的垂直指示線（overlay canvas，不觸發 chart.update）
    drawChartIndicator(idx);

    // 同步影片位置
    if (pbVideoAvailable && pbVideoEl && pbData.length > 0) {
        const videoTime = d.t - pbData[0].t;
        if (Math.abs(pbVideoEl.currentTime - videoTime) > VIDEO_SYNC_THRESHOLD) {
            pbVideoEl.currentTime = videoTime;
        }
    }
}

/** 快取版 setVal — 直接接收 DOM 元素而非 id 字串 */
function _setElText(el, val, fmt) {
    if (el && val != null) el.textContent = fmt(val);
}

// 播放控制
function togglePlay() {
    if (pbPlaying) stopPlayback();
    else startPlayback();
}

/**
 * rAF 播放迴圈 — 以錄製時間戳為基準推進，與螢幕刷新率同步。
 * 相比 setTimeout：
 *  - 不會在背景分頁被節流
 *  - 高倍速下自然跳過中間幀而非排隊等待
 */
function startPlayback() {
    if (pbData.length === 0) return;
    if (pbIndex >= pbData.length - 1) pbIndex = 0;
    pbPlaying = true;
    _pb['pb-play-icon'].className = 'fas fa-pause';

    // 同步啟動影片播放
    if (pbVideoAvailable && pbVideoEl) {
        const speed = parseFloat(_pb['pb-speed'].value);
        pbVideoEl.playbackRate = speed;
        pbVideoEl.play().catch(() => {});
    }

    let lastRafTime = null;       // 上一幀 rAF 的 wall-clock 時間 (ms)
    let accumulatedTime = 0;      // 累積的錄製時間 (秒)

    function tick(rafTimestamp) {
        if (!pbPlaying || pbIndex >= pbData.length - 1) {
            stopPlayback();
            return;
        }

        if (lastRafTime === null) {
            lastRafTime = rafTimestamp;
            pbAnimId = requestAnimationFrame(tick);
            return;
        }

        const speed = parseFloat(_pb['pb-speed'].value);
        const wallDelta = (rafTimestamp - lastRafTime) / 1000;  // 秒
        lastRafTime = rafTimestamp;

        // 同步影片播放速度
        if (pbVideoAvailable && pbVideoEl && Math.abs(pbVideoEl.playbackRate - speed) > 0.01) {
            pbVideoEl.playbackRate = speed;
        }

        // 防止長時間掛起後的跳躍（例如切到其他分頁再回來）
        accumulatedTime += Math.min(wallDelta, 0.5) * speed;

        // 推進到對應的錄製時間點
        const targetTime = pbData[pbIndex].t + accumulatedTime;
        let newIdx = pbIndex;
        while (newIdx < pbData.length - 1 && pbData[newIdx + 1].t <= targetTime) {
            newIdx++;
        }

        if (newIdx !== pbIndex) {
            accumulatedTime -= (pbData[newIdx].t - pbData[pbIndex].t);
            seekTo(newIdx);
        }

        pbAnimId = requestAnimationFrame(tick);
    }

    pbAnimId = requestAnimationFrame(tick);
}

function stopPlayback() {
    pbPlaying = false;
    if (pbAnimId) { cancelAnimationFrame(pbAnimId); pbAnimId = null; }
    const icon = _pb['pb-play-icon'];
    if (icon) icon.className = 'fas fa-play';
    // 暫停影片
    if (pbVideoEl && !pbVideoEl.paused) {
        pbVideoEl.pause();
    }
}

function clearPlayback() {
    stopPlayback();
    pbData = [];
    pbIndex = 0;
    _resetDisplayState();
    _pb['pb-controls'].style.display = 'none';
    _pb['pb-data'].style.display = 'none';
    document.querySelectorAll('.recording-item').forEach(el => el.classList.remove('active'));
    if (pbChartHR) { pbChartHR.destroy(); pbChartHR = null; }
    if (pbChartEye) { pbChartEye.destroy(); pbChartEye = null; }
    if (_overlayHR) { _overlayHR.remove(); _overlayHR = null; }
    if (_overlayEye) { _overlayEye.remove(); _overlayEye = null; }
    // 清除影片
    pbVideoAvailable = false;
    if (pbVideoEl) {
        pbVideoEl.pause();
        pbVideoEl.removeAttribute('src');
        pbVideoEl.load();
    }
    const videoSection = document.getElementById('pb-video-section');
    if (videoSection) videoSection.style.display = 'none';
    // 隱藏共用回放區
    const shared = document.getElementById('shared-playback');
    if (shared) shared.style.display = 'none';
}

/** 顯示共用回放區並設定來源 banner */
function _showSharedPlayback(sourceName, isCloud) {
    const shared = document.getElementById('shared-playback');
    if (shared) shared.style.display = 'block';
    const nameEl = document.getElementById('pb-source-name');
    if (nameEl) nameEl.textContent = sourceName || '--';
    const badge = document.getElementById('pb-source-badge');
    if (badge) {
        badge.textContent = isCloud ? '雲端' : '本地';
        badge.className = 'pb-source-badge ' + (isCloud ? 'cloud' : 'local');
    }
}

// 格式化秒數為 mm:ss
function fmtDuration(sec) {
    if (!sec || sec < 0) return '00:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// ============ 趨勢圖 ============

// 不再使用 Chart.js plugin（會觸發 chart.update 重繪整張圖）
// 改用 overlay canvas 在圖表上方繪製指示線

/** 建立與 chart canvas 完全對齊的 overlay canvas */
function createOverlayCanvas(chartCanvas) {
    const overlay = document.createElement('canvas');
    overlay.style.position = 'absolute';
    overlay.style.left = '0';
    overlay.style.top = '0';
    overlay.style.pointerEvents = 'none';  // 不攔截滑鼠事件
    overlay.style.zIndex = '10';

    // 確保父容器是 relative 定位
    const parent = chartCanvas.parentElement;
    if (getComputedStyle(parent).position === 'static') {
        parent.style.position = 'relative';
    }
    parent.appendChild(overlay);

    syncOverlaySize(null, overlay, chartCanvas);
    return overlay;
}

/** 同步 overlay 尺寸到 chart canvas */
function syncOverlaySize(chart, overlay, canvasOverride) {
    const chartCanvas = canvasOverride || (chart ? chart.canvas : null);
    if (!chartCanvas || !overlay) return;
    overlay.width = chartCanvas.width;
    overlay.height = chartCanvas.height;
    overlay.style.width = chartCanvas.style.width;
    overlay.style.height = chartCanvas.style.height;
}

/** 在 overlay canvas 上繪製垂直指示線 + 圓點（不觸發 chart.update） */
function drawIndicatorOnOverlay(chart, overlay, sampledIdx) {
    if (!chart || !overlay) return;
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    if (sampledIdx == null || sampledIdx < 0) return;
    const meta = chart.getDatasetMeta(0);
    if (!meta.data[sampledIdx]) return;

    const x = meta.data[sampledIdx].x;
    const { top, bottom } = chart.chartArea;
    const dpr = window.devicePixelRatio || 1;

    ctx.save();
    // 垂直線
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.lineWidth = 2 * dpr;
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.stroke();

    // 各數據集的圓點
    chart.data.datasets.forEach((ds, di) => {
        const point = chart.getDatasetMeta(di).data[sampledIdx];
        if (point) {
            ctx.beginPath();
            ctx.arc(point.x, point.y, 5 * dpr, 0, Math.PI * 2);
            ctx.fillStyle = ds.borderColor;
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 1.5 * dpr;
            ctx.stroke();
        }
    });
    ctx.restore();
}

// 儲存降採樣步長供 drawChartIndicator 使用
let _chartStep = 1;

function buildTrendCharts() {
    if (pbChartHR) pbChartHR.destroy();
    if (pbChartEye) pbChartEye.destroy();
    if (_overlayHR) { _overlayHR.remove(); _overlayHR = null; }
    if (_overlayEye) { _overlayEye.remove(); _overlayEye = null; }

    const t0 = pbData[0].t;

    // 降採樣（超過 2000 點時）
    const step = pbData.length > 2000 ? Math.ceil(pbData.length / 2000) : 1;
    _chartStep = step;
    const sampledLabels = [], bpmArr = [], rmssdArr = [], earArr = [], perclosArr = [];
    for (let i = 0; i < pbData.length; i += step) {
        sampledLabels.push(fmtDuration(pbData[i].t - t0));
        bpmArr.push(pbData[i].bpm || null);
        rmssdArr.push(pbData[i].rmssd || null);
        earArr.push(pbData[i].ear || null);
        perclosArr.push(pbData[i].perclos || null);
    }

    const axisOpts = {
        ticks: { color: '#94a3b8', maxTicksLimit: 8 },
        grid: { color: 'rgba(255,255,255,0.05)' }
    };

    // HR / RMSSD 圖
    const ctx1 = document.getElementById('pb-chart-hr');
    if (ctx1) {
        pbChartHR = new Chart(ctx1.getContext('2d'), {
            type: 'line',
            data: {
                labels: sampledLabels,
                datasets: [
                    { label: 'BPM', data: bpmArr, borderColor: '#fb7185', backgroundColor: 'rgba(251,113,133,0.08)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
                    { label: 'RMSSD', data: rmssdArr, borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,0.08)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: { legend: { labels: { color: '#94a3b8' } } },
                scales: {
                    y: { ...axisOpts, position: 'left', title: { display: true, text: 'BPM', color: '#fb7185' } },
                    y1: { ...axisOpts, position: 'right', title: { display: true, text: 'RMSSD (ms)', color: '#38bdf8' }, grid: { drawOnChartArea: false } },
                    x: { ...axisOpts }
                }
            }
        });
        _overlayHR = createOverlayCanvas(ctx1);
    }

    // EAR / PERCLOS 圖
    const ctx2 = document.getElementById('pb-chart-eye');
    if (ctx2) {
        pbChartEye = new Chart(ctx2.getContext('2d'), {
            type: 'line',
            data: {
                labels: sampledLabels,
                datasets: [
                    { label: 'EAR', data: earArr, borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.08)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
                    { label: 'PERCLOS %', data: perclosArr, borderColor: '#fbbf24', backgroundColor: 'rgba(251,191,36,0.08)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: { legend: { labels: { color: '#94a3b8' } } },
                scales: {
                    y: { ...axisOpts, position: 'left', title: { display: true, text: 'EAR', color: '#a78bfa' } },
                    y1: { ...axisOpts, position: 'right', title: { display: true, text: 'PERCLOS %', color: '#fbbf24' }, grid: { drawOnChartArea: false } },
                    x: { ...axisOpts }
                }
            }
        });
        _overlayEye = createOverlayCanvas(ctx2);
    }
}

/** 繪製圖表指示線 — 只操作 overlay canvas，完全不觸發 chart.update() */
function drawChartIndicator(idx) {
    const sampledIdx = Math.round(idx / _chartStep);
    drawIndicatorOnOverlay(pbChartHR, _overlayHR, sampledIdx);
    drawIndicatorOnOverlay(pbChartEye, _overlayEye, sampledIdx);
}

// ============ 初始化 ============
document.addEventListener('DOMContentLoaded', () => {
    _cachePbDom();
    initSocket();
    refreshRecordingList();

    // 回放按鈕事件
    document.getElementById('refresh-list-btn').addEventListener('click', refreshRecordingList);
    document.getElementById('clear-playback-btn').addEventListener('click', clearPlayback);
    document.getElementById('pb-play-btn').addEventListener('click', togglePlay);
    document.getElementById('recording-search-input').addEventListener('input', (event) => {
        recordingState.search = event.target.value || '';
        recordingState.page = 1;
        refreshRecordingList();
    });
    document.getElementById('recording-sort-select').addEventListener('change', (event) => {
        recordingState.sort = event.target.value || 'desc';
        recordingState.page = 1;
        refreshRecordingList();
    });
    document.getElementById('recording-prev-page-btn').addEventListener('click', () => {
        recordingState.page = Math.max(1, recordingState.page - 1);
        renderRecordingPage();
    });
    document.getElementById('recording-next-page-btn').addEventListener('click', () => {
        recordingState.page += 1;
        renderRecordingPage();
    });

    // 進度條拖動
    _pb['pb-slider'].addEventListener('input', (e) => {
        stopPlayback();
        seekTo(parseInt(e.target.value));
    });

    const resyncPlaybackOverlays = () => {
        if (pbChartHR) syncOverlaySize(pbChartHR, _overlayHR);
        if (pbChartEye) syncOverlaySize(pbChartEye, _overlayEye);
    };
    window.addEventListener('resize', resyncPlaybackOverlays);
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(resyncPlaybackOverlays);
        const hrCanvas = document.getElementById('pb-chart-hr');
        const eyeCanvas = document.getElementById('pb-chart-eye');
        if (hrCanvas?.parentElement) observer.observe(hrCanvas.parentElement);
        if (eyeCanvas?.parentElement) observer.observe(eyeCanvas.parentElement);
    }

    window.addEventListener('online', () => {
        refreshRecordingList();
    });

    // ── File Browser 雲端回放事件綁定 ──
    document.getElementById('fb-connect-btn')?.addEventListener('click', fbConnect);
    document.getElementById('fb-disconnect-btn')?.addEventListener('click', fbDisconnect);
    document.getElementById('fb-refresh-btn')?.addEventListener('click', fbRefreshList);
    document.getElementById('cloud-recording-prev-page-btn')?.addEventListener('click', () => {
        _cloudRecState.page = Math.max(1, _cloudRecState.page - 1);
        _renderCloudPage();
    });
    document.getElementById('cloud-recording-next-page-btn')?.addEventListener('click', () => {
        _cloudRecState.page += 1;
        _renderCloudPage();
    });
    // Enter 鍵快速連線
    ['fb-url-input','fb-username-input','fb-password-input'].forEach(id => {
        document.getElementById(id)?.addEventListener('keydown', e => {
            if (e.key === 'Enter') fbConnect();
        });
    });
    // 頁面載入時：填入儲存的憑證，再檢查 server 連線狀態
    fbRestoreForm();
    fbCheckStatus();
});

// ============================================================
// File Browser 雲端回放
// ============================================================

const _cloudRecState = { page: 1, pageSize: 8 };
let _cloudRecList = [];   // 完整雲端列表（配對後）
let _fbConnected = false; // File Browser 連線狀態（影響本地列表的上傳按鈕）

// ── 憑證本地持久化（localStorage） ──

const _FB_STORAGE_KEY = 'fb_credentials';

function fbSaveCredentials(url, username, password, rememberPwd) {
    const data = { url, username, rememberPwd };
    if (rememberPwd) data.password = password;
    try { localStorage.setItem(_FB_STORAGE_KEY, JSON.stringify(data)); } catch (_) {}
}

function fbLoadCredentials() {
    try {
        const raw = localStorage.getItem(_FB_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (_) { return null; }
}

function fbClearCredentials() {
    try { localStorage.removeItem(_FB_STORAGE_KEY); } catch (_) {}
}

/** 頁面載入時將儲存的憑證填入表單 */
function fbRestoreForm() {
    const creds = fbLoadCredentials();
    if (!creds) return;
    const urlEl  = document.getElementById('fb-url-input');
    const userEl = document.getElementById('fb-username-input');
    const pwdEl  = document.getElementById('fb-password-input');
    const remEl  = document.getElementById('fb-remember-pwd');
    if (urlEl  && creds.url)      urlEl.value  = creds.url;
    if (userEl && creds.username) userEl.value = creds.username;
    if (remEl)  remEl.checked = !!creds.rememberPwd;
    if (pwdEl  && creds.rememberPwd && creds.password) pwdEl.value = creds.password;
}

// ── 連線管理 ──

async function fbCheckStatus() {
    try {
        const r = await fetch('/api/fb/status');
        const d = await r.json();
        _fbUpdateUI(d.authenticated, d.base_url, d.username);
        if (d.authenticated) fbRefreshList();
    } catch (_) {}
}

async function fbConnect() {
    const url      = (document.getElementById('fb-url-input')?.value || '').trim();
    const username = (document.getElementById('fb-username-input')?.value || '').trim();
    const password = (document.getElementById('fb-password-input')?.value || '').trim();
    const errEl    = document.getElementById('fb-connect-error');
    if (!url || !username || !password) {
        if (errEl) { errEl.textContent = '請填寫所有欄位'; errEl.style.display = 'block'; }
        return;
    }
    if (errEl) errEl.style.display = 'none';
    const btn = document.getElementById('fb-connect-btn');
    if (btn) { btn.disabled = true; btn.textContent = '連線中...'; }
    try {
        const r = await fetch('/api/fb/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, username, password })
        });
        const d = await r.json();
        if (d.success) {
            const rememberPwd = document.getElementById('fb-remember-pwd')?.checked || false;
            fbSaveCredentials(url, username, password, rememberPwd);
            _fbUpdateUI(true, url, username);
            fbRefreshList();
        } else {
            if (errEl) { errEl.textContent = d.error || '連線失敗'; errEl.style.display = 'block'; }
        }
    } catch (e) {
        if (errEl) { errEl.textContent = `網路錯誤: ${e.message}`; errEl.style.display = 'block'; }
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:18px;">login</span> 連線'; }
    }
}

async function fbDisconnect() {
    if (!confirm('確定要登出並切換帳號嗎？')) return;
    await fetch('/api/fb/logout', { method: 'POST' }).catch(() => {});
    // 保留 URL 和帳號，清除密碼（除非已勾選記住密碼）
    const creds = fbLoadCredentials();
    if (creds && !creds.rememberPwd) {
        fbSaveCredentials(creds.url, creds.username, '', false);
        const pwdEl = document.getElementById('fb-password-input');
        if (pwdEl) pwdEl.value = '';
    }
    _cloudRecList = [];
    _cloudRecState.page = 1;
    _fbUpdateUI(false);
    _renderCloudPage();
    clearPlayback();
}

function _fbUpdateUI(authenticated, baseUrl, username) {
    const connectSection = document.getElementById('fb-connect-section');
    const statusSection  = document.getElementById('fb-status-section');
    if (!connectSection || !statusSection) return;
    if (authenticated) {
        connectSection.style.display = 'none';
        statusSection.style.display = 'block';
        const urlEl  = document.getElementById('fb-status-url');
        const userEl = document.getElementById('fb-status-user');
        if (urlEl)  urlEl.textContent  = baseUrl  || '';
        if (userEl) userEl.textContent = username || '';
    } else {
        connectSection.style.display = 'block';
        statusSection.style.display  = 'none';
    }
    // 更新全域狀態，並重繪本地錄製列表（使上傳按鈕出現/消失）
    _fbConnected = !!authenticated;
    renderRecordingPage();
}

// ── 雲端列表 ──

async function fbRefreshList() {
    const listEl   = document.getElementById('cloud-recording-list');
    const loadEl   = document.getElementById('cloud-pb-loading');
    if (listEl) listEl.innerHTML = '';
    if (loadEl) loadEl.style.display = 'block';
    try {
        const r = await fetch('/api/fb/recordings');
        const d = await r.json();
        if (!d.success) throw new Error(d.error || '載入失敗');
        _cloudRecList = d.recordings || [];
        _cloudRecState.page = 1;
        _renderCloudPage();
    } catch (e) {
        if (listEl) listEl.innerHTML =
            `<div style="text-align:center;color:var(--md-sys-color-error);padding:20px;">${escapeHtml(e.message)}</div>`;
    } finally {
        if (loadEl) loadEl.style.display = 'none';
    }
}

function _renderCloudPage() {
    const listEl    = document.getElementById('cloud-recording-list');
    const pageInfoEl = document.getElementById('cloud-recording-page-info');
    const prevBtn   = document.getElementById('cloud-recording-prev-page-btn');
    const nextBtn   = document.getElementById('cloud-recording-next-page-btn');
    if (!listEl) return;

    const total      = _cloudRecList.length;
    const totalPages = Math.max(1, Math.ceil(total / _cloudRecState.pageSize));
    _cloudRecState.page = Math.min(Math.max(1, _cloudRecState.page), totalPages);

    const start = (_cloudRecState.page - 1) * _cloudRecState.pageSize;
    const items = _cloudRecList.slice(start, start + _cloudRecState.pageSize);

    if (pageInfoEl) pageInfoEl.textContent = `第 ${_cloudRecState.page} / ${totalPages} 頁 · 共 ${total} 筆`;
    if (prevBtn) prevBtn.disabled = _cloudRecState.page <= 1;
    if (nextBtn) nextBtn.disabled = _cloudRecState.page >= totalPages;

    listEl.replaceChildren();
    if (items.length === 0) {
        listEl.innerHTML = '<div style="text-align:center;color:var(--md-sys-color-on-surface-variant);padding:30px 20px;">'
            + '<span class="material-symbols-outlined" style="font-size:36px;opacity:0.4;display:block;margin-bottom:8px;">cloud_off</span>'
            + (total === 0 ? '雲端無錄製檔案' : '此頁無資料') + '</div>';
        return;
    }
    items.forEach((rec, i) => {
        const globalIdx = start + i;
        listEl.appendChild(_buildCloudRecItem(rec, globalIdx));
    });
}

function _buildCloudRecItem(rec, idx) {
    const item = document.createElement('div');
    item.className = 'recording-item';

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:14px;align-items:flex-start;';

    // 圖示
    const iconWrap = document.createElement('div');
    iconWrap.style.cssText = 'width:48px;height:48px;border-radius:10px;display:flex;align-items:center;justify-content:center;background:rgba(100,220,180,0.1);flex-shrink:0;';
    iconWrap.innerHTML = '<span class="material-symbols-outlined" style="color:#4dd9b0;font-size:24px;">cloud</span>';
    row.appendChild(iconWrap);

    const body = document.createElement('div');
    body.style.cssText = 'flex:1;min-width:0;';

    // 標題行
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;';
    const titleSpan = document.createElement('span');
    titleSpan.style.cssText = 'font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px;';
    titleSpan.textContent = rec.name || '未命名';
    header.appendChild(titleSpan);
    if (rec.has_db) header.insertAdjacentHTML('beforeend', '<span style="font-size:0.72rem;padding:2px 6px;border-radius:4px;background:rgba(100,180,255,0.15);color:#64b4ff;">DB</span>');
    if (rec.has_mp4) header.insertAdjacentHTML('beforeend', '<span style="font-size:0.72rem;padding:2px 6px;border-radius:4px;background:rgba(100,255,150,0.15);color:#64c896;">MP4</span>');

    // 元資訊
    const meta = document.createElement('div');
    meta.style.cssText = 'display:flex;gap:16px;font-size:0.82rem;color:var(--md-sys-color-on-surface-variant);flex-wrap:wrap;';
    const modDate = rec.modified ? new Date(rec.modified).toLocaleString('zh-TW') : '--';
    meta.innerHTML = `<span><i class="fas fa-clock"></i> ${escapeHtml(modDate)}</span>`
        + `<span><i class="fas fa-database"></i> ${formatBytes(rec.db_size)}</span>`
        + (rec.has_mp4 ? `<span><i class="fas fa-video"></i> ${formatBytes(rec.mp4_size)}</span>` : '');

    body.appendChild(header);
    body.appendChild(meta);
    row.appendChild(body);

    // 操作按鈕區（下載 DB、下載 MP4、刪除）
    const btnWrap = document.createElement('div');
    btnWrap.style.cssText = 'display:flex;flex-direction:column;gap:4px;flex-shrink:0;align-self:center;';

    const btnStyle = 'background:none;border:1px solid var(--md-sys-color-outline);border-radius:6px;padding:4px 10px;cursor:pointer;color:var(--md-sys-color-on-surface);font-size:0.78rem;display:flex;align-items:center;gap:4px;white-space:nowrap;';

    if (rec.has_db && rec.db_path) {
        const dlDbBtn = document.createElement('button');
        dlDbBtn.title = '下載 DB 檔案';
        dlDbBtn.style.cssText = btnStyle;
        dlDbBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;">download</span> DB';
        dlDbBtn.addEventListener('click', e => { e.stopPropagation(); fbDownloadFile(rec.db_path); });
        btnWrap.appendChild(dlDbBtn);
    }

    if (rec.has_mp4 && rec.mp4_path) {
        const dlMp4Btn = document.createElement('button');
        dlMp4Btn.title = '下載 MP4 影片';
        dlMp4Btn.style.cssText = btnStyle;
        dlMp4Btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;">download</span> MP4';
        dlMp4Btn.addEventListener('click', e => { e.stopPropagation(); fbDownloadFile(rec.mp4_path); });
        btnWrap.appendChild(dlMp4Btn);
    }

    const delBtn = document.createElement('button');
    delBtn.title = '從 File Browser 刪除此錄製';
    delBtn.style.cssText = btnStyle + 'border-color:rgba(239,68,68,0.5);color:#ef4444;';
    delBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;">delete</span> 刪除';
    delBtn.addEventListener('click', e => {
        e.stopPropagation();
        fbDeleteRecording(rec, idx, item);
    });
    btnWrap.appendChild(delBtn);

    row.appendChild(btnWrap);

    item.appendChild(row);
    item.addEventListener('click', () => selectCloudRecording(idx));
    return item;
}

// ── 雲端播放 ──

async function selectCloudRecording(idx) {
    // 清除本地列表的 active
    document.querySelectorAll('#recording-list .recording-item').forEach(el => el.classList.remove('active'));
    // 設定雲端列表 active
    document.querySelectorAll('#cloud-recording-list .recording-item').forEach((el, i) => {
        el.classList.toggle('active', i === (idx % _cloudRecState.pageSize));
    });

    stopPlayback();
    const loadEl = document.getElementById('cloud-pb-loading');
    if (loadEl) loadEl.style.display = 'block';
    _pb['pb-controls'].style.display = 'none';
    _pb['pb-data'].style.display = 'none';

    const rec = _cloudRecList[idx];
    if (!rec) { if (loadEl) loadEl.style.display = 'none'; return; }

    // 顯示共用回放區（雲端標籤）
    _showSharedPlayback(rec.name, true);

    const videoSection   = document.getElementById('pb-video-section');
    const videoPlaceholder = document.getElementById('pb-video-placeholder');
    if (!pbVideoEl) pbVideoEl = document.getElementById('pb-video');

    try {
        // 設定影片（串流 proxy）
        if (rec.has_mp4 && rec.mp4_path) {
            pbVideoAvailable = true;
            pbVideoEl.src = `/api/fb/stream-video?path=${encodeURIComponent(rec.mp4_path)}`;
            pbVideoEl.onerror = () => {
                pbVideoAvailable = false;
                pbVideoEl.style.display = 'none';
                videoPlaceholder.style.display = 'flex';
            };
            pbVideoEl.load();
            pbVideoEl.style.display = 'block';
            videoPlaceholder.style.display = 'none';
            videoSection.style.display = 'block';
        } else {
            pbVideoAvailable = false;
            pbVideoEl.removeAttribute('src');
            pbVideoEl.style.display = 'none';
            videoPlaceholder.style.display = 'flex';
            videoSection.style.display = 'block';
        }

        // 下載 .db 到本地快取
        if (!rec.has_db || !rec.db_path) {
            throw new Error('此雲端錄製沒有 .db 檔案');
        }
        const cacheRes = await fetch('/api/fb/cache-db', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ remote_path: rec.db_path })
        });
        const cacheJson = await cacheRes.json();
        if (!cacheJson.success || !cacheJson.db_path) {
            throw new Error(cacheJson.error || '下載 DB 失敗');
        }

        // 用現有回放引擎播放
        const res  = await fetch(`/api/playback/full?db_path=${encodeURIComponent(cacheJson.db_path)}`);
        const json = await res.json();
        if (!json.success || !json.data || json.data.length === 0) {
            throw new Error(json.error || '資料庫為空');
        }
        pbData = json.data;
        pbIndex = 0;
        _resetDisplayState();
        initPlaybackUI();
    } catch (e) {
        showNotification(`雲端回放失敗: ${e.message}`, 'error');
        clearPlayback();
    } finally {
        if (loadEl) loadEl.style.display = 'none';
    }
}

// ── 上傳至 File Browser ──

async function fbUploadRecording(recordingName, btnEl) {
    if (!recordingName) return;

    // 取出 stem（去掉 metrics_ 前綴）用於比對雲端列表
    const stem = recordingName.replace(/^metrics_/, '');

    // 先即時查詢雲端，檢查是否已有同名檔案
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = '檢查中...'; }
    try {
        const checkRes = await fetch('/api/fb/recordings');
        const checkData = await checkRes.json();
        if (checkData.success) {
            const existing = (checkData.recordings || []).find(r => r.name === stem);
            if (existing) {
                const existFiles = [existing.has_db ? 'DB' : null, existing.has_mp4 ? 'MP4' : null].filter(Boolean).join('、');
                showNotification(`雲端已存在「${stem}」（${existFiles}），請先至雲端回放刪除後再上傳。`, 'error');
                if (btnEl) { btnEl.disabled = false; btnEl.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">cloud_upload</span> 上傳'; }
                return;
            }
        }
    } catch (e) {
        // 查詢失敗不阻止上傳，讓後端處理
        console.warn('檢查雲端檔案失敗:', e);
    }

    const origHTML = btnEl ? btnEl.innerHTML : '';
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = '上傳中...'; }

    const onProgress = (data) => {
        if (data.recording === recordingName && btnEl) {
            const pct = Math.round((data.progress || 0) * 100);
            btnEl.textContent = `${data.file ? data.file.substring(0, 8) : ''} ${pct}%`;
        }
    };
    if (socket) socket.on('fb_upload_progress', onProgress);

    try {
        const r = await fetch('/api/fb/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recording_name: recordingName })
        });
        const d = await r.json();
        if (d.success) {
            showNotification(`上傳成功: ${recordingName}（${(d.uploaded || []).join(', ')}）`, 'success');
            if (btnEl) { btnEl.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;">cloud_done</span>'; btnEl.style.color = '#4dd9b0'; }
            fbRefreshList();
        } else {
            showNotification(`上傳失敗: ${d.error}`, 'error');
            if (btnEl) { btnEl.disabled = false; btnEl.innerHTML = origHTML; }
        }
    } catch (e) {
        showNotification(`上傳錯誤: ${e.message}`, 'error');
        if (btnEl) { btnEl.disabled = false; btnEl.innerHTML = origHTML; }
    } finally {
        if (socket) socket.off('fb_upload_progress', onProgress);
    }
}

// ── 下載 / 刪除 ──

function fbDownloadFile(filename) {
    if (!filename) return;
    // 透過後端 proxy 下載，讓瀏覽器直接另存新檔
    const a = document.createElement('a');
    a.href = `/api/fb/download?filename=${encodeURIComponent(filename)}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function fbDeleteRecording(rec, idx, itemEl) {
    const label = rec.name || '此錄製';
    const files = [rec.db_path, rec.mp4_path].filter(Boolean);
    if (!confirm(`確定要從 File Browser 刪除「${label}」嗎？\n（${files.join('、')}）\n此操作無法復原。`)) return;

    const results = await Promise.all(files.map(async filename => {
        try {
            const r = await fetch('/api/fb/delete', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            });
            const d = await r.json();
            return d.success ? null : d.error;
        } catch (e) {
            return e.message;
        }
    }));

    const errs = results.filter(Boolean);
    if (errs.length === 0) {
        showNotification(`已刪除：${label}`, 'success');
        // 從列表移除並重新渲染
        _cloudRecList.splice(idx, 1);
        _renderCloudPage();
        // 如果正在播放此錄製則清除
        if (document.getElementById('pb-source-name')?.textContent === rec.name) {
            clearPlayback();
        }
    } else {
        showNotification(`刪除失敗：${errs.join('；')}`, 'error');
    }
}

// ── 工具函數（如已有則不衝突，escapeHtml / formatBytes / showNotification 在舊程式碼已定義） ──
if (typeof escapeHtml === 'undefined') {
    window.escapeHtml = function(text) {
        if (!text) return '';
        return String(text).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    };
}
if (typeof formatBytes === 'undefined') {
    window.formatBytes = function(bytes) {
        if (!bytes) return '0 B';
        const sizes = ['B','KB','MB','GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
    };
}
if (typeof showNotification === 'undefined') {
    window.showNotification = function(msg, type='info') {
        const colors = {success:'#4caf50',error:'#f44336',info:'#2196f3'};
        const el = document.createElement('div');
        el.style.cssText = `position:fixed;top:16px;right:16px;z-index:9999;padding:12px 20px;border-radius:8px;background:${colors[type]||colors.info};color:#fff;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,.3);`;
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => { el.style.opacity='0'; setTimeout(()=>el.remove(),300); }, 3000);
    };
}
