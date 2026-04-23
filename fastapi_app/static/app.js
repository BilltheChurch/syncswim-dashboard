/* ═══════════════════════════════════════════════════════
   SyncSwim Coach Station — app.js (Stage 6 overhaul)
   Framework: Vanilla JS, no build step.
═══════════════════════════════════════════════════════ */
'use strict';

// ═══════════════════════════════════════════════════════
//   CONSTANTS
// ═══════════════════════════════════════════════════════
const CONNECTIONS = [
    [11,12],[11,13],[13,15],[12,14],[14,16],
    [11,23],[12,24],[23,24],[23,25],[24,26],
    [25,27],[26,28]
];

const THRESHOLDS = {
    leg_deviation:            { clean: 5,   minor: 15,  inverted: false },
    knee_extension:           { clean: 170, minor: 155, inverted: true  },
    trunk_vertical:           { clean: 10,  minor: 20,  inverted: false },
    elbow:                    { clean: 15,  minor: 30,  inverted: false },
    leg_symmetry:             { clean: 5,   minor: 15,  inverted: false },
    shoulder_knee_alignment:  { clean: 170, minor: 155, inverted: true  },
};

const LIVE_BAR_RANGES = {
    leg_deviation:  { min: 0,   max: 30  },
    knee_extension: { min: 140, max: 180 },
    trunk_vertical: { min: 0,   max: 35  },
    elbow:          { min: 0,   max: 60  },
};

const METRIC_LABELS = {
    leg_deviation:            '腿部垂直偏差',
    leg_height_index:         '腿部高度指数',
    knee_extension:           '膝盖伸直度',
    shoulder_knee_alignment:  '肩膝对齐',
    trunk_vertical:           '躯干垂直度',
    leg_symmetry:             '双腿对称性',
    smoothness:               '动作平滑度',
    stability:                '姿势稳定性',
    movement_frequency:       '动作频率',
    rotation_frequency:       '旋转速率',
    mean_pattern_duration:    '平均图形时长',
    last_hf_duration:         '末段图形时长',
    explosive_power:          '爆发力',
    energy_index:             '能量消耗',
    motion_complexity:        '动作复杂度',
    elbow:                    '肘关节角度',
};

const METRIC_HINTS = {
    leg_deviation:           '偏差越小越好',
    knee_extension:          '角度越大越接近 180°',
    trunk_vertical:          '偏差越小越垂直',
    leg_symmetry:            '偏差越小越对称',
    shoulder_knee_alignment: '角度越大越对齐 · Edriss 2024 r=-0.444',
    leg_height_index:        '顶级队 32.7% · Yue 2023',
    movement_frequency:      '顶级队 1.92Hz · Yue 2023 β=0.345',
    rotation_frequency:      '顶级队 44.95°/s · Yue 2023',
    mean_pattern_duration:   '平均图形时长 · Yue 2023',
    last_hf_duration:        '最后一段图形时长',
    explosive_power:         '动态加速度峰值',
    energy_index:            '代谢消耗代理',
    motion_complexity:       '动作谱熵 · 越高越多变',
    elbow:                   'FINA 扣分依据',
};

const ZONE_LABELS = { clean: '达标', minor: '轻微', major: '需改进', no_data: '无数据' };
const PHASE_NAMES = { prep: '准备', exhibition: '展示', recovery: '恢复', '准备': '准备', '动作': '动作', '恢复': '恢复' };
const GROUP_NAMES = { posture: '姿态', extension: '伸展', symmetry: '对称', motion: '运动', power: '能量' };
const GROUP_ICONS = { posture: 'P', extension: 'E', symmetry: 'S', motion: 'M', power: 'W' };

const SERIES_COLORS = {
    tilt_NODE_A1:            '#3B82F6',
    tilt_NODE_A2:            '#A855F7',
    elbow:                   '#F59E0B',
    leg_deviation:           '#EF4444',
    knee_extension:          '#10B981',
    trunk_vertical:          '#06B6D4',
    shoulder_knee_alignment: '#EC4899',
    leg_symmetry:            '#84CC16',
};

const SERIES_LABELS = {
    tilt_NODE_A1:            'A1 倾角',
    tilt_NODE_A2:            'A2 倾角',
    elbow:                   '肘角',
    leg_deviation:           '腿部偏差',
    knee_extension:          '膝伸直度',
    trunk_vertical:          '躯干垂直',
    shoulder_knee_alignment: '肩膝对齐',
    leg_symmetry:            '双腿对称',
};

// ═══════════════════════════════════════════════════════
//   HELPERS — DOM, zone, number, toast
// ═══════════════════════════════════════════════════════
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function getZone(name, value) {
    const t = THRESHOLDS[name];
    if (!t) return 'clean';
    if (t.inverted) {
        if (value >= t.clean) return 'clean';
        if (value >= t.minor) return 'minor';
        return 'major';
    }
    if (value <= t.clean) return 'clean';
    if (value <= t.minor) return 'minor';
    return 'major';
}

function scoreZone(score) {
    if (score >= 8) return 'clean';
    if (score >= 6) return 'minor';
    return 'major';
}

function formatDuration(sec) {
    if (!sec || sec < 0) return '--:--';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function formatBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function normalizeForRadar(name, val) {
    switch (name) {
        case 'leg_deviation':           return Math.max(0, Math.min(100, (30 - val) / 30 * 100));
        case 'knee_extension':          return Math.max(0, Math.min(100, (val - 140) / 40 * 100));
        case 'shoulder_knee_alignment': return Math.max(0, Math.min(100, (val - 140) / 40 * 100));
        case 'trunk_vertical':          return Math.max(0, Math.min(100, (35 - val) / 35 * 100));
        case 'leg_symmetry':            return Math.max(0, Math.min(100, (30 - val) / 30 * 100));
        case 'smoothness':              return Math.max(0, Math.min(100, (50 - val) / 50 * 100));
        case 'stability':               return Math.max(0, Math.min(100, (45 - val) / 45 * 100));
        case 'leg_height_index':        return Math.max(0, Math.min(100, val / 180 * 100));
        default:                        return 50;
    }
}

// ─── Toast ─────────────────────────────────────────────
function toast(msg, type = 'info', timeout = 3200) {
    const c = $('#toast-container');
    if (!c) return;
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span>${msg}</span><button class="toast-close">×</button>`;
    c.appendChild(el);
    const close = () => {
        el.classList.add('toast-fade-out');
        setTimeout(() => el.remove(), 300);
    };
    el.querySelector('.toast-close').onclick = close;
    setTimeout(close, timeout);
}

// ─── Modal (confirm) ───────────────────────────────────
function confirmModal(title, body, { confirmText = '确认', cancelText = '取消', danger = false } = {}) {
    return new Promise(resolve => {
        const root = $('#modal-root');
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal-box">
                <div class="modal-title">${title}</div>
                <div class="modal-body">${body}</div>
                <div class="modal-actions">
                    <button class="modal-btn modal-btn-cancel">${cancelText}</button>
                    <button class="modal-btn modal-btn-confirm"${danger ? '' : ' style="background:var(--primary);border-color:var(--primary)"'}>${confirmText}</button>
                </div>
            </div>
        `;
        root.appendChild(overlay);
        const done = (v) => { overlay.remove(); document.removeEventListener('keydown', keyHandler); resolve(v); };
        overlay.querySelector('.modal-btn-cancel').onclick  = () => done(false);
        overlay.querySelector('.modal-btn-confirm').onclick = () => done(true);
        overlay.onclick = e => { if (e.target === overlay) done(false); };
        const keyHandler = (e) => { if (e.key === 'Escape') done(false); };
        document.addEventListener('keydown', keyHandler);
    });
}

function anyModalOpen() {
    return !!$('.modal-overlay');
}

// ─── Value pop animation ──────────────────────────────
function tickValue(el) {
    if (!el) return;
    el.classList.remove('value-tick');
    void el.offsetWidth;
    el.classList.add('value-tick');
}

// ═══════════════════════════════════════════════════════
//   TAB NAVIGATION
// ═══════════════════════════════════════════════════════
function switchTab(view) {
    $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
    if (view === 'analysis') loadSetList();
    if (view === 'history')  loadHistory();
    if (view === 'settings') loadSettings();
}

$$('.tab').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.view));
});

// ═══════════════════════════════════════════════════════
//   KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════════════
document.addEventListener('keydown', e => {
    if (anyModalOpen()) return;
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    // Ignore presses with any modifier key — otherwise the R in the
    // browser's built-in Cmd+Shift+R (hard reload) fires our "start
    // recording" handler before the browser actually reloads, causing
    // the page to auto-record on every hard refresh.
    if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;

    switch (e.key) {
        case '1': switchTab('live');     break;
        case '2': switchTab('analysis'); break;
        case '3': switchTab('history');  break;
        case '4': switchTab('settings'); break;
        case 'r': case 'R':
            if (!$('#btn-start').disabled) $('#btn-start').click();
            break;
        case ' ':
            if (!$('#btn-stop').disabled) { e.preventDefault(); $('#btn-stop').click(); }
            break;
        case 's': case 'S':
            $('#btn-snapshot').click();
            break;
        case 't': case 'T':
            $('#btn-annotate').click();
            break;
    }
});

// Annotation toggle wire-up lives near the _annotationMode declaration
// so there's no temporal-dead-zone risk.

// ═══════════════════════════════════════════════════════
//   HEADER CLOCK
// ═══════════════════════════════════════════════════════
setInterval(() => {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const el = $('#header-clock');
    if (el) el.textContent = `${hh}:${mm}:${ss}`;
}, 1000);

// ═══════════════════════════════════════════════════════
//   LIVE — VIDEO WS
// ═══════════════════════════════════════════════════════
const canvas = $('#video-canvas');
const ctx = canvas.getContext('2d');
let videoWs = null;
let _lastFrameTs = 0;
let _frameEma = 0;
let _lastAspect = 0;  // cached image aspect ratio for wrapper sizing

/**
 * Size the video wrapper to match the image's aspect ratio while fitting
 * inside the available column height (after controls) and width.
 * Prevents the "tiny portrait video in wide black rectangle" layout.
 */
function fitVideoWrapper(aspect) {
    if (!aspect || !isFinite(aspect)) return;
    if (Math.abs(aspect - _lastAspect) < 0.01) return;  // same, skip
    _lastAspect = aspect;

    const wrap = canvas.parentElement;
    const col = wrap && wrap.parentElement;
    if (!wrap || !col) return;

    const controls = col.querySelector('.controls-bar');
    const controlsH = controls ? controls.offsetHeight : 60;
    const gap = 10;
    const availH = col.clientHeight - controlsH - gap;
    const availW = col.clientWidth;
    if (availH <= 0 || availW <= 0) return;

    let targetH = availH;
    let targetW = targetH * aspect;
    if (targetW > availW) {
        targetW = availW;
        targetH = availW / aspect;
    }
    wrap.style.width  = Math.floor(targetW) + 'px';
    wrap.style.height = Math.floor(targetH) + 'px';
}

// Re-fit on window resize (flex layout changes available space)
window.addEventListener('resize', () => {
    if (_lastAspect) {
        const prev = _lastAspect;
        _lastAspect = 0;
        fitVideoWrapper(prev);
    }
}, { passive: true });

function connectVideoWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    videoWs = new WebSocket(`${protocol}//${location.host}/ws/video`);

    videoWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        // fps calc
        const now = performance.now();
        if (_lastFrameTs) {
            const dt = now - _lastFrameTs;
            _frameEma = _frameEma ? _frameEma * 0.85 + dt * 0.15 : dt;
            const fps = _frameEma > 0 ? 1000 / _frameEma : 0;
            const fpsEl = $('#cam-fps');
            if (fpsEl) fpsEl.textContent = fps.toFixed(0) + ' FPS';
            const hdCam = $('#hd-cam-dot');
            if (hdCam) hdCam.classList.add('active');
        }
        _lastFrameTs = now;

        const img = new Image();
        img.onload = () => {
            canvas.width  = img.width;
            canvas.height = img.height;
            ctx.drawImage(img, 0, 0);

            // Multi-person: draw each teammate with their own colour
            // + identity label + key-angle pills. Primary gets the
            // rich MPI-blue full-detail treatment on top. ``trackIds``
            // is the parallel BYTETracker stream (phase 7.1) — when
            // present, identity binds colour and label so the same
            // swimmer keeps the same hue across frames.
            const all = data.all_landmarks || [];
            const allAngles = data.all_angles || [];
            const trackIds = data.track_ids || [];
            if (all.length > 1) {
                for (let i = 1; i < all.length; i++) {
                    drawSecondaryPose(ctx, canvas, all[i], allAngles[i], i, trackIds[i]);
                }
            }
            if (data.landmarks && data.landmarks.length === 33) {
                drawSkeletonOnCanvas(ctx, canvas, data.landmarks, data.angles, trackIds[0]);
            }
            // Size the wrapper to match image aspect ratio so we don't waste space
            fitVideoWrapper(img.width / img.height);
        };
        img.src = data.frame;

        // Pose badge reflects team count (e.g., "3 人" in team routines).
        const n = data.person_count || 0;
        const primary = data.landmarks && data.landmarks.length === 33
                        && data.landmarks.some(l => l[2] > 0.3);
        const badge = $('#pose-badge');
        if (badge) {
            badge.classList.toggle('pose-detected', !!primary);
            const txt = n === 0 ? '无人' : n === 1 ? '检测中' : `${n} 人`;
            $('#pose-text').textContent = txt;
        }

        if (data.angles) {
            updateLiveMetrics(data.angles);
            updateLiveScoreRing(data.angles);
        } else {
            clearLiveMetrics();
            updateLiveScoreRing(null);
        }
    };

    videoWs.onclose = () => {
        const hdCam = $('#hd-cam-dot');
        if (hdCam) hdCam.classList.remove('active');
        setTimeout(connectVideoWs, 2000);
    };
    videoWs.onerror = () => videoWs.close();
}

// ─── Skeleton annotation config ─────────────────────────
const JOINT_LABELS = {
    11: '左肩', 12: '右肩',
    13: '左肘', 14: '右肘',
    15: '左腕', 16: '右腕',
    23: '左髋', 24: '右髋',
    25: '左膝', 26: '右膝',
    27: '左踝', 28: '右踝',
};

// Where each computed angle should be drawn. `joint` can be a single
// index, an array of two indices (for midpoints like the trunk centre)
// or an object {anchor, offset} for fine-tuned placement.
const ANGLE_MARKERS = [
    { key: 'elbow',               joint: 14, label: 'R肘' },
    { key: 'elbow_left',          joint: 13, label: 'L肘' },
    { key: 'knee_extension',      joint: 26, label: 'R膝' },
    { key: 'knee_extension_left', joint: 25, label: 'L膝' },
    { key: 'shoulder_knee_angle', joint: 24, label: 'R髋' },
    { key: 'leg_deviation',       joint: 28, label: 'R腿' },
    { key: 'leg_deviation_left',  joint: 27, label: 'L腿' },
    { key: 'trunk_vertical',      joint: [23, 24], label: '躯干' },
    { key: 'shoulder_line',       joint: [11, 12], label: '肩线' },
];

// Annotation density mode: 'normal' (key joints + 3 angle pills)
//                         'detailed' (all 33 joints + names + every angle)
let _annotationMode = localStorage.getItem('annotationMode') || 'detailed';

function setAnnotationMode(mode) {
    _annotationMode = mode;
    try { localStorage.setItem('annotationMode', mode); } catch {}
    const btn = $('#btn-annotate');
    if (btn) btn.classList.toggle('active', mode === 'detailed');
}

// Wire the annotation toggle button — safe here because
// `_annotationMode` is already declared above. `script` is at the
// bottom of <body> so DOM is ready; no need for DOMContentLoaded.
(function wireAnnotateToggle() {
    const btn = document.getElementById('btn-annotate');
    if (!btn) return;
    btn.classList.toggle('active', _annotationMode === 'detailed');
    btn.addEventListener('click', () => {
        setAnnotationMode(_annotationMode === 'detailed' ? 'normal' : 'detailed');
    });
})();

// Color palette for up to 8 athletes in a team routine. Primary
// person keeps MPI blue via drawSkeletonOnCanvas; teammates cycle
// through these distinctive hues.
const TEAM_COLORS = [
    '#3B82F6',  // 0 primary (not used here)
    '#A855F7',  // 1 violet
    '#F59E0B',  // 2 amber
    '#10B981',  // 3 green
    '#EC4899',  // 4 pink
    '#06B6D4',  // 5 cyan
    '#F43F5E',  // 6 rose
    '#84CC16',  // 7 lime
];

/**
 * Skeleton + identity label + key-angle pills for a non-primary teammate.
 * Each person gets a distinct colour so the coach can track them
 * visually across frames.
 *
 * @param {*} idx     Position in all_landmarks (1…N-1, 0 is primary).
 * @param {*} angles  Per-person angles dict from data.all_angles[idx]
 *                    (may be undefined if the backend is old).
 * @param {*} trackId Stable BYTETracker ID (int) when available, or
 *                    null/undefined for older recordings / MediaPipe.
 *                    When present we bind colour to the ID so the same
 *                    swimmer keeps the same hue even if their array
 *                    position changes between frames.
 */
function drawSecondaryPose(c, cv, landmarks, angles, idx = 1, trackId = null) {
    if (!landmarks || landmarks.length !== 33) return;
    const w = cv.width, h = cv.height;
    const color = (trackId != null)
        ? TEAM_COLORS[trackId % TEAM_COLORS.length]
        : TEAM_COLORS[idx % TEAM_COLORS.length];

    // Bones
    c.strokeStyle = color + 'B0';  // ~70% opacity
    c.lineWidth = 1.8;
    c.lineCap = 'round';
    CONNECTIONS.forEach(([i, j]) => {
        if (landmarks[i][2] > 0.3 && landmarks[j][2] > 0.3) {
            c.beginPath();
            c.moveTo(landmarks[i][0] * w, landmarks[i][1] * h);
            c.lineTo(landmarks[j][0] * w, landmarks[j][1] * h);
            c.stroke();
        }
    });
    // Joints
    c.fillStyle = color;
    for (let i = 0; i < 33; i++) {
        if (landmarks[i][2] < 0.3) continue;
        c.beginPath();
        c.arc(landmarks[i][0] * w, landmarks[i][1] * h, 3, 0, Math.PI * 2);
        c.fill();
    }

    // "Pn" label — anchor above the head (nose with fallback to shoulder midpoint).
    let labelX = 0, labelY = 0, anchorOk = false;
    if (landmarks[0][2] > 0.3) {
        labelX = landmarks[0][0] * w;
        labelY = landmarks[0][1] * h - 22;
        anchorOk = true;
    } else if (landmarks[11][2] > 0.3 && landmarks[12][2] > 0.3) {
        labelX = (landmarks[11][0] + landmarks[12][0]) / 2 * w;
        labelY = (landmarks[11][1] + landmarks[12][1]) / 2 * h - 30;
        anchorOk = true;
    }
    if (anchorOk) {
        // Prefer the stable BYTETracker ID (#3, #7, ...) so the coach
        // can verify identity across frames. Fall back to "Pn" for
        // older recordings / MP backend that don't surface IDs.
        const tag = (trackId != null) ? `#${trackId}` : `P${idx + 1}`;
        c.font = 'bold 13px "Fira Code", monospace';
        const tw = c.measureText(tag).width;
        c.fillStyle = color;
        c.beginPath();
        c.roundRect(labelX - tw/2 - 6, labelY - 12, tw + 12, 18, 4);
        c.fill();
        c.fillStyle = '#fff';
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText(tag, labelX, labelY - 3);
        c.textAlign = 'left';   // reset
        c.textBaseline = 'alphabetic';
    }

    // Key angles — only the two most informative (elbow + knee) to
    // avoid visual clutter when 5-8 athletes are in frame.
    if (angles) {
        const pickList = [
            { key: 'elbow',          joint: 14, label: '肘' },
            { key: 'knee_extension', joint: 26, label: '膝' },
        ];
        c.font = 'bold 11px "Fira Code", monospace';
        pickList.forEach(({ key, joint, label }) => {
            const v = angles[key];
            if (v === undefined || v === null) return;
            if (!landmarks[joint] || landmarks[joint][2] < 0.3) return;
            const x = landmarks[joint][0] * w + 8;
            const y = landmarks[joint][1] * h + 4;
            const text = `${label}${v.toFixed(0)}`;
            const tw = c.measureText(text).width;
            c.fillStyle = 'rgba(0,0,0,0.65)';
            c.beginPath();
            c.roundRect(x - 2, y - 10, tw + 6, 14, 3);
            c.fill();
            c.fillStyle = color;
            c.fillText(text, x + 1, y);
        });
    }
}

