/* ═══════════════════════════════════════════════════════
   SyncSwim Coach Station — app.js
   Framework: Vanilla JS (no dependencies)
═══════════════════════════════════════════════════════ */

'use strict';

// ─── Constants ────────────────────────────────────────────
const CONNECTIONS = [
    [11,12],[11,13],[13,15],[12,14],[14,16],
    [11,23],[12,24],[23,24],[23,25],[24,26],
    [25,27],[26,28]
];

const THRESHOLDS = {
    leg_deviation:   { clean: 5,   minor: 15,  inverted: false },
    knee_extension:  { clean: 170, minor: 155, inverted: true  },
    trunk_vertical:  { clean: 10,  minor: 20,  inverted: false },
    elbow:           { clean: 15,  minor: 30,  inverted: false },
};

// Live metric bar normalization ranges (for the mini-bar fill %)
const LIVE_BAR_RANGES = {
    leg_deviation:  { min: 0, max: 30  },
    knee_extension: { min: 140, max: 180 },
    trunk_vertical: { min: 0, max: 35  },
    elbow:          { min: 0, max: 60  },
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
};

const ZONE_LABELS = { clean: '达标', minor: '轻微', major: '需改进' };

const PHASE_NAMES = { prep: '准备', exhibition: '展示', recovery: '恢复' };

// Radar normalization — returns 0-100 score (higher = better)
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

// ─── Zone helper ──────────────────────────────────────────
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

// ─── Tab Navigation ───────────────────────────────────────
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('view-' + btn.dataset.view).classList.add('active');
        if (btn.dataset.view === 'analysis') loadSetList();
    });
});

// ═══════════════════════════════════════════════════════
//   WEBSOCKET: VIDEO
// ═══════════════════════════════════════════════════════
const canvas = document.getElementById('video-canvas');
const ctx = canvas.getContext('2d');

let videoWs = null;

function connectVideoWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    videoWs = new WebSocket(`${protocol}//${location.host}/ws/video`);

    videoWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const img = new Image();
        img.onload = () => {
            canvas.width  = img.width;
            canvas.height = img.height;
            ctx.drawImage(img, 0, 0);
            if (data.landmarks && data.landmarks.length === 33) {
                drawSkeleton(data.landmarks, data.angles);
            }
        };
        img.src = data.frame;
        if (data.angles) {
            updateLiveMetrics(data.angles);
        } else {
            clearLiveMetrics();
        }
    };

    videoWs.onclose = () => setTimeout(connectVideoWs, 2000);
    videoWs.onerror = () => videoWs.close();
}

function drawSkeleton(landmarks, angles) {
    const w = canvas.width;
    const h = canvas.height;

    // Connections
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.85)';
    ctx.lineWidth = 2;
    CONNECTIONS.forEach(([i, j]) => {
        if (landmarks[i][2] > 0.3 && landmarks[j][2] > 0.3) {
            ctx.beginPath();
            ctx.moveTo(landmarks[i][0] * w, landmarks[i][1] * h);
            ctx.lineTo(landmarks[j][0] * w, landmarks[j][1] * h);
            ctx.stroke();
        }
    });

    // Joints
    landmarks.forEach((lm) => {
        if (lm[2] > 0.3) {
            ctx.fillStyle = '#3B82F6';
            ctx.beginPath();
            ctx.arc(lm[0] * w, lm[1] * h, 4, 0, Math.PI * 2);
            ctx.fill();
            // white center dot
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(lm[0] * w, lm[1] * h, 1.5, 0, Math.PI * 2);
            ctx.fill();
        }
    });

    // Angle labels at key joints
    if (angles) {
        const angleJoints = [
            { name: 'elbow',          joint: 14, label: '肘' },
            { name: 'knee_extension', joint: 26, label: '膝' },
        ];
        angleJoints.forEach(({ name, joint, label }) => {
            if (angles[name] !== undefined && landmarks[joint][2] > 0.3) {
                const x = landmarks[joint][0] * w + 14;
                const y = landmarks[joint][1] * h - 8;
                const zone = getZone(name, angles[name]);
                const color = zone === 'clean' ? '#4ade80' : zone === 'minor' ? '#fbbf24' : '#f87171';

                // Background pill
                const text = `${label} ${angles[name].toFixed(0)}°`;
                ctx.font = 'bold 12px "Fira Code", monospace';
                const tw = ctx.measureText(text).width;
                ctx.fillStyle = 'rgba(0,0,0,0.65)';
                ctx.beginPath();
                ctx.roundRect(x - 4, y - 13, tw + 8, 18, 3);
                ctx.fill();

                ctx.fillStyle = color;
                ctx.fillText(text, x, y);
            }
        });
    }
}

