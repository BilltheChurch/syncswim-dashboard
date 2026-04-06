// ─── Tab Navigation ─────────────────────────────────────
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('view-' + btn.dataset.view).classList.add('active');
        if (btn.dataset.view === 'analysis') loadSetList();
    });
});

// ─── WebSocket: Video ───────────────────────────────────
const canvas = document.getElementById('video-canvas');
const ctx = canvas.getContext('2d');

const CONNECTIONS = [
    [11,12],[11,13],[13,15],[12,14],[14,16],
    [11,23],[12,24],[23,24],[23,25],[24,26],
    [25,27],[26,28]
];

// FINA thresholds for color coding
const THRESHOLDS = {
    leg_deviation: { clean: 5, minor: 15 },
    knee_extension: { clean: 170, minor: 155, inverted: true },
    trunk_vertical: { clean: 10, minor: 20 },
    elbow: { clean: 15, minor: 30 },
};

function getZone(name, value) {
    const t = THRESHOLDS[name];
    if (!t) return 'clean';
    if (t.inverted) {
        if (value >= t.clean) return 'clean';
        if (value >= t.minor) return 'minor';
        return 'major';
    }
    if (value < t.clean) return 'clean';
    if (value < t.minor) return 'minor';
    return 'major';
}

let videoWs = null;
function connectVideoWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    videoWs = new WebSocket(`${protocol}//${location.host}/ws/video`);
    videoWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const img = new Image();
        img.onload = () => {
            canvas.width = img.width;
            canvas.height = img.height;
            ctx.drawImage(img, 0, 0);
            if (data.landmarks && data.landmarks.length === 33) {
                drawSkeleton(data.landmarks, data.angles);
            }
        };
        img.src = data.frame;
        // Update live metrics
        if (data.angles) updateLiveMetrics(data.angles);
    };
    videoWs.onclose = () => setTimeout(connectVideoWs, 2000);
    videoWs.onerror = () => videoWs.close();
}

function drawSkeleton(landmarks, angles) {
    const w = canvas.width;
    const h = canvas.height;

    // Draw connections
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 2;
    CONNECTIONS.forEach(([i, j]) => {
        if (landmarks[i][2] > 0.3 && landmarks[j][2] > 0.3) {
            ctx.beginPath();
            ctx.moveTo(landmarks[i][0] * w, landmarks[i][1] * h);
            ctx.lineTo(landmarks[j][0] * w, landmarks[j][1] * h);
            ctx.stroke();
        }
    });

    // Draw joints
    landmarks.forEach((lm, idx) => {
        if (lm[2] > 0.3) {
            ctx.fillStyle = '#4ade80';
            ctx.beginPath();
            ctx.arc(lm[0] * w, lm[1] * h, 4, 0, Math.PI * 2);
            ctx.fill();
        }
    });

    // Draw angle labels at key joints
    if (angles) {
        const angleJoints = [
            { name: 'elbow', joint: 14, label: '肘' },
            { name: 'knee_extension', joint: 26, label: '膝' },
        ];
        angleJoints.forEach(({ name, joint, label }) => {
            if (angles[name] !== undefined && landmarks[joint][2] > 0.3) {
                const x = landmarks[joint][0] * w + 15;
                const y = landmarks[joint][1] * h - 10;
                const zone = getZone(name, angles[name]);
                ctx.font = 'bold 14px sans-serif';
                ctx.fillStyle = zone === 'clean' ? '#4ade80' : zone === 'minor' ? '#fbbf24' : '#f87171';
                ctx.fillText(`${label} ${angles[name].toFixed(0)}°`, x, y);
            }
        });
    }
}

function updateLiveMetrics(angles) {
    const metrics = ['leg_deviation', 'knee_extension', 'trunk_vertical', 'elbow'];
    metrics.forEach(name => {
        const el = document.querySelector(`#metric-${name} .metric-value`);
        if (el && angles[name] !== undefined) {
            const val = angles[name].toFixed(1);
            el.textContent = val + '°';
            el.className = 'metric-value ' + getZone(name, angles[name]);
        }
    });
}

// ─── WebSocket: Metrics ─────────────────────────────────
let metricsWs = null;
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
    Object.entries(nodes).forEach(([name, info]) => {
        const el = document.getElementById('node-' + name);
        if (!el) return;
        const dot = el.querySelector('.dot');
        const rate = el.querySelector('.node-rate');
        dot.className = 'dot' + (info.connected ? ' connected' : '');
        rate.textContent = info.connected ? info.rate.toFixed(0) + 'Hz' : '--';
    });
}