function drawSkeletonOnCanvas(c, cv, landmarks, angles, trackId = null) {
    const w = cv.width, h = cv.height;
    const detailed = _annotationMode === 'detailed';

    // --- Identity tag above head (BYTETracker ID, when available) ---
    // Drawn first so the skeleton bones render on top if they
    // overlap; the small dark pill stays readable either way.
    if (trackId != null && landmarks && landmarks.length === 33) {
        let lx = 0, ly = 0, ok = false;
        if (landmarks[0] && landmarks[0][2] > 0.3) {
            lx = landmarks[0][0] * w;
            ly = landmarks[0][1] * h - 22;
            ok = true;
        } else if (landmarks[11] && landmarks[12]
                   && landmarks[11][2] > 0.3 && landmarks[12][2] > 0.3) {
            lx = (landmarks[11][0] + landmarks[12][0]) / 2 * w;
            ly = (landmarks[11][1] + landmarks[12][1]) / 2 * h - 30;
            ok = true;
        }
        if (ok) {
            const tag = `#${trackId}`;
            c.font = 'bold 13px "Fira Code", monospace';
            const tw = c.measureText(tag).width;
            c.fillStyle = '#3B82F6';
            c.beginPath();
            c.roundRect(lx - tw/2 - 6, ly - 12, tw + 12, 18, 4);
            c.fill();
            c.fillStyle = '#fff';
            c.textAlign = 'center';
            c.textBaseline = 'middle';
            c.fillText(tag, lx, ly - 3);
            c.textAlign = 'left';
            c.textBaseline = 'alphabetic';
        }
    }

    // --- Connections (bones) ---
    c.strokeStyle = 'rgba(59, 130, 246, 0.9)';
    c.lineWidth = 2.2;
    c.lineCap = 'round';
    CONNECTIONS.forEach(([i, j]) => {
        if (landmarks[i][2] > 0.3 && landmarks[j][2] > 0.3) {
            c.beginPath();
            c.moveTo(landmarks[i][0] * w, landmarks[i][1] * h);
            c.lineTo(landmarks[j][0] * w, landmarks[j][1] * h);
            c.stroke();
        }
    });

    // --- Joint dots ---
    const jointSet = detailed
        ? Array.from({ length: 33 }, (_, i) => i)
        : [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
    jointSet.forEach(i => {
        const lm = landmarks[i];
        if (!lm) return;
        const vis = lm[2];
        if (vis < 0.2) return;
        const r = detailed ? 3 + vis * 2 : 4;
        c.fillStyle = vis > 0.6 ? '#3B82F6' : 'rgba(59,130,246,0.6)';
        c.beginPath();
        c.arc(lm[0] * w, lm[1] * h, r, 0, Math.PI * 2);
        c.fill();
        c.fillStyle = '#ffffff';
        c.beginPath();
        c.arc(lm[0] * w, lm[1] * h, r * 0.35, 0, Math.PI * 2);
        c.fill();
    });

    // --- Joint name labels (detailed only) ---
    if (detailed) {
        c.font = '10px "Fira Sans", sans-serif';
        c.fillStyle = 'rgba(210,225,245,0.85)';
        c.textBaseline = 'middle';
        Object.entries(JOINT_LABELS).forEach(([idxStr, name]) => {
            const i = parseInt(idxStr, 10);
            const lm = landmarks[i];
            if (!lm || lm[2] < 0.4) return;
            const x = lm[0] * w + 7;
            const y = lm[1] * h - 7;
            // Small dark pill so label survives on light backgrounds.
            const tw = c.measureText(name).width;
            c.fillStyle = 'rgba(0,0,0,0.55)';
            c.fillRect(x - 2, y - 7, tw + 4, 13);
            c.fillStyle = 'rgba(210,225,245,0.95)';
            c.fillText(name, x, y);
        });
        c.textBaseline = 'alphabetic';
    }

    // --- Angle pills at each joint ---
    if (angles) {
        const markers = detailed
            ? ANGLE_MARKERS
            : ANGLE_MARKERS.filter(m => ['elbow','knee_extension','leg_deviation'].includes(m.key));

        markers.forEach(({ key, joint, label }) => {
            if (angles[key] === undefined || angles[key] === null) return;
            let x = 0, y = 0, ok = false;
            if (Array.isArray(joint)) {
                const [a, b] = joint;
                if (landmarks[a][2] > 0.3 && landmarks[b][2] > 0.3) {
                    x = (landmarks[a][0] + landmarks[b][0]) / 2 * w;
                    y = (landmarks[a][1] + landmarks[b][1]) / 2 * h;
                    ok = true;
                }
            } else if (landmarks[joint] && landmarks[joint][2] > 0.3) {
                x = landmarks[joint][0] * w;
                y = landmarks[joint][1] * h;
                ok = true;
            }
            if (!ok) return;

            // Normalize zone key (drop _left suffix) for consistent color.
            const zoneKey = key.replace(/_left$/, '');
            const zone = getZone(zoneKey, angles[key]);
            const color = zone === 'clean' ? '#4ade80' : zone === 'minor' ? '#fbbf24' : '#f87171';
            const text = `${label} ${angles[key].toFixed(0)}°`;

            c.font = 'bold 11px "Fira Code", monospace';
            const tw = c.measureText(text).width;
            const bx = x + 10, by = y - 10;
            c.fillStyle = 'rgba(0,0,0,0.72)';
            c.beginPath();
            c.roundRect(bx - 4, by - 12, tw + 8, 17, 3);
            c.fill();
            c.fillStyle = color;
            c.fillText(text, bx, by);
        });
    }
}

function updateLiveMetrics(angles) {
    ['leg_deviation','knee_extension','trunk_vertical','elbow'].forEach(name => {
        const row  = $(`#metric-${name}`);
        const valEl = row ? row.querySelector('.lm-value') : null;
        const fill  = row ? row.querySelector('.lm-bar-fill') : null;
        if (!row) return;
        if (angles[name] === undefined || angles[name] === null) {
            valEl.textContent = '--';
            row.className = 'live-metric-row';
            if (fill) fill.style.width = '0%';
            return;
        }
        const val  = angles[name];
        const zone = getZone(name, val);
        valEl.textContent = val.toFixed(1);
        row.className = `live-metric-row zone-${zone}`;
        if (fill) {
            const range = LIVE_BAR_RANGES[name];
            if (range) {
                const pct = Math.max(0, Math.min(100,
                    (val - range.min) / (range.max - range.min) * 100
                ));
                fill.style.width = pct + '%';
            }
        }
    });
}

function clearLiveMetrics() {
    ['leg_deviation','knee_extension','trunk_vertical','elbow'].forEach(name => {
        const row = $(`#metric-${name}`);
        if (!row) return;
        const valEl = row.querySelector('.lm-value');
        const fill  = row.querySelector('.lm-bar-fill');
        if (valEl) valEl.textContent = '--';
        row.className = 'live-metric-row';
        if (fill) fill.style.width = '0%';
    });
}

// ─── Live score ring ──────────────────────────────────
function updateLiveScoreRing(angles) {
    const ringScore = $('#live-score');
    const ring = $('#live-ring');
    const msPose = $('#ms-fill-pose');
    const msSmooth = $('#ms-fill-smooth');
    const msSym = $('#ms-fill-sym');
    if (!angles) {
        if (ringScore) ringScore.textContent = '--';
        if (ring) {
            ring.style.strokeDashoffset = '276.46';
            // SVG elements have a readonly SVGAnimatedString className;
            // use setAttribute() instead or every frame throws TypeError
            // (it was stacking thousands of exceptions, slowing the page
            // and making the skeleton lag).
            ring.setAttribute('class', 'ring-fill');
        }
        [msPose, msSmooth, msSym].forEach(el => {
            if (el) { el.style.width = '0%'; el.setAttribute('class', 'ms-fill'); }
        });
        return;
    }

    // pose: avg score of leg_dev + trunk + knee_ext normalized
    const poseParts = [];
    if (angles.leg_deviation !== undefined) poseParts.push(normalizeForRadar('leg_deviation', angles.leg_deviation));
    if (angles.trunk_vertical !== undefined) poseParts.push(normalizeForRadar('trunk_vertical', angles.trunk_vertical));
    if (angles.knee_extension !== undefined) poseParts.push(normalizeForRadar('knee_extension', angles.knee_extension));
    const poseScore = poseParts.length ? poseParts.reduce((a, b) => a + b, 0) / poseParts.length : 0;

    // smoothness proxy: elbow stability within last window (heuristic — just reuse elbow zone)
    let smoothScore = 70;
    if (angles.elbow !== undefined) {
        const z = getZone('elbow', angles.elbow);
        smoothScore = z === 'clean' ? 90 : z === 'minor' ? 65 : 40;
    }

    // symmetry proxy: if leg_symmetry not live, use shoulder/knee alignment
    let symScore = 70;
    if (angles.shoulder_knee_alignment !== undefined) {
        symScore = normalizeForRadar('shoulder_knee_alignment', angles.shoulder_knee_alignment);
    }

    const overall = (poseScore * 0.5 + smoothScore * 0.25 + symScore * 0.25) / 10; // 0..10
    const zone = scoreZone(overall);
    const dash = 276.46;
    if (ringScore) ringScore.textContent = overall.toFixed(1);
    if (ring) {
        ring.style.strokeDashoffset = String(dash - dash * Math.min(1, overall / 10));
        ring.setAttribute('class', `ring-fill zone-${zone}`);
    }

    const paintMs = (el, pct) => {
        if (!el) return;
        el.style.width = pct + '%';
        const cls = pct >= 80 ? 'ms-fill zone-clean'
                  : pct >= 55 ? 'ms-fill zone-minor'
                              : 'ms-fill zone-major';
        el.setAttribute('class', cls);
    };
    paintMs(msPose, poseScore.toFixed(0));
    paintMs(msSmooth, smoothScore.toFixed(0));
    paintMs(msSym, symScore.toFixed(0));
}

// ═══════════════════════════════════════════════════════
//   LIVE — METRICS WS
// ═══════════════════════════════════════════════════════
let metricsWs = null;
let wasRecording = false;

function connectMetricsWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    metricsWs = new WebSocket(`${protocol}//${location.host}/ws/metrics`);

    metricsWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateBleStatus(data.nodes);
        updateRecStatus(data);

        if (wasRecording && !data.recording) {
            // Auto-switch to analysis view after stop
            setTimeout(() => switchTab('analysis'), 300);
            toast('录制已停止，进入分析', 'success');
        }
        wasRecording = data.recording;
    };

    metricsWs.onclose = () => setTimeout(connectMetricsWs, 2000);
    metricsWs.onerror = () => metricsWs.close();
}

function updateBleStatus(nodes) {
    let anyConnected = false;
    Object.entries(nodes).forEach(([name, info]) => {
        const row  = $(`#node-${name}`);
        const meta = $(`#meta-${name}`);
        const tilt = $(`#tilt-${name}`);
        if (!row) return;

        if (info.connected) {
            anyConnected = true;
            row.classList.add('connected');
            if (meta) meta.textContent = `${info.rate.toFixed(0)} Hz · ${info.packets.toLocaleString()} 包`;
            if (tilt && info.tilt !== undefined) tilt.textContent = info.tilt.toFixed(1) + '°';
        } else {
            row.classList.remove('connected');
            if (meta) meta.textContent = `-- Hz · 0 包`;
            if (tilt) tilt.textContent = '--°';
        }
    });

    const badge = $('#ble-badge');
    if (badge) {
        const n = Object.values(nodes).filter(i => i.connected).length;
        badge.textContent = n > 0 ? `${n}/${Object.keys(nodes).length} 在线` : '离线';
        badge.classList.toggle('online', anyConnected);
    }
    const hd = $('#hd-ble-dot');
    if (hd) hd.classList.toggle('active', anyConnected);
}

function updateRecStatus(data) {
    const recDot   = $('#rec-dot');
    const recLabel = $('#rec-label');
    const recTime  = $('#rec-time');
    const setOverlay = $('#set-overlay');

    const rsDot    = $('#rs-dot');
    const rsStatus = $('#rs-status');
    const rsTime   = $('#rs-time');
    const rsSet    = $('#rs-set');

    if (data.recording) {
        const timeStr = formatDuration(data.elapsed);
        if (recDot)   { recDot.className = 'rec-dot recording'; }
        if (recLabel) { recLabel.textContent = 'REC'; recLabel.className = 'rec-label recording'; }
        if (recTime)  { recTime.textContent = timeStr; }
        if (setOverlay) { setOverlay.textContent = `Set #${data.set_number}`; }

        if (rsDot)    { rsDot.className = 'rs-dot recording'; }
        if (rsStatus) { rsStatus.textContent = '录制中'; rsStatus.className = 'rs-status recording'; }
        if (rsTime)   { rsTime.textContent = timeStr; }
        if (rsSet)    { rsSet.textContent = `#${data.set_number}`; }

        $('#btn-start').disabled = true;
        $('#btn-stop').disabled  = false;
    } else {
        if (recDot)   { recDot.className = 'rec-dot'; }
        if (recLabel) { recLabel.textContent = 'IDLE'; recLabel.className = 'rec-label'; }
        if (recTime)  { recTime.textContent = ''; }
        if (setOverlay) { setOverlay.textContent = ''; }

        if (rsDot)    { rsDot.className = 'rs-dot'; }
        if (rsStatus) { rsStatus.textContent = '待机'; rsStatus.className = 'rs-status'; }
        if (rsTime)   { rsTime.textContent = '--:--'; }
        if (rsSet)    { rsSet.textContent = '--'; }

        $('#btn-start').disabled = false;
        $('#btn-stop').disabled  = true;
    }
}

// ═══════════════════════════════════════════════════════
//   LIVE — button handlers
// ═══════════════════════════════════════════════════════
$('#btn-start').addEventListener('click', async () => {
    try {
        const r = await fetch('/api/recording/start', { method: 'POST' });
        const j = await r.json();
        if (j.error) toast(j.error, 'error');
        else toast(`开始录制 Set #${j.set_number}`, 'success');
    } catch {
        toast('录制启动失败', 'error');
    }
});

$('#btn-stop').addEventListener('click', async () => {
    try {
        const r = await fetch('/api/recording/stop', { method: 'POST' });
        const j = await r.json();
        if (j.error) toast(j.error, 'error');
    } catch {
        toast('停止失败', 'error');
    }
});