function updateLiveMetrics(angles) {
    const metrics = ['leg_deviation', 'knee_extension', 'trunk_vertical', 'elbow'];
    metrics.forEach(name => {
        const row  = document.getElementById(`metric-${name}`);
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

        // Bar fill
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
    const metrics = ['leg_deviation', 'knee_extension', 'trunk_vertical', 'elbow'];
    metrics.forEach(name => {
        const row = document.getElementById(`metric-${name}`);
        if (!row) return;
        const valEl = row.querySelector('.lm-value');
        const fill  = row.querySelector('.lm-bar-fill');
        if (valEl) valEl.textContent = '--';
        row.className = 'live-metric-row';
        if (fill) fill.style.width = '0%';
    });
}

// ═══════════════════════════════════════════════════════
//   WEBSOCKET: METRICS
// ═══════════════════════════════════════════════════════
let metricsWs   = null;
let wasRecording = false;

function connectMetricsWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    metricsWs = new WebSocket(`${protocol}//${location.host}/ws/metrics`);

    metricsWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateBleStatus(data.nodes);
        updateRecStatus(data);

        // Auto-switch to analysis when recording stops
        if (wasRecording && !data.recording) {
            document.querySelector('[data-view="analysis"]').click();
        }
        wasRecording = data.recording;
    };

    metricsWs.onclose = () => setTimeout(connectMetricsWs, 2000);
    metricsWs.onerror = () => metricsWs.close();
}

function updateBleStatus(nodes) {
    let anyConnected = false;

    Object.entries(nodes).forEach(([name, info]) => {
        const row  = document.getElementById(`node-${name}`);
        const rate = document.getElementById(`rate-${name}`);
        const tilt = document.getElementById(`tilt-${name}`);
        if (!row) return;

        if (info.connected) {
            anyConnected = true;
            row.classList.add('connected');
            if (rate) rate.textContent = info.rate.toFixed(0) + ' Hz';
            if (tilt && info.tilt !== undefined) tilt.textContent = info.tilt.toFixed(1) + '°';
        } else {
            row.classList.remove('connected');
            if (rate) rate.textContent = '-- Hz';
            if (tilt) tilt.textContent = '--°';
        }
    });

    const badge = document.getElementById('ble-badge');
    if (badge) {
        if (anyConnected) {
            badge.textContent = '在线';
            badge.classList.add('online');
        } else {
            badge.textContent = '离线';
            badge.classList.remove('online');
        }
    }
}