function updateRecStatus(data) {
    const indicator = document.querySelector('.rec-indicator');
    const timeEl = document.querySelector('.rec-time');
    const setEl = document.querySelector('.rec-set');

    if (data.recording) {
        indicator.textContent = 'REC';
        indicator.className = 'rec-indicator recording';
        const mins = Math.floor(data.elapsed / 60);
        const secs = Math.floor(data.elapsed % 60);
        timeEl.textContent = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
        setEl.textContent = `Set #${data.set_number}`;
        document.getElementById('btn-start').disabled = true;
        document.getElementById('btn-stop').disabled = false;
    } else {
        indicator.textContent = 'IDLE';
        indicator.className = 'rec-indicator';
        timeEl.textContent = '';
        setEl.textContent = '';
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-stop').disabled = true;
    }
}

// ─── Recording Controls ─────────────────────────────────
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

// ─── Analysis View ──────────────────────────────────────
const METRIC_LABELS = {
    leg_deviation: '腿部垂直偏差',
    leg_height_index: '腿部高度指数',
    knee_extension: '膝盖伸直度',
    shoulder_knee_alignment: '肩膝对齐',
    trunk_vertical: '躯干垂直度',
    leg_symmetry: '双腿对称性',
    smoothness: '动作平滑度',
    stability: '姿势稳定性',
};

const ZONE_LABELS = { clean: '达标', minor: '轻微', major: '需改进' };
const ZONE_ICONS = { clean: '✅', minor: '⚠️', major: '❌' };

async function loadSetList() {
    const res = await fetch('/api/sets');
    const sets = await res.json();
    const sel = document.getElementById('set-selector');
    sel.innerHTML = '';
    if (sets.length === 0) {
        sel.innerHTML = '<option value="">暂无数据</option>';
        return;
    }
    // Sort by name descending (latest first)
    sets.sort((a, b) => b.name.localeCompare(a.name));
    sets.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.name;
        opt.textContent = `${s.name} (${s.duration_sec}s)`;
        sel.appendChild(opt);
    });
    // Auto-load latest
    loadReport(sets[0].name);
}

document.getElementById('set-selector').addEventListener('change', (e) => {
    if (e.target.value) loadReport(e.target.value);
});

async function loadReport(name) {
    const content = document.getElementById('analysis-content');
    content.innerHTML = '<p class="placeholder">分析中...</p>';

    const res = await fetch(`/api/sets/${name}/report`);
    const report = await res.json();

    if (report.error) {
        content.innerHTML = `<p class="placeholder">${report.error}</p>`;
        return;
    }

    const scoreColor = report.overall_score >= 8 ? '#4ade80' : report.overall_score >= 6 ? '#fbbf24' : '#f87171';
    const scorePercent = (report.overall_score / 10 * 100).toFixed(0);

    let metricsHtml = report.metrics.map(m => `
        <div class="metric-item">
            <span class="name">${METRIC_LABELS[m.name] || m.name}</span>
            <span class="value">${m.value}${m.unit === 'deg' ? '°' : ''}</span>
            <span class="zone zone-${m.zone}">${ZONE_ICONS[m.zone]} ${ZONE_LABELS[m.zone]}</span>
        </div>
    `).join('');

    content.innerHTML = `
        <div class="score-bar">
            <span class="score-value" style="color:${scoreColor}">${report.overall_score}</span>
            <span class="score-label"> / 10</span>
            <div class="score-bar-visual">
                <div class="score-bar-fill" style="width:${scorePercent}%;background:${scoreColor}"></div>
            </div>
        </div>
        <div class="metric-list">${metricsHtml}</div>
    `;
}

// ─── Settings ───────────────────────────────────────────
document.getElementById('btn-save-camera').addEventListener('click', async () => {
    const url = document.getElementById('camera-url').value;
    await fetch('/api/camera/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    });
    alert('保存成功');
});

document.querySelectorAll('.btn-rot').forEach(btn => {
    btn.addEventListener('click', async () => {
        const rot = parseInt(btn.dataset.rot);
        await fetch('/api/camera/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rotation: rot })
        });
        currentRotation = rot;
    });
});

// ─── Init ───────────────────────────────────────────────
connectVideoWs();
connectMetricsWs();