let currentRotation = 0;
$('#btn-rotate').addEventListener('click', async () => {
    currentRotation = (currentRotation + 90) % 360;
    await fetch('/api/camera/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rotation: currentRotation })
    });
    toast(`画面旋转至 ${currentRotation}°`, 'info', 1500);
});

$('#btn-snapshot').addEventListener('click', async () => {
    await downloadSnapshot(true);
});

$('#btn-snapshot-raw').addEventListener('click', async () => {
    await downloadSnapshot(false);
});

async function downloadSnapshot(withSkeleton) {
    try {
        const r = await fetch(`/api/camera/snapshot?skeleton=${withSkeleton ? 1 : 0}`);
        if (!r.ok) { toast('快照失败（无画面）', 'error'); return; }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.download = `snapshot_${withSkeleton ? 'skel' : 'raw'}_${ts}.jpg`;
        a.click();
        URL.revokeObjectURL(url);
        toast('快照已保存', 'success', 1800);
    } catch {
        toast('快照失败', 'error');
    }
}

$('#btn-reconnect').addEventListener('click', async () => {
    try {
        await fetch('/api/ble/reconnect', { method: 'POST' });
        toast('正在重连 BLE…', 'info');
    } catch {
        toast('重连请求失败', 'error');
    }
});

// ═══════════════════════════════════════════════════════
//   ANALYSIS — set list
// ═══════════════════════════════════════════════════════
let _currentSet = null;

async function loadSetList() {
    try {
        const res  = await fetch('/api/sets');
        const sets = await res.json();
        const sel  = $('#set-selector');
        sel.innerHTML = '';
        if (!sets || sets.length === 0) {
            sel.innerHTML = '<option value="">暂无数据</option>';
            $('#analysis-content').innerHTML = `
                <div class="analysis-placeholder">
                    <div class="placeholder-mark"></div>
                    <p>暂无训练数据 — 请先录制一组</p>
                </div>`;
            return;
        }
        sets.sort((a, b) => {
            const da = a.name.match(/(\d{8}_\d{6})/);
            const db = b.name.match(/(\d{8}_\d{6})/);
            if (da && db) return db[1].localeCompare(da[1]);
            return b.name.localeCompare(a.name);
        });
        sets.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent = `${s.name}  (${s.duration_sec}s)`;
            sel.appendChild(opt);
        });

        const target = _currentSet && sets.some(s => s.name === _currentSet)
            ? _currentSet
            : sets[0].name;
        sel.value = target;
        loadReport(target);
    } catch {
        toast('加载数据集列表失败', 'error');
    }
}

$('#set-selector').addEventListener('change', (e) => {
    if (e.target.value) loadReport(e.target.value);
});

$('#btn-refresh-sets').addEventListener('click', () => {
    loadSetList();
    toast('列表已刷新', 'info', 1200);
});

$('#btn-delete-set').addEventListener('click', async () => {
    if (!_currentSet) { toast('未选择数据集', 'warn'); return; }
    const ok = await confirmModal('删除训练组？', `将永久删除 <b>${_currentSet}</b> 及其所有数据（IMU / 视频 / 骨骼）。此操作不可撤销。`, { confirmText: '删除', danger: true });
    if (!ok) return;
    try {
        const r = await fetch(`/api/sets/${encodeURIComponent(_currentSet)}`, { method: 'DELETE' });
        const j = await r.json();
        if (j.error) { toast(j.error, 'error'); return; }
        toast(`已删除 ${_currentSet}`, 'success');
        _currentSet = null;
        loadSetList();
    } catch {
        toast('删除失败', 'error');
    }
});

// ═══════════════════════════════════════════════════════
//   ANALYSIS — render report
// ═══════════════════════════════════════════════════════
async function loadReport(name) {
    _currentSet = name;
    const content = $('#analysis-content');
    content.innerHTML = renderAnalysisSkeleton();
    const scoreInline = $('#score-inline');
    if (scoreInline) scoreInline.style.display = 'none';

    let report;
    try {
        const res = await fetch(`/api/sets/${encodeURIComponent(name)}/report`);
        report = await res.json();
    } catch {
        content.innerHTML = `<div class="analysis-placeholder"><p>加载失败</p></div>`;
        return;
    }
    if (report.error) {
        content.innerHTML = `<div class="analysis-placeholder"><p>${report.error}</p></div>`;
        return;
    }

    renderReport(name, report);

    // Fetch time-series in parallel, do NOT block main render
    fetch(`/api/sets/${encodeURIComponent(name)}/timeseries?resample=240`)
        .then(r => r.json())
        .then(ts => renderTimeseries(ts))
        .catch(() => {});
}

function renderAnalysisSkeleton() {
    return `
        <div class="skel-card"><div class="skeleton skel-line" style="width:40%"></div></div>
        <div class="score-groups">
            ${[0,1,2,3].map(() => '<div class="skel-card"><div class="skeleton skel-line"></div><div class="skeleton skel-line" style="width:60%"></div></div>').join('')}
        </div>
        <div class="skel-card"><div class="skeleton skel-block"></div></div>
    `;
}

function renderReport(name, report) {
    const hasScore = report.overall_score !== null && report.overall_score !== undefined;
    const score = hasScore ? report.overall_score : 0;
    const zone = hasScore ? scoreZone(score) : 'no_data';
    const scoreColor =
        !hasScore              ? 'var(--text-muted)' :
        zone === 'clean'       ? 'var(--clean-text)' :
        zone === 'minor'       ? 'var(--minor-text)' :
                                 'var(--major-text)';
    const scorePct = hasScore ? (score / 10 * 100).toFixed(0) : 0;

    const siScore = $('#si-score');
    if (siScore) {
        siScore.textContent = hasScore ? score.toFixed(1) : '—';
        siScore.style.color = scoreColor;
    }
    const scoreInline = $('#score-inline');
    if (scoreInline) scoreInline.style.display = 'flex';

    const imuSummary = report.imu_summary || {};
    const imuNodes = Object.keys(imuSummary);
    const totalPackets = Object.values(imuSummary).reduce((s, x) => s + (x.packets || 0), 0);
    const totalLost = Object.values(imuSummary).reduce((s, x) => s + (x.lost || 0), 0);
    const lossPct = totalPackets > 0 ? (100 * totalLost / (totalPackets + totalLost)).toFixed(2) : '0';

    // Visibility cell helper — colors the value red / yellow / green
    const visFmt = (pct) => {
        if (pct === null || pct === undefined) return { txt: '—', cls: '' };
        const cls = pct >= 80 ? 'sub-ok' : pct >= 40 ? 'sub-warn' : 'sub-bad';
        return { txt: `${pct.toFixed(0)}%`, cls };
    };
    const vg = (report.visibility && report.visibility.groups) || {};
    const vUpper = visFmt(vg.upper);
    const vTrunk = visFmt(vg.trunk);
    const vLower = visFmt(vg.lower);

    // ── Summary header (2 rows on narrow screens) ──
    const summaryHTML = `
        <div class="summary-header">
            <div class="summary-cell">
                <div class="summary-cell-label">时长</div>
                <div class="summary-cell-value">${formatDuration(report.duration)}</div>
                <div class="summary-cell-sub">${report.duration.toFixed(1)}s</div>
            </div>
            <div class="summary-cell">
                <div class="summary-cell-label">IMU 包数</div>
                <div class="summary-cell-value">${totalPackets.toLocaleString()}</div>
                <div class="summary-cell-sub ${totalLost > 0 ? 'sub-warn' : ''}">${imuNodes.length ? imuNodes.join(' · ') + ' · 丢包 ' + lossPct + '%' : '无 IMU'}</div>
            </div>
            <div class="summary-cell">
                <div class="summary-cell-label">视频帧</div>
                <div class="summary-cell-value">${report.frame_count.toLocaleString()}</div>
                <div class="summary-cell-sub">${report.fps_mean.toFixed(1)} FPS</div>
            </div>
            <div class="summary-cell">
                <div class="summary-cell-label">上身入镜</div>
                <div class="summary-cell-value ${vUpper.cls}">${vUpper.txt}</div>
                <div class="summary-cell-sub">肩/肘/腕</div>
            </div>
            <div class="summary-cell">
                <div class="summary-cell-label">躯干入镜</div>
                <div class="summary-cell-value ${vTrunk.cls}">${vTrunk.txt}</div>
                <div class="summary-cell-sub">双髋</div>
            </div>
            <div class="summary-cell">
                <div class="summary-cell-label">下身入镜</div>
                <div class="summary-cell-value ${vLower.cls}">${vLower.txt}</div>
                <div class="summary-cell-sub">膝/踝</div>
            </div>
        </div>
    `;

    // ── Score row ──
    const scoreText = hasScore ? score.toFixed(1) : '—';

    // Diagnose WHY we're missing data, using the new visibility stats
    // returned by /api/sets/{name}/report.
    let noDataBanner = '';
    if (!hasScore) {
        const vis = report.visibility || {};
        const g = vis.groups || {};
        const missing = [];
        if (g.lower !== undefined && g.lower !== null && g.lower < 20) missing.push(`下半身 ${g.lower}%`);
        if (g.trunk !== undefined && g.trunk !== null && g.trunk < 40) missing.push(`躯干 ${g.trunk}%`);
        if (g.upper !== undefined && g.upper !== null && g.upper < 40) missing.push(`上半身 ${g.upper}%`);
        const imuMissing = !report.imu_summary || Object.keys(report.imu_summary).length === 0;

        const bits = [];
        if (missing.length) {
            bits.push(`视觉：${missing.join(' / ')} 入镜率过低`);
        }
        if (imuMissing) bits.push('IMU：本次录制无 IMU 数据');
        const diag = bits.length
            ? `<b>原因：</b>${bits.join('；')}。`
            : '本训练组数据不足。';
        noDataBanner = `<div class="no-data-banner">
            ⚠️ 无法给出综合评分。${diag}
            <br><span style="color:var(--text-muted)">建议：相机后退 2 米让整个身体入镜；开始录制前确认 BLE 节点在线；Ballet Leg 侧面拍摄。</span>
        </div>`;
    }
    const scoreRowHTML = `
        ${noDataBanner}
        <div class="score-row">
            <div class="score-num-block">
                <span class="score-num mono" style="color:${scoreColor}">${scoreText}</span>
                <span class="score-denom mono">&thinsp;/&thinsp;10</span>
            </div>
            <div class="score-bar-col">
                <span class="score-bar-label">综合评分</span>
                <div class="score-bar-track">
                    <div class="score-bar-fill" style="width:${scorePct}%; background:${scoreColor}"></div>
                </div>
            </div>
        </div>
    `;

    // ── Multi-dim score groups ──
    const groupsHTML = `
        <div class="metrics-section-title">多维评分</div>
        <div class="score-groups">
            ${Object.entries(report.score_breakdown || {}).map(([key, g]) => {
                const has = g.score !== null && g.score !== undefined;
                const gz = has ? (g.zone || scoreZone(g.score)) : 'no_data';
                const pct = has ? Math.max(0, Math.min(100, g.score / 10 * 100)) : 0;
                const names = (g.contributors || []).map(n => METRIC_LABELS[n] || n).join(' · ');
                const shown = has ? g.score.toFixed(1) : '—';
                return `
                    <div class="score-group-card">
                        <div class="sg-icon">${GROUP_ICONS[key] || '•'}</div>
                        <div class="sg-name">${GROUP_NAMES[key] || key}</div>
                        <div class="sg-score-row">
                            <span class="sg-score zone-${gz} mono">${shown}</span>
                            <span class="sg-denom">/ 10</span>
                        </div>
                        <div class="sg-contrib">${names || '无数据'}</div>
                        <div class="sg-bar"><div class="sg-bar-fill zone-${gz}" style="width:${pct}%"></div></div>
                    </div>
                `;
            }).join('')}
        </div>
    `;

    // ── Video + Timeseries row ──
    const videoHTML = report.has_video ? `
        <div class="video-player-card">
            <div class="vp-header">
                <span class="vp-title">视频回放</span>
                <button class="vp-athletes-btn" id="vp-athletes-btn" type="button" title="给检测到的运动员命名">队员</button>
                <label class="vp-overlay-toggle active" id="vp-toggle">
                    <span>骨架叠加</span>
                    <span class="toggle-switch"></span>
                </label>
            </div>
            <div class="vp-wrapper">
                <video id="vp-video" class="vp-video" controls src="/api/sets/${encodeURIComponent(name)}/video"></video>
                <canvas id="vp-skeleton" class="vp-skeleton-canvas"></canvas>
            </div>
        </div>
    ` : `
        <div class="video-player-card">
            <div class="vp-header"><span class="vp-title">视频回放</span></div>
            <div class="vp-wrapper">
                <div class="vp-placeholder"><span>此训练组无视频</span></div>
            </div>
        </div>
    `;

    const tsHTML = `
        <div class="timeseries-card">
            <div class="ts-header">
                <span class="ts-title">时序曲线</span>
                <div class="ts-legend" id="ts-legend"></div>
            </div>
            <div class="ts-chart-wrap">
                <canvas id="ts-canvas" class="ts-canvas"></canvas>
            </div>
        </div>
    `;

    // ── Keyframes section (default 3, toggle 6) ──
    const keyframesHTML = `
        <div class="keyframes-section">
            <div class="keyframes-toolbar">
                <span class="kf-count-label">关键帧数量</span>
                <div class="kf-count-buttons">
                    <button class="kf-count-btn active" data-count="3">3</button>
                    <button class="kf-count-btn" data-count="6">6</button>
                </div>
            </div>
            <div id="keyframes-row" class="keyframes-row"></div>
        </div>
    `;

    // ── Metric cards ──
    const metricsHTML = report.metrics && report.metrics.length
        ? buildMetricCards(report.metrics)
        : '<p style="color:var(--text-muted);font-size:0.85rem">暂无指标数据</p>';

    // ── Sensor card ──
    const sensorHTML = buildSensorSection(report);

    // ── Compose ──
    $('#analysis-content').innerHTML = `
        ${summaryHTML}
        ${scoreRowHTML}
        ${groupsHTML}
        <div class="video-analysis-row">
            ${videoHTML}
            ${tsHTML}
        </div>
        ${keyframesHTML}
        <div class="metrics-section-title">详细指标</div>
        <div class="metrics-grid">${metricsHTML}</div>
        <div class="analysis-bottom">
            <div class="radar-card">
                <div class="radar-title">雷达图 — 综合表现</div>
                <canvas id="radar-canvas"></canvas>
            </div>
            ${sensorHTML}
        </div>
    `;

    // radar — only real metrics
    const radarCanvas = $('#radar-canvas');
    const radarMetrics = (report.metrics || []).filter(m =>
        m.value !== null && m.value !== undefined && m.zone !== 'no_data'
    );
    if (radarCanvas && radarMetrics.length >= 3) {
        requestAnimationFrame(() => drawRadar(radarCanvas, radarMetrics));
    } else if (radarCanvas) {
        const ctx = radarCanvas.getContext('2d');
        radarCanvas.width = 240; radarCanvas.height = 240;
        ctx.fillStyle = 'rgba(140,150,180,0.6)';
        ctx.font = '12px "Fira Sans", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('数据不足，无法绘制雷达图', 120, 120);
    }

    // keyframes
    renderKeyframes(name, 3, report.phases);

    // kf toggle
    $$('.kf-count-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const n = parseInt(btn.dataset.count, 10);
            $$('.kf-count-btn').forEach(b => b.classList.toggle('active', b === btn));
            renderKeyframes(name, n, report.phases);
        });
    });

    // overlay toggle
    const tgl = $('#vp-toggle');
    if (tgl) {
        tgl.addEventListener('click', () => tgl.classList.toggle('active'));
    }
    // Athlete-management modal trigger
    const aBtn = $('#vp-athletes-btn');
    if (aBtn) {
        aBtn.addEventListener('click', () => openAthleteManager(name));
    }
    setupSkeletonOverlay(name);
}