function updateRecStatus(data) {
    // Overlay elements
    const recDot   = document.getElementById('rec-dot');
    const recLabel = document.getElementById('rec-label');
    const recTime  = document.getElementById('rec-time');
    const setOverlay = document.getElementById('set-overlay');

    // Side panel elements
    const rsDot    = document.getElementById('rs-dot');
    const rsStatus = document.getElementById('rs-status');
    const rsTime   = document.getElementById('rs-time');
    const rsSet    = document.getElementById('rs-set');

    if (data.recording) {
        const mins = Math.floor(data.elapsed / 60);
        const secs = Math.floor(data.elapsed % 60);
        const timeStr = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;

        // Overlay
        if (recDot)   { recDot.className = 'rec-dot recording'; }
        if (recLabel) { recLabel.textContent = 'REC'; recLabel.className = 'rec-label recording'; }
        if (recTime)  { recTime.textContent = timeStr; }
        if (setOverlay) { setOverlay.textContent = `Set #${data.set_number}`; }

        // Side panel
        if (rsDot)    { rsDot.className = 'rs-dot recording'; }
        if (rsStatus) { rsStatus.textContent = '录制中'; rsStatus.className = 'rs-status recording'; }
        if (rsTime)   { rsTime.textContent = timeStr; }
        if (rsSet)    { rsSet.textContent = `#${data.set_number}`; }

        document.getElementById('btn-start').disabled = true;
        document.getElementById('btn-stop').disabled  = false;

    } else {
        // Overlay
        if (recDot)   { recDot.className = 'rec-dot'; }
        if (recLabel) { recLabel.textContent = 'IDLE'; recLabel.className = 'rec-label'; }
        if (recTime)  { recTime.textContent = ''; }
        if (setOverlay) { setOverlay.textContent = ''; }

        // Side panel
        if (rsDot)    { rsDot.className = 'rs-dot'; }
        if (rsStatus) { rsStatus.textContent = '待机'; rsStatus.className = 'rs-status'; }
        if (rsTime)   { rsTime.textContent = '--:--'; }
        if (rsSet)    { rsSet.textContent = '--'; }

        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-stop').disabled  = true;
    }
}

// ─── Recording Controls ───────────────────────────────────
document.getElementById('btn-start').addEventListener('click', async () => {
    await fetch('/api/recording/start', { method: 'POST' });
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    await fetch('/api/recording/stop', { method: 'POST' });
});

let currentRotation = 0;
document.getElementById('btn-rotate').addEventListener('click', async () => {
    currentRotation = (currentRotation + 90) % 360;
    await fetch('/api/camera/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rotation: currentRotation })
    });
});

// ═══════════════════════════════════════════════════════
//   ANALYSIS VIEW
// ═══════════════════════════════════════════════════════

async function loadSetList() {
    const res  = await fetch('/api/sets');
    const sets = await res.json();
    const sel  = document.getElementById('set-selector');
    sel.innerHTML = '';

    if (!sets || sets.length === 0) {
        sel.innerHTML = '<option value="">暂无数据</option>';
        return;
    }

    sets.sort((a, b) => b.name.localeCompare(a.name));
    sets.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.name;
        opt.textContent = `${s.name}  (${s.duration_sec}s)`;
        sel.appendChild(opt);
    });

    loadReport(sets[0].name);
}

document.getElementById('set-selector').addEventListener('change', (e) => {
    if (e.target.value) loadReport(e.target.value);
});