// ─── Build metric cards (detailed) ────────────────────
function buildMetricCards(metrics) {
    const order = [
        // Visual / geometry (from paper 1: Edriss 2024)
        'leg_deviation','knee_extension','shoulder_knee_alignment','trunk_vertical',
        'leg_symmetry','leg_height_index',
        // Temporal / dynamics (from paper 2: Yue 2023)
        'movement_frequency','rotation_frequency','mean_pattern_duration','last_hf_duration',
        // IMU-native unique metrics (our system's advantage)
        'smoothness','stability','explosive_power','energy_index','motion_complexity',
    ];
    const map = {};
    metrics.forEach(m => { map[m.name] = m; });
    return order.map(name => {
        const m = map[name];
        if (!m) return '';
        const label   = METRIC_LABELS[name] || name;
        const unit    = m.unit === 'deg' ? '°' : (m.unit || '');
        const zone    = m.zone || 'clean';
        const zoneTxt = ZONE_LABELS[zone];
        const hint    = METRIC_HINTS[name] || '';

        if (zone === 'no_data' || m.value === null || m.value === undefined) {
            return `
                <div class="metric-card no-data" data-metric="${name}">
                    <div class="mc-name">${label}</div>
                    <div class="mc-value-row">
                        <span class="mc-value mono">—</span>
                    </div>
                    <div class="mc-zone zone-no_data">无数据</div>
                    <div class="mc-bar-track"><div class="mc-bar-fill zone-no_data" style="width:0%"></div></div>
                </div>
            `;
        }

        const radar  = normalizeForRadar(name, m.value);
        const barPct = radar.toFixed(0);
        return `
            <div class="metric-card" data-metric="${name}">
                <div class="mc-name">${label}${hint ? ` · <span style="color:var(--text-muted);font-size:0.68rem">${hint}</span>` : ''}</div>
                <div class="mc-value-row">
                    <span class="mc-value mono">${typeof m.value === 'number' ? m.value.toFixed(1) : m.value}</span>
                    <span class="mc-unit mono">${unit}</span>
                </div>
                <div class="mc-zone zone-${zone}">${zoneTxt} · -${(m.deduction || 0).toFixed(1)}</div>
                <div class="mc-bar-track">
                    <div class="mc-bar-fill zone-${zone}" style="width:${barPct}%"></div>
                </div>
            </div>
        `;
    }).join('');
}

// ─── Sensor summary (IMU nodes + correlation + phases) ────
function buildSensorSection(report) {
    const imu = report.imu_summary || {};
    const corrVal = (report.correlation !== null && report.correlation !== undefined)
        ? report.correlation.toFixed(3)
        : '--';
    const nodeBlocks = Object.entries(imu).map(([node, info]) => `
        <div class="imu-node-block">
            <div class="imu-node-header">
                <span class="imu-node-label">${node}</span>
            </div>
            <div class="imu-node-body">
                <div class="imu-stat"><span class="imu-stat-label">数据包</span><span class="imu-stat-value mono">${info.packets.toLocaleString()}</span></div>
                <div class="imu-stat"><span class="imu-stat-label">频率</span><span class="imu-stat-value mono">${info.rate.toFixed(1)} Hz</span></div>
                <div class="imu-stat"><span class="imu-stat-label">时长</span><span class="imu-stat-value mono">${info.duration.toFixed(1)} s</span></div>
                <div class="imu-stat"><span class="imu-stat-label">倾角均值</span><span class="imu-stat-value mono">${info.tilt_mean.toFixed(1)}°</span></div>
                <div class="imu-stat"><span class="imu-stat-label">倾角标差</span><span class="imu-stat-value mono">${info.tilt_std.toFixed(1)}°</span></div>
                <div class="imu-stat"><span class="imu-stat-label">丢包</span><span class="imu-stat-value mono" style="color:${info.lost > 0 ? 'var(--minor-text)' : 'inherit'}">${info.lost} (${info.loss_pct}%)</span></div>
            </div>
        </div>
    `).join('');

    return `
        <div class="sensor-card">
            <div class="sensor-title">传感器数据</div>
            ${nodeBlocks || '<p style="color:var(--text-muted);font-size:0.8rem">无 IMU 数据</p>'}
            <div class="correlation-row">
                <span class="corr-label">IMU ↔ 视觉 相关系数</span>
                <span class="corr-value mono">${corrVal}</span>
            </div>
            ${buildPhaseTimeline(report.phases)}
        </div>
    `;
}

function buildPhaseTimeline(phases) {
    if (!phases || phases.length === 0) return '';
    const total = phases.reduce((s, p) => s + (p.end - p.start), 0) || 1;
    const segments = phases.map(p => {
        const pct = ((p.end - p.start) / total * 100).toFixed(1);
        const key = p.phase || p.name || 'prep';
        const cls = ({ prep: 'prep', exhibition: 'exhibition', recovery: 'recovery',
                      '准备': 'prep', '动作': 'exhibition', '恢复': 'recovery' })[key] || 'prep';
        const lbl = PHASE_NAMES[key] || key;
        return `<div class="phase-segment ${cls}" style="width:${pct}%" title="${lbl}: ${p.start.toFixed(1)} – ${p.end.toFixed(1)}s">${pct > 15 ? lbl : ''}</div>`;
    }).join('');
    const phasesSet = [...new Set(phases.map(p => {
        const k = p.phase || p.name;
        return ({ prep: 'prep', exhibition: 'exhibition', recovery: 'recovery',
                 '准备': 'prep', '动作': 'exhibition', '恢复': 'recovery' })[k] || 'prep';
    }))];
    const legend = phasesSet.map(ph =>
        `<div class="phase-legend-item"><div class="phase-legend-dot ${ph}"></div><span>${PHASE_NAMES[ph] || ph}</span></div>`
    ).join('');
    return `
        <div class="phase-timeline-section">
            <div class="phase-timeline-label">阶段时间轴</div>
            <div class="phase-timeline-track">${segments}</div>
            <div class="phase-legend">${legend}</div>
        </div>
    `;
}

// ─── Keyframes rendering ──────────────────────────────
function renderKeyframes(setName, count, phases) {
    const row = $('#keyframes-row');
    if (!row) return;
    row.classList.toggle('kf-6', count === 6);
    const labels = phases && phases.length === 3 && count === 3
        ? phases.map(p => (PHASE_NAMES[p.phase || p.name] || p.name || p.phase))
        : Array.from({ length: count }).map((_, i) => `F${i + 1}`);

    row.innerHTML = Array.from({ length: count }).map((_, i) => {
        const src = `/api/sets/${encodeURIComponent(setName)}/keyframes/${i}?count=${count}`;
        const lbl = labels[i];
        return `
            <div class="keyframe-card">
                <div class="kf-image-wrap">
                    <img src="${src}" alt="${lbl}" loading="lazy"
                         onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
                    <div class="kf-placeholder" style="display:none"><div class="kf-placeholder-inner"></div></div>
                </div>
                <div class="kf-label">
                    <span class="kf-phase-name">${lbl}</span>
                    <span class="kf-index mono">F${i + 1}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ─── Radar (kept from prior impl, slightly refined) ────
function drawRadar(canvas, metrics) {
    const dpr = window.devicePixelRatio || 1;
    const size = Math.min(canvas.parentElement.clientWidth - 36, 320);
    canvas.style.width  = size + 'px';
    canvas.style.height = size + 'px';
    canvas.width  = size * dpr;
    canvas.height = size * dpr;
    const c = canvas.getContext('2d');
    c.scale(dpr, dpr);

    const cx = size / 2, cy = size / 2, r = size * 0.36;
    const n = metrics.length;
    const labels = metrics.map(m => METRIC_LABELS[m.name] || m.name);
    const values = metrics.map(m => normalizeForRadar(m.name, m.value));

    const rings = [0.25, 0.5, 0.75, 1.0];
    rings.forEach((frac, ri) => {
        c.beginPath();
        for (let i = 0; i < n; i++) {
            const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
            const x = cx + Math.cos(angle) * r * frac;
            const y = cy + Math.sin(angle) * r * frac;
            if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
        }
        c.closePath();
        c.strokeStyle = ri === rings.length - 1 ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.06)';
        c.lineWidth = ri === rings.length - 1 ? 1.5 : 1;
        c.stroke();
    });

    c.strokeStyle = 'rgba(255,255,255,0.08)';
    c.lineWidth = 1;
    for (let i = 0; i < n; i++) {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        c.beginPath();
        c.moveTo(cx, cy);
        c.lineTo(cx + Math.cos(angle) * r, cy + Math.sin(angle) * r);
        c.stroke();
    }

    const pts = values.map((v, i) => {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const frac  = v / 100;
        return [cx + Math.cos(angle) * r * frac, cy + Math.sin(angle) * r * frac];
    });
    c.beginPath();
    pts.forEach(([x, y], i) => { if (i === 0) c.moveTo(x, y); else c.lineTo(x, y); });
    c.closePath();
    c.fillStyle = 'rgba(30,64,175,0.35)';
    c.fill();
    c.strokeStyle = '#3B82F6';
    c.lineWidth = 2;
    c.stroke();

    pts.forEach(([x, y]) => {
        c.beginPath(); c.arc(x, y, 4, 0, Math.PI * 2);
        c.fillStyle = '#3B82F6'; c.fill();
        c.beginPath(); c.arc(x, y, 2, 0, Math.PI * 2);
        c.fillStyle = '#fff'; c.fill();
    });

    const labelR = r + size * 0.10;
    c.font = `${Math.round(size * 0.032)}px "Fira Sans", sans-serif`;
    c.fillStyle = 'rgba(200,210,230,0.85)';
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    labels.forEach((label, i) => {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const lx = cx + Math.cos(angle) * labelR;
        const ly = cy + Math.sin(angle) * labelR;
        const words = label.match(/.{1,4}/gu) || [label];
        const lineH = size * 0.036;
        words.forEach((word, wi) => {
            c.fillText(word, lx, ly + (wi - (words.length - 1) / 2) * lineH);
        });
    });
}

// ═══════════════════════════════════════════════════════
//   ANALYSIS — Timeseries chart (Canvas 2D)
// ═══════════════════════════════════════════════════════
let _tsState = { data: null, active: new Set() };

function renderTimeseries(ts) {
    if (!ts || !ts.series) return;
    const keys = Object.keys(ts.series).filter(k => ts.series[k] && ts.series[k].length > 0);
    if (keys.length === 0) {
        const wrap = $('.ts-chart-wrap');
        if (wrap) wrap.innerHTML = '<p style="color:var(--text-muted);font-size:0.82rem;padding:20px">无时序数据</p>';
        return;
    }

    _tsState = { data: ts, active: new Set(keys) };

    const legend = $('#ts-legend');
    if (legend) {
        legend.innerHTML = keys.map(k => `
            <span class="ts-legend-item active" data-key="${k}">
                <span class="ts-legend-dot" style="background:${SERIES_COLORS[k] || '#888'}"></span>
                ${SERIES_LABELS[k] || k}
            </span>
        `).join('');
        $$('.ts-legend-item', legend).forEach(it => {
            it.addEventListener('click', () => {
                const k = it.dataset.key;
                if (_tsState.active.has(k)) { _tsState.active.delete(k); it.classList.add('inactive'); it.classList.remove('active'); }
                else { _tsState.active.add(k); it.classList.add('active'); it.classList.remove('inactive'); }
                drawTimeseries();
            });
        });
    }

    drawTimeseries();
    window.addEventListener('resize', drawTimeseries, { passive: true });
}

function drawTimeseries() {
    const ts = _tsState.data;
    if (!ts) return;
    const canvas = $('#ts-canvas');
    if (!canvas) return;

    const wrap = canvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const W = wrap.clientWidth, H = Math.max(220, wrap.clientHeight);
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';
    const c = canvas.getContext('2d');
    c.scale(dpr, dpr);
    c.clearRect(0, 0, W, H);

    const padL = 40, padR = 10, padT = 14, padB = 28;
    const chartW = W - padL - padR, chartH = H - padT - padB;

    // Collect visible series with per-series normalization range
    const series = Array.from(_tsState.active).map(k => ({
        key: k,
        color: SERIES_COLORS[k] || '#888',
        data: ts.series[k],
    })).filter(s => s.data && s.data.length > 0);

    if (series.length === 0) {
        c.fillStyle = 'rgba(180,180,200,0.4)';
        c.font = '12px "Fira Sans", sans-serif';
        c.textAlign = 'center';
        c.fillText('选择一条曲线以显示', W / 2, H / 2);
        return;
    }

    // Range: union of all series (ignore null/NaN for occluded frames)
    let yMin = Infinity, yMax = -Infinity;
    series.forEach(s => {
        s.data.forEach(v => {
            if (v == null || Number.isNaN(v)) return;
            if (v < yMin) yMin = v;
            if (v > yMax) yMax = v;
        });
    });
    if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) { yMin = 0; yMax = 1; }
    if (yMin === yMax) { yMin -= 1; yMax += 1; }
    const yPad = (yMax - yMin) * 0.1;
    yMin -= yPad; yMax += yPad;

    // Grid
    c.strokeStyle = 'rgba(255,255,255,0.05)';
    c.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padT + chartH * i / 4;
        c.beginPath();
        c.moveTo(padL, y);
        c.lineTo(padL + chartW, y);
        c.stroke();
        const val = yMax - (yMax - yMin) * i / 4;
        c.fillStyle = 'rgba(140,150,180,0.65)';
        c.font = '10px "Fira Code", monospace';
        c.textAlign = 'right';
        c.fillText(val.toFixed(0), padL - 6, y + 3);
    }

    // X axis labels (0, mid, end)
    const duration = ts.duration || 1;
    c.fillStyle = 'rgba(140,150,180,0.6)';
    c.textAlign = 'center';
    c.font = '10px "Fira Code", monospace';
    ['0s', (duration / 2).toFixed(1) + 's', duration.toFixed(1) + 's'].forEach((lbl, i) => {
        const x = padL + chartW * i / 2;
        c.fillText(lbl, x, H - 8);
    });

    // Draw each series — break path on null (occluded)
    series.forEach(s => {
        c.strokeStyle = s.color;
        c.lineWidth = 1.6;
        c.beginPath();
        let pen = false;
        s.data.forEach((v, i) => {
            if (v == null || Number.isNaN(v)) { pen = false; return; }
            const x = padL + (chartW * i) / (s.data.length - 1);
            const y = padT + chartH * (1 - (v - yMin) / (yMax - yMin));
            if (!pen) { c.moveTo(x, y); pen = true; }
            else c.lineTo(x, y);
        });
        c.stroke();
    });
}

// ═══════════════════════════════════════════════════════
//   ANALYSIS — Skeleton overlay on played video
// ═══════════════════════════════════════════════════════
let _skelLandmarks = null;
let _skelFrameRAF = null;

// Module-level handle to the currently-displayed overlay so the
// athlete-manager modal can mutate ``athlete_map`` after a binding
// change without rebuilding the whole overlay (which would re-bind
// every video event listener and accumulate them on each open).
let _activeOverlay = null;   // { setName, landmarks }

async function setupSkeletonOverlay(name) {
    const video  = $('#vp-video');
    const canvas = $('#vp-skeleton');
    const tgl    = $('#vp-toggle');
    if (!video || !canvas) return;

    // Fetch landmarks once (may be large for long sets; ~30KB/sec of video)
    let landmarks = null;
    try {
        const r = await fetch(`/api/sets/${encodeURIComponent(name)}/landmarks`);
        if (r.ok) landmarks = await r.json();
    } catch { landmarks = null; }

    _activeOverlay = { setName: name, landmarks };

    const c2 = canvas.getContext('2d');

    function findFrameIdx(t) {
        if (!landmarks || !landmarks.times || landmarks.times.length === 0) return -1;
        const n = landmarks.frames.length;

        // Ratio-based lookup is the only reliable way to stay in sync:
        // the MP4 is re-encoded at a fixed 25 fps by VideoWriter, but the
        // actual camera delivers 20-30 fps. landmarks.csv timestamps are
        // real wall-clock seconds, so video.currentTime / video.duration
        // (both in "video time") may drift from landmarks.times[]
        // (wall-clock time) by hundreds of ms. Mapping by *proportion* of
        // each timeline removes that drift.
        if (video && isFinite(video.duration) && video.duration > 0) {
            const ratio = Math.max(0, Math.min(1, video.currentTime / video.duration));
            return Math.min(n - 1, Math.max(0, Math.round(ratio * (n - 1))));
        }

        // Fallback — binary search on wall-clock times if we somehow
        // don't have video.duration yet.
        const times = landmarks.times;
        let lo = 0, hi = n - 1;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (times[mid] < t) lo = mid + 1;
            else hi = mid;
        }
        if (lo > 0 && Math.abs(times[lo - 1] - t) < Math.abs(times[lo] - t)) lo--;
        return lo;
    }

    function resizeCanvas() {
        // Match displayed video size (after letterboxing)
        const rect = video.getBoundingClientRect();
        const vw = video.videoWidth  || rect.width;
        const vh = video.videoHeight || rect.height;
        if (!vw || !vh) return { x: 0, y: 0, w: rect.width, h: rect.height };

        // object-fit: contain math — compute letterbox offsets in CSS pixels
        const scale = Math.min(rect.width / vw, rect.height / vh);
        const drawW = vw * scale;
        const drawH = vh * scale;
        const x = (rect.width  - drawW) / 2;
        const y = (rect.height - drawH) / 2;

        canvas.width  = Math.max(1, Math.round(rect.width));
        canvas.height = Math.max(1, Math.round(rect.height));
        return { x, y, w: drawW, h: drawH };
    }

    function drawPersonAt(box, pts, color, label) {
        if (!pts || pts.length !== 33) return;
        const toXY = (p) => ({ x: box.x + p[0] * box.w, y: box.y + p[1] * box.h, v: p[2] });

        c2.strokeStyle = color + 'E6';  // ~90% opacity
        c2.lineWidth = 2;
        CONNECTIONS.forEach(([i, j]) => {
            const a = toXY(pts[i]); const b = toXY(pts[j]);
            if (a.v > 0.3 && b.v > 0.3) {
                c2.beginPath(); c2.moveTo(a.x, a.y); c2.lineTo(b.x, b.y); c2.stroke();
            }
        });
        for (let i = 0; i < 33; i++) {
            const p = toXY(pts[i]);
            if (p.v < 0.3) continue;
            c2.fillStyle = color;
            c2.beginPath(); c2.arc(p.x, p.y, 3.5, 0, Math.PI * 2); c2.fill();
            c2.fillStyle = '#fff';
            c2.beginPath(); c2.arc(p.x, p.y, 1.4, 0, Math.PI * 2); c2.fill();
        }
        // Tag above head — caller decides what to render. Falsy/empty
        // string means "no label" (e.g. the legacy primary swimmer
        // path that wants to stay uncluttered).
        if (label) {
            let lx = 0, ly = 0, ok = false;
            if (pts[0][2] > 0.3) {
                lx = box.x + pts[0][0] * box.w;
                ly = box.y + pts[0][1] * box.h - 18;
                ok = true;
            } else if (pts[11][2] > 0.3 && pts[12][2] > 0.3) {
                lx = box.x + (pts[11][0] + pts[12][0]) / 2 * box.w;
                ly = box.y + (pts[11][1] + pts[12][1]) / 2 * box.h - 24;
                ok = true;
            }
            if (ok) {
                c2.font = 'bold 12px "Fira Code", monospace';
                const tw = c2.measureText(label).width;
                c2.fillStyle = color;
                c2.beginPath(); c2.roundRect(lx - tw / 2 - 5, ly - 11, tw + 10, 16, 4); c2.fill();
                c2.fillStyle = '#fff';
                c2.textAlign = 'center'; c2.textBaseline = 'middle';
                c2.fillText(label, lx, ly - 3);
                c2.textAlign = 'start'; c2.textBaseline = 'alphabetic';
            }
        }
    }

    // Per-person colour and label resolution. Three-layer fallback:
    //   1. Athlete binding (phase 7.2) — coach has named #3 → "张三"
    //      and optionally pinned a colour. Highest priority.
    //   2. BYTETracker ID (phase 7.1) — colour bound to the ID itself
    //      so the same swimmer keeps the same hue across frames AND
    //      across Sets (foundation for cross-Set comparison in 7.3).
    //   3. Array-index fallback — older recordings, MediaPipe backend,
    //      or brand-new detections that don't have an ID yet.
    //
    // ``athleteMap`` is keyed by ``String(track_id)`` because JSON
    // object keys are always strings.
    function colourFor(arrayIdx, trackId, athleteMap) {
        if (trackId != null) {
            const ath = athleteMap && athleteMap[String(trackId)];
            if (ath && ath.color) return ath.color;
            return TEAM_COLORS[trackId % TEAM_COLORS.length];
        }
        if (arrayIdx === 0) return '#3B82F6';
        return TEAM_COLORS[arrayIdx % TEAM_COLORS.length];
    }
    function labelFor(arrayIdx, trackId, athleteMap) {
        if (trackId != null) {
            const ath = athleteMap && athleteMap[String(trackId)];
            if (ath && ath.name) return ath.name;
            return `#${trackId}`;
        }
        if (arrayIdx === 0) return '';   // legacy: don't clutter primary
        return `P${arrayIdx + 1}`;
    }

    function drawOverlay() {
        const box = resizeCanvas();
        c2.clearRect(0, 0, canvas.width, canvas.height);
        if (!tgl.classList.contains('active')) return;
        if (!landmarks) return;

        const idx = findFrameIdx(video.currentTime);
        if (idx < 0) return;

        // Multi-person playback: if the server returned all_frames,
        // draw each athlete with their own distinct colour. Stable
        // BYTETracker IDs (when present) bind colour to athlete
        // instead of array position, so the same swimmer keeps the
        // same hue even when their relative position in the frame
        // changes from one moment to the next. ``athlete_map`` (when
        // present) overrides both colour and label with the coach's
        // assigned name (phase 7.2).
        if (landmarks.all_frames && landmarks.all_frames[idx]) {
            const persons = landmarks.all_frames[idx];
            const ids = (landmarks.all_ids && landmarks.all_ids[idx]) || [];
            const aMap = landmarks.athlete_map || {};
            // Draw teammates first so the primary (or whoever is at
            // index 0 — usually the closest-to-camera athlete) ends
            // up on top.
            for (let p = 1; p < persons.length; p++) {
                drawPersonAt(
                    box, persons[p],
                    colourFor(p, ids[p], aMap),
                    labelFor(p, ids[p], aMap),
                );
            }
            if (persons.length > 0) {
                drawPersonAt(
                    box, persons[0],
                    colourFor(0, ids[0], aMap),
                    labelFor(0, ids[0], aMap),
                );
                return;
            }
        }

        // Single-person fallback (older sets without landmarks_multi.jsonl)
        const pts = landmarks.frames[idx];
        drawPersonAt(box, pts, '#3B82F6', '');
    }

    // rAF loop only while playing for smoothness
    let rafId = null;
    function loop() {
        drawOverlay();
        if (!video.paused && !video.ended) rafId = requestAnimationFrame(loop);
    }
    video.addEventListener('play',  () => { cancelAnimationFrame(rafId); loop(); });
    video.addEventListener('pause', () => { cancelAnimationFrame(rafId); drawOverlay(); });
    video.addEventListener('seeked', drawOverlay);
    video.addEventListener('loadedmetadata', drawOverlay);
    video.addEventListener('timeupdate', () => { if (video.paused) drawOverlay(); });
    tgl.addEventListener('click', drawOverlay);
    window.addEventListener('resize', drawOverlay, { passive: true });

    // Initial paint once metadata is ready
    if (video.readyState >= 1) drawOverlay();
}