// ── Radar Chart (Canvas 2D) ───────────────────────────────
function drawRadar(canvas, metrics) {
    const dpr = window.devicePixelRatio || 1;
    const size = Math.min(canvas.parentElement.clientWidth - 36, 320);
    canvas.style.width  = size + 'px';
    canvas.style.height = size + 'px';
    canvas.width  = size * dpr;
    canvas.height = size * dpr;
    const c = canvas.getContext('2d');
    c.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const r  = size * 0.36;
    const n  = metrics.length;

    const labels = metrics.map(m => METRIC_LABELS[m.name] || m.name);
    const values = metrics.map(m => normalizeForRadar(m.name, m.value));

    // Grid rings at 25%, 50%, 75%, 100%
    const rings = [0.25, 0.5, 0.75, 1.0];
    rings.forEach((frac, ri) => {
        c.beginPath();
        for (let i = 0; i < n; i++) {
            const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
            const x = cx + Math.cos(angle) * r * frac;
            const y = cy + Math.sin(angle) * r * frac;
            if (i === 0) c.moveTo(x, y);
            else c.lineTo(x, y);
        }
        c.closePath();
        c.strokeStyle = ri === rings.length - 1 ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.06)';
        c.lineWidth = ri === rings.length - 1 ? 1.5 : 1;
        c.stroke();

        // Ring percentage label
        if (ri < rings.length - 1) {
            const pctAngle = -Math.PI / 2;
            const lx = cx + Math.cos(pctAngle) * r * frac + 4;
            const ly = cy + Math.sin(pctAngle) * r * frac - 3;
            c.fillStyle = 'rgba(100,120,160,0.7)';
            c.font = `${Math.round(size * 0.028)}px "Fira Code", monospace`;
            c.fillText(`${frac * 100}`, lx, ly);
        }
    });

    // Axis spokes
    c.strokeStyle = 'rgba(255,255,255,0.08)';
    c.lineWidth = 1;
    for (let i = 0; i < n; i++) {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        c.beginPath();
        c.moveTo(cx, cy);
        c.lineTo(cx + Math.cos(angle) * r, cy + Math.sin(angle) * r);
        c.stroke();
    }

    // Filled polygon
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

    // Data point dots
    pts.forEach(([x, y]) => {
        c.beginPath();
        c.arc(x, y, 4, 0, Math.PI * 2);
        c.fillStyle = '#3B82F6';
        c.fill();
        c.beginPath();
        c.arc(x, y, 2, 0, Math.PI * 2);
        c.fillStyle = '#fff';
        c.fill();
    });

    // Axis labels
    const labelR = r + size * 0.10;
    const labelFont = `${Math.round(size * 0.032)}px "Fira Sans", sans-serif`;
    c.font = labelFont;
    c.fillStyle = 'rgba(200,210,230,0.85)';
    c.textAlign = 'center';
    c.textBaseline = 'middle';

    labels.forEach((label, i) => {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const lx = cx + Math.cos(angle) * labelR;
        const ly = cy + Math.sin(angle) * labelR;

        // Break long labels
        const words = label.match(/.{1,4}/gu) || [label];
        const lineH = size * 0.036;
        words.forEach((word, wi) => {
            c.fillText(word, lx, ly + (wi - (words.length - 1) / 2) * lineH);
        });
    });
}

// ── Phase Timeline ────────────────────────────────────────
function buildPhaseTimeline(phases) {
    if (!phases || phases.length === 0) return '';

    const total = phases.reduce((sum, p) => sum + (p.end - p.start), 0) || 1;

    const segments = phases.map(p => {
        const pct   = ((p.end - p.start) / total * 100).toFixed(1);
        const cls   = p.phase || 'prep';
        const label = PHASE_NAMES[cls] || cls;
        return `<div class="phase-segment ${cls}" style="width:${pct}%" title="${label}: ${p.start.toFixed(1)}s — ${p.end.toFixed(1)}s">
                    ${pct > 15 ? label : ''}
                </div>`;
    }).join('');

    const legendItems = [...new Set(phases.map(p => p.phase || 'prep'))].map(ph =>
        `<div class="phase-legend-item">
            <div class="phase-legend-dot ${ph}"></div>
            <span>${PHASE_NAMES[ph] || ph}</span>
        </div>`
    ).join('');

    return `
        <div class="phase-timeline-section">
            <div class="phase-timeline-label">阶段时间轴</div>
            <div class="phase-timeline-track">${segments}</div>
            <div class="phase-legend">${legendItems}</div>
        </div>
    `;
}