// ═══════════════════════════════════════════════════════
//   ATHLETE MANAGER (phase 7.2)
// ═══════════════════════════════════════════════════════
//   Coach assigns a stable name to each BYTETracker ID detected
//   in this Set. The binding is per-Set because BYTETracker state
//   resets between recordings (see DEVLOG #25).
//
//   On bind/unbind we mutate ``_activeOverlay.landmarks.athlete_map``
//   in place — drawOverlay() reads from this object reference every
//   frame, so the skeleton labels update on the next render without
//   re-running setupSkeletonOverlay() (which would accumulate event
//   listeners).
//
async function openAthleteManager(setName) {
    if (!setName) return;

    // Aggregate every distinct (non-null) track_id observed in this
    // recording. ByteTrack assigns IDs from 1, but old recordings
    // (before phase 7.1) won't have any IDs at all — show a friendly
    // "nothing to bind" hint in that case.
    const detectedIds = new Set();
    if (_activeOverlay && _activeOverlay.landmarks
        && Array.isArray(_activeOverlay.landmarks.all_ids)) {
        for (const frameIds of _activeOverlay.landmarks.all_ids) {
            for (const id of (frameIds || [])) {
                if (id != null) detectedIds.add(id);
            }
        }
    }
    const sortedIds = [...detectedIds].sort((a, b) => a - b);

    // Snapshot of the existing roster so we can offer it in the picker.
    let athletes = [];
    try {
        const r = await fetch('/api/athletes');
        if (r.ok) athletes = (await r.json()).athletes || [];
    } catch {}

    // Per-Set binding map (mutated in place as we bind/unbind).
    const aMap = (_activeOverlay && _activeOverlay.landmarks
                  && _activeOverlay.landmarks.athlete_map) || {};

    const root = $('#modal-root');
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    function escapeHTML(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function rowsHTML() {
        if (sortedIds.length === 0) {
            return `<div class="ath-empty">本组没有检测到带稳定 ID 的运动员
                    （旧录制 / MediaPipe backend / 单人都属此情况）。</div>`;
        }
        return sortedIds.map(id => {
            const swatch = `<span class="ath-swatch" style="background:${TEAM_COLORS[id % TEAM_COLORS.length]}"></span>`;
            const idTag = `<span class="ath-id">#${id}</span>`;
            const bound = aMap[String(id)];
            if (bound) {
                return `<div class="ath-row" data-track-id="${id}">
                    ${swatch}${idTag}
                    <span class="ath-name">${escapeHTML(bound.name)}</span>
                    <button class="ath-unbind"
                            data-track-id="${id}"
                            data-athlete-id="${escapeHTML(bound.athlete_id)}">解绑</button>
                </div>`;
            }
            const opts = athletes.map(a =>
                `<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}</option>`
            ).join('');
            return `<div class="ath-row" data-track-id="${id}">
                ${swatch}${idTag}
                <select class="ath-select" data-track-id="${id}">
                    <option value="">— 选择运动员 —</option>
                    ${opts}
                    <option value="__new__">＋ 新建运动员…</option>
                </select>
            </div>`;
        }).join('');
    }

    function render() {
        overlay.innerHTML = `
            <div class="modal-box ath-modal">
                <div class="modal-title">队员管理 · ${escapeHTML(setName)}</div>
                <div class="modal-body">
                    <div class="ath-hint">
                        本组检测到的 BYTETracker ID。给每个 ID 绑定一个运动员后，
                        骨架标签会从 <code>#3</code> 升级为运动员姓名。绑定是 per-Set 的，
                        因为追踪 ID 每次录制都会重置（DEVLOG #25）。
                    </div>
                    <div class="ath-rows">${rowsHTML()}</div>
                </div>
                <div class="modal-actions">
                    <button class="modal-btn modal-btn-cancel" id="ath-close">关闭</button>
                </div>
            </div>
        `;
        overlay.querySelector('#ath-close').onclick = closeModal;
        overlay.querySelectorAll('.ath-select').forEach(sel => {
            sel.addEventListener('change', () => onPick(sel));
        });
        overlay.querySelectorAll('.ath-unbind').forEach(btn => {
            btn.addEventListener('click', () => onUnbind(btn));
        });
    }

    async function onPick(sel) {
        const trackId = parseInt(sel.dataset.trackId, 10);
        let athleteId = sel.value;
        if (!athleteId) return;

        if (athleteId === '__new__') {
            const name = window.prompt('运动员姓名：');
            if (!name || !name.trim()) { sel.value = ''; return; }
            try {
                const r = await fetch('/api/athletes', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name.trim() }),
                });
                if (!r.ok) throw 0;
                const ath = await r.json();
                athletes.push(ath);
                athleteId = ath.id;
            } catch {
                toast('创建运动员失败', 'error');
                sel.value = '';
                return;
            }
        }

        try {
            const r = await fetch(`/api/athletes/${encodeURIComponent(athleteId)}/bind`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ set: setName, track_id: trackId }),
            });
            if (!r.ok) throw 0;
            const ath = await r.json();
            // Conflict resolution on the server may have stolen this
            // (set, track_id) from another athlete — clear stale local
            // entries with the same id before writing the new one.
            for (const k of Object.keys(aMap)) {
                if (aMap[k].athlete_id === ath.id && k !== String(trackId)) {
                    // not our concern: that's a *different* track_id
                    // for the same athlete, which is allowed
                }
            }
            aMap[String(trackId)] = {
                athlete_id: ath.id,
                name: ath.name,
                color: ath.color,
            };
            if (_activeOverlay && _activeOverlay.landmarks) {
                _activeOverlay.landmarks.athlete_map = aMap;
            }
            toast(`#${trackId} → ${ath.name}`, 'success');
            render();
        } catch {
            toast('绑定失败', 'error');
            sel.value = '';
        }
    }

    async function onUnbind(btn) {
        const trackId = parseInt(btn.dataset.trackId, 10);
        const athleteId = btn.dataset.athleteId;
        try {
            const r = await fetch(`/api/athletes/${encodeURIComponent(athleteId)}/unbind`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ set: setName, track_id: trackId }),
            });
            if (!r.ok) throw 0;
            delete aMap[String(trackId)];
            if (_activeOverlay && _activeOverlay.landmarks) {
                _activeOverlay.landmarks.athlete_map = aMap;
            }
            toast(`#${trackId} 已解绑`, 'success');
            render();
        } catch {
            toast('解绑失败', 'error');
        }
    }

    function closeModal() {
        overlay.remove();
        document.removeEventListener('keydown', keyHandler);
    }
    const keyHandler = (e) => { if (e.key === 'Escape') closeModal(); };
    document.addEventListener('keydown', keyHandler);
    overlay.onclick = e => { if (e.target === overlay) closeModal(); };

    render();
    root.appendChild(overlay);
}

// ═══════════════════════════════════════════════════════
//   HISTORY VIEW
// ═══════════════════════════════════════════════════════
let _historyData = [];

async function loadHistory() {
    const grid = $('#history-grid');
    grid.innerHTML = `
        <div class="skel-card"><div class="skeleton skel-block"></div></div>
        <div class="skel-card"><div class="skeleton skel-block"></div></div>
        <div class="skel-card"><div class="skeleton skel-block"></div></div>
    `;
    try {
        const r = await fetch('/api/sets');
        _historyData = await r.json();
    } catch {
        grid.innerHTML = '<div class="analysis-placeholder"><p>加载失败</p></div>';
        return;
    }
    renderHistory();
}

function renderHistory() {
    const grid  = $('#history-grid');
    const stats = $('#history-stats');
    const search = $('#history-search').value.trim().toLowerCase();
    const sort  = $('#history-sort').value;

    let items = _historyData.filter(s => !search || s.name.toLowerCase().includes(search));

    items.sort((a, b) => {
        const da = (a.name.match(/(\d{8}_\d{6})/) || [])[1] || a.name;
        const db = (b.name.match(/(\d{8}_\d{6})/) || [])[1] || b.name;
        switch (sort) {
            case 'date-asc':      return da.localeCompare(db);
            case 'duration-desc': return (b.duration_sec || 0) - (a.duration_sec || 0);
            case 'duration-asc':  return (a.duration_sec || 0) - (b.duration_sec || 0);
            default:              return db.localeCompare(da); // date-desc
        }
    });

    stats.textContent = `${items.length} 组 · 共 ${_historyData.length}`;

    if (items.length === 0) {
        grid.innerHTML = '<div class="analysis-placeholder"><p>没有匹配的训练组</p></div>';
        return;
    }

    grid.innerHTML = items.map(s => {
        const dateMatch = s.name.match(/(\d{8})_(\d{6})/);
        const dateStr = dateMatch ? `${dateMatch[1].slice(0, 4)}-${dateMatch[1].slice(4, 6)}-${dateMatch[1].slice(6, 8)}` : '';
        const timeStr = dateMatch ? `${dateMatch[2].slice(0, 2)}:${dateMatch[2].slice(2, 4)}` : '';
        const chips = [];
        if (s.has_imu)       chips.push(`<span class="hc-chip on">IMU×${(s.imu_nodes || []).length}</span>`);
        if (s.has_vision)    chips.push(`<span class="hc-chip on">视觉</span>`);
        if (s.has_video)     chips.push(`<span class="hc-chip on">视频</span>`);
        if (s.has_landmarks) chips.push(`<span class="hc-chip on">骨架</span>`);
        const thumbSrc = s.has_video ? `/api/sets/${encodeURIComponent(s.name)}/keyframes/0?count=3` : '';

        return `
            <div class="history-card" data-name="${s.name}">
                <div class="hc-thumb-wrap">
                    ${thumbSrc
                        ? `<img class="hc-thumb" src="${thumbSrc}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'hc-thumb-placeholder', textContent:'无缩略图'}))">`
                        : '<div class="hc-thumb-placeholder">无视频</div>'
                    }
                    <div class="hc-score-badge" data-name="${s.name}">--</div>
                </div>
                <div class="hc-info">
                    <div class="hc-title">${s.name}</div>
                    <div class="hc-meta">
                        <span>${dateStr} ${timeStr}</span>
                        <span>${(s.duration_sec || 0).toFixed(1)}s</span>
                    </div>
                    <div class="hc-chips">${chips.join('')}</div>
                </div>
                <div class="hc-actions">
                    <button class="hc-action hc-open">查看</button>
                    <button class="hc-action danger hc-del">删除</button>
                </div>
            </div>
        `;
    }).join('');

    // Click handlers
    $$('.history-card').forEach(card => {
        const name = card.dataset.name;
        card.querySelector('.hc-open').addEventListener('click', (e) => {
            e.stopPropagation();
            _currentSet = name;
            switchTab('analysis');
        });
        card.addEventListener('click', () => {
            _currentSet = name;
            switchTab('analysis');
        });
        card.querySelector('.hc-del').addEventListener('click', async (e) => {
            e.stopPropagation();
            const ok = await confirmModal('删除训练组？', `永久删除 <b>${name}</b>？`, { confirmText: '删除', danger: true });
            if (!ok) return;
            try {
                await fetch(`/api/sets/${encodeURIComponent(name)}`, { method: 'DELETE' });
                toast(`已删除 ${name}`, 'success');
                loadHistory();
            } catch { toast('删除失败', 'error'); }
        });

        // Lazily fetch score for the badge
        fetchAndShowCardScore(name, card.querySelector('.hc-score-badge'));
    });
}

async function fetchAndShowCardScore(name, badge) {
    try {
        const r = await fetch(`/api/sets/${encodeURIComponent(name)}/report`);
        const j = await r.json();
        if (j && j.overall_score !== undefined) {
            const s = j.overall_score;
            badge.textContent = s.toFixed(1);
            badge.classList.add(`zone-${scoreZone(s)}`);
        }
    } catch {}
}

$('#history-search').addEventListener('input', renderHistory);
$('#history-sort').addEventListener('change', renderHistory);

// ═══════════════════════════════════════════════════════
//   SETTINGS VIEW
// ═══════════════════════════════════════════════════════
const FINA_METRICS = [
    { key: 'leg_deviation',            label: '腿部垂直偏差', inverted: false },
    { key: 'knee_extension',           label: '膝盖伸直度',   inverted: true  },
    { key: 'trunk_vertical',           label: '躯干垂直度',   inverted: false },
    { key: 'leg_symmetry',             label: '双腿对称性',   inverted: false },
    { key: 'shoulder_knee_alignment',  label: '肩膝对齐',     inverted: true  },
];

async function loadSettings() {
    try {
        const [cfg, stats] = await Promise.all([
            fetch('/api/config').then(r => r.json()),
            fetch('/api/data/stats').then(r => r.json()),
        ]);
        populateSettings(cfg, stats);
    } catch { toast('设置加载失败', 'error'); }
}

function populateSettings(cfg, stats) {
    const hw = cfg.hardware || {};
    $('#camera-url').value = hw.camera_url || '';

    // rotation buttons — camera rotation isn't persisted in config, use current module state
    $$('.btn-rot').forEach(b => b.classList.toggle('active', parseInt(b.dataset.rot, 10) === currentRotation));

    // devices
    const nodes = hw.imu_nodes || [];
    if (nodes[0]) $('#cfg-node-a1').value = nodes[0];
    if (nodes[1]) $('#cfg-node-a2').value = nodes[1];

    // Data stats
    if (stats) {
        $('#ds-count').textContent = stats.set_count.toString();
        $('#ds-size').textContent  = formatBytes(stats.total_size_bytes || 0);
        $('#ds-path').textContent  = stats.data_dir || 'data/';
    }

    // FINA editor
    const fina = cfg.fina || {};
    renderFinaEditor(fina);
}

function renderFinaEditor(fina) {
    const root = $('#fina-editor');
    if (!root) return;
    root.innerHTML = FINA_METRICS.map(m => {
        const sub = fina[m.key] || {};
        const get = (k, d) => sub[k] !== undefined ? sub[k] : d;
        const defaults = m.inverted
            ? { clean: 170, minor: 155, major: 140 }
            : { clean: 5,   minor: 15,  major: 30 };
        return `
            <div class="fina-row" data-metric="${m.key}">
                <div class="fina-metric-label">${m.label} <span class="fina-metric-hint">${m.inverted ? '(反向：大为优)' : '(正向：小为优)'}</span></div>
                <div class="fina-thresholds">
                    <div class="fina-th-cell">
                        <span class="fina-th-label clean">Clean</span>
                        <input type="number" class="fina-input" data-k="clean" value="${get('clean', defaults.clean)}">
                    </div>
                    <div class="fina-th-cell">
                        <span class="fina-th-label minor">Minor</span>
                        <input type="number" class="fina-input" data-k="minor" value="${get('minor', defaults.minor)}">
                    </div>
                    <div class="fina-th-cell">
                        <span class="fina-th-label major">Major</span>
                        <input type="number" class="fina-input" data-k="major" value="${get('major', defaults.major)}">
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

$('#btn-save-camera').addEventListener('click', async () => {
    const url = $('#camera-url').value.trim();
    try {
        await fetch('/api/camera/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        toast('相机配置已保存', 'success');
    } catch { toast('保存失败', 'error'); }
});

$('#btn-test-camera').addEventListener('click', async () => {
    const url = $('#camera-url').value.trim();
    if (!url) { toast('请先填写 URL', 'warn'); return; }
    toast('正在测试连接…', 'info', 1200);
    try {
        const r = await fetch('/api/camera/test', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const j = await r.json();
        if (j.ok) toast(`连接成功 · 读取 ${j.bytes} 字节 JPEG 流`, 'success');
        else toast(`连接失败: ${j.error || '无 JPEG 响应'}`, 'error');
    } catch { toast('测试失败', 'error'); }
});

$('#btn-save-devices').addEventListener('click', async () => {
    const a1 = $('#cfg-node-a1').value.trim();
    const a2 = $('#cfg-node-a2').value.trim();
    const nodes = [a1, a2].filter(Boolean);
    try {
        await fetch('/api/config', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hardware: { imu_nodes: nodes } }),
        });
        toast('设备信息已保存 · 下次重启生效', 'success');
    } catch { toast('保存失败', 'error'); }
});

$('#btn-save-fina').addEventListener('click', async () => {
    const root = $('#fina-editor');
    const update = {};
    $$('.fina-row', root).forEach(row => {
        const key = row.dataset.metric;
        const sub = {};
        $$('.fina-input', row).forEach(inp => {
            sub[inp.dataset.k] = parseFloat(inp.value);
        });
        update[key] = sub;
    });
    try {
        await fetch('/api/config', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fina: update }),
        });
        toast('FINA 阈值已保存', 'success');
    } catch { toast('保存失败', 'error'); }
});

$$('.btn-rot').forEach(btn => {
    btn.addEventListener('click', async () => {
        $$('.btn-rot').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentRotation = parseInt(btn.dataset.rot, 10);
        await fetch('/api/camera/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rotation: currentRotation })
        });
    });
});

// ═══════════════════════════════════════════════════════
//   INIT
// ═══════════════════════════════════════════════════════

// ─── Upper-body-only mode (artistic swimming from deck camera) ────
function getBodyMode() { return localStorage.getItem('bodyMode') || 'full'; }
function applyBodyMode() {
    const mode = getBodyMode();
    document.querySelector('main')?.classList.toggle('upper-body', mode === 'upper');
    const chk = $('#cfg-upper-body');
    if (chk) chk.checked = mode === 'upper';
}
document.addEventListener('DOMContentLoaded', () => {
    applyBodyMode();
    const chk = $('#cfg-upper-body');
    if (chk) {
        chk.addEventListener('change', () => {
            localStorage.setItem('bodyMode', chk.checked ? 'upper' : 'full');
            applyBodyMode();
            toast(chk.checked ? '仅上半身模式已启用' : '恢复全身模式', 'info', 1500);
        });
    }
});
// Apply immediately (script runs at bottom so DOM is likely ready)
applyBodyMode();
(function wireBodyModeNow() {
    const chk = document.getElementById('cfg-upper-body');
    if (chk && !chk.dataset.wired) {
        chk.dataset.wired = '1';
        chk.addEventListener('change', () => {
            localStorage.setItem('bodyMode', chk.checked ? 'upper' : 'full');
            applyBodyMode();
            toast(chk.checked ? '仅上半身模式已启用' : '恢复全身模式', 'info', 1500);
        });
    }
})();

// Preload camera rotation from server config so the buttons + state match.
async function preloadCameraState() {
    try {
        const cfg = await fetch('/api/config').then(r => r.json());
        const hw = cfg.hardware || {};
        if (hw.camera_rotation !== undefined) {
            currentRotation = parseInt(hw.camera_rotation, 10) || 0;
            $$('.btn-rot').forEach(b =>
                b.classList.toggle('active', parseInt(b.dataset.rot, 10) === currentRotation));
        }
    } catch { /* ignore — defaults are fine */ }
}

preloadCameraState();
connectVideoWs();
connectMetricsWs();

window.addEventListener('resize', () => {
    if ($('#view-analysis').classList.contains('active')) {
        drawTimeseries();
        const rc = $('#radar-canvas');
        if (rc) {
            // No direct re-render; easier to leave radar static on resize
        }
    }
}, { passive: true });