// ── Keyframe cards ────────────────────────────────────────
function buildKeyframeCards(setName, phases) {
    const phaseKeys = ['prep', 'exhibition', 'recovery'];
    const phaseMap  = {};
    if (phases) phases.forEach(p => { phaseMap[p.phase] = p; });

    return phaseKeys.map((ph, idx) => {
        const imgSrc  = `/api/sets/${encodeURIComponent(setName)}/keyframes/${idx}`;
        const phLabel = PHASE_NAMES[ph] || ph;
        return `
            <div class="keyframe-card">
                <div class="kf-image-wrap">
                    <img src="${imgSrc}"
                         alt="${phLabel}"
                         onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
                    >
                    <div class="kf-placeholder" style="display:none">
                        <div class="kf-placeholder-inner"></div>
                    </div>
                </div>
                <div class="kf-label">
                    <span class="kf-phase-name">${phLabel}</span>
                    <span class="kf-index">F${idx + 1}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ── Metric Cards ──────────────────────────────────────────
function buildMetricCards(metrics) {
    const metricOrder = [
        'leg_deviation','knee_extension','shoulder_knee_alignment','trunk_vertical',
        'leg_symmetry','smoothness','stability','leg_height_index'
    ];

    const metricMap = {};
    metrics.forEach(m => { metricMap[m.name] = m; });

    return metricOrder.map(name => {
        const m = metricMap[name];
        if (!m) return '';

        const label   = METRIC_LABELS[name] || name;
        const unit    = m.unit === 'deg' ? '°' : (m.unit || '');
        const zone    = m.zone || 'clean';
        const zoneTxt = ZONE_LABELS[zone];
        const radar   = normalizeForRadar(name, m.value);
        const barPct  = radar.toFixed(0);

        return `
            <div class="metric-card">
                <div class="mc-name">${label}</div>
                <div class="mc-value-row">
                    <span class="mc-value">${typeof m.value === 'number' ? m.value.toFixed(1) : m.value}</span>
                    <span class="mc-unit">${unit}</span>
                </div>
                <div class="mc-zone zone-${zone}">${zoneTxt}</div>
                <div class="mc-bar-track">
                    <div class="mc-bar-fill zone-${zone}" style="width:${barPct}%"></div>
                </div>
            </div>
        `;
    }).join('');
}

// ── IMU Sensor Summary ────────────────────────────────────
function buildSensorSection(report) {
    const imuData = report.imu_summary || {};
    const corrVal = report.correlation !== undefined
        ? report.correlation.toFixed(3)
        : '--';

    const nodeBlocks = Object.entries(imuData).map(([node, info]) => `
        <div class="imu-node-block">
            <div class="imu-node-header">
                <span class="imu-node-label">${node}</span>
            </div>
            <div class="imu-node-body">
                <div class="imu-stat">
                    <span class="imu-stat-label">数据包</span>
                    <span class="imu-stat-value">${info.packets ?? '--'}</span>
                </div>
                <div class="imu-stat">
                    <span class="imu-stat-label">频率</span>
                    <span class="imu-stat-value">${info.rate !== undefined ? info.rate.toFixed(1) + ' Hz' : '--'}</span>
                </div>
                <div class="imu-stat">
                    <span class="imu-stat-label">时长</span>
                    <span class="imu-stat-value">${info.duration !== undefined ? info.duration.toFixed(1) + ' s' : '--'}</span>
                </div>
                <div class="imu-stat">
                    <span class="imu-stat-label">倾斜</span>
                    <span class="imu-stat-value">${info.tilt !== undefined ? info.tilt.toFixed(1) + '°' : '--'}</span>
                </div>
            </div>
        </div>
    `).join('');

    // Fallback if no IMU summary
    if (!nodeBlocks) return '';

    return `
        <div class="sensor-card">
            <div class="sensor-title">传感器数据</div>
            ${nodeBlocks}
            <div class="correlation-row">
                <span class="corr-label">IMU / 视觉 相关系数</span>
                <span class="corr-value">${corrVal}</span>
            </div>
            ${buildPhaseTimeline(report.phases)}
        </div>
    `;
}

// ── Main render ───────────────────────────────────────────
async function loadReport(name) {
    const content = document.getElementById('analysis-content');
    content.innerHTML = `
        <div class="analysis-placeholder">
            <div class="placeholder-mark"></div>
            <p>分析中...</p>
        </div>`;

    // Hide inline score while loading
    const scoreInline = document.getElementById('score-inline');
    if (scoreInline) scoreInline.style.display = 'none';

    let report;
    try {
        const res = await fetch(`/api/sets/${encodeURIComponent(name)}/report`);
        report = await res.json();
    } catch (e) {
        content.innerHTML = `<div class="analysis-placeholder"><p>加载失败</p></div>`;
        return;
    }

    if (report.error) {
        content.innerHTML = `<div class="analysis-placeholder"><p>${report.error}</p></div>`;
        return;
    }

    const score     = report.overall_score ?? 0;
    const scoreColor = score >= 8 ? '#4ade80' : score >= 6 ? '#fbbf24' : '#f87171';
    const scorePct  = (score / 10 * 100).toFixed(0);

    // Inline score in topbar
    if (scoreInline) {
        const siScore = document.getElementById('si-score');
        if (siScore) {
            siScore.textContent = score.toFixed(1);
            siScore.style.color = scoreColor;
        }
        scoreInline.style.display = 'flex';
    }

    // Metric cards HTML
    const metricsHtml = report.metrics && report.metrics.length
        ? buildMetricCards(report.metrics)
        : '<p style="color:var(--text-muted);font-size:0.85rem">暂无指标数据</p>';

    // Keyframes
    const keyframesHtml = buildKeyframeCards(name, report.phases);

    // Sensor section
    const sensorHtml = buildSensorSection(report);

    content.innerHTML = `
        <!-- Score Row -->
        <div class="score-row">
            <div class="score-num-block">
                <span class="score-num" style="color:${scoreColor}">${score.toFixed(1)}</span>
                <span class="score-denom">&thinsp;/&thinsp;10</span>
            </div>
            <div class="score-bar-col">
                <span class="score-bar-label">综合评分</span>
                <div class="score-bar-track">
                    <div class="score-bar-fill" style="width:${scorePct}%; background:${scoreColor}"></div>
                </div>
            </div>
        </div>

        <!-- Keyframes -->
        <div class="metrics-section-title">动作帧</div>
        <div class="keyframes-row">${keyframesHtml}</div>

        <!-- Metric Cards -->
        <div class="metrics-section-title">生物力学指标</div>
        <div class="metrics-grid">${metricsHtml}</div>

        <!-- Bottom row: Radar + Sensor -->
        <div class="analysis-bottom">
            <div class="radar-card">
                <div class="radar-title">雷达图 — 综合表现</div>
                <canvas id="radar-canvas"></canvas>
            </div>
            ${sensorHtml}
        </div>
    `;

    // Draw radar after DOM insertion
    const radarCanvas = document.getElementById('radar-canvas');
    if (radarCanvas && report.metrics && report.metrics.length) {
        // Use only the 8 defined radar metrics
        const radarMetrics = report.metrics.filter(m => normalizeForRadar(m.name, m.value) !== 50 || true);
        requestAnimationFrame(() => drawRadar(radarCanvas, radarMetrics));
    }
}

// ═══════════════════════════════════════════════════════
//   SETTINGS VIEW
// ═══════════════════════════════════════════════════════
document.getElementById('btn-save-camera').addEventListener('click', async () => {
    const url = document.getElementById('camera-url').value.trim();
    const feedback = document.getElementById('save-feedback');

    try {
        await fetch('/api/camera/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        if (feedback) {
            feedback.textContent = '配置已保存';
            feedback.style.opacity = '1';
            setTimeout(() => { feedback.style.opacity = '0'; }, 3000);
        }
    } catch {
        if (feedback) {
            feedback.textContent = '保存失败';
            feedback.style.color = 'var(--major-text)';
        }
    }
});

document.querySelectorAll('.btn-rot').forEach(btn => {
    btn.addEventListener('click', async () => {
        document.querySelectorAll('.btn-rot').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentRotation = parseInt(btn.dataset.rot, 10);
        await fetch('/api/camera/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rotation: currentRotation })
        });
    });
});

// ─── Init ──────────────────────────────────────────────────
connectVideoWs();
connectMetricsWs();
