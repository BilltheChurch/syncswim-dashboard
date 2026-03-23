---
phase: 2
slug: single-set-analysis
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 (existing from Phase 1) |
| **Config file** | tests/ directory (existing) |
| **Quick run command** | `source .venv/bin/activate && python -m pytest tests/ -x -q` |
| **Full suite command** | `source .venv/bin/activate && python -m pytest tests/ -v` |
| **Estimated runtime** | ~8 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 8 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | ANAL-01,ANAL-02 | unit | `python -m pytest tests/test_scoring.py -x -q` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | ANAL-03,ANAL-04 | unit | `python -m pytest tests/test_phase_detection.py -x -q` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | VIZ-01,VIZ-02,VIZ-04 | unit | `python -m pytest tests/test_chart_builders.py -x -q` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | VIZ-03 | unit | `python -m pytest tests/test_skeleton.py -x -q` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | ANAL-05 | integration | `python -c "from dashboard.core.skeleton import ..."` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | ANAL-06 | manual | `streamlit run dashboard/app.py` | N/A | ⬜ pending |
| 02-03-02 | 03 | 3 | VIZ-01,VIZ-02,VIZ-04 | manual | visual chart check | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_scoring.py` — stubs for scoring engine (5 metrics, FINA deductions)
- [ ] `tests/test_phase_detection.py` — stubs for IMU phase detection (find_peaks, fallback)
- [ ] `tests/test_chart_builders.py` — stubs for gauge, waveform, fusion chart builders
- [ ] `tests/test_skeleton.py` — stubs for MediaPipe re-run and overlay rendering

*Existing test infrastructure (conftest.py, pytest) from Phase 1 covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Report auto-generates within 3 seconds of set selection | ANAL-06 | Timing + visual verification | Select set, measure time to full report render |
| Gauge charts show FINA zone coloring (green/yellow/red) | VIZ-01 | Visual rendering check | Verify gauge color bands match FINA thresholds |
| IMU waveform scrolls correctly | VIZ-02 | Visual rendering check | Verify accel/gyro curves display with correct axes |
| Fusion chart shows dual axes with correlation | VIZ-04 | Visual rendering check | Verify both sensor angles on same timeline |
| Phase timeline shows colored bars | ANAL-03 | Visual rendering check | Verify horizontal bars with FINA zone colors |
| Keyframe comparison shows wireframe overlay | ANAL-05 | Visual rendering check | Verify green=standard, red=actual on same frame |
| Tab navigation works (Overview/Visual/Sensor) | ANAL-06 | UI interaction check | Click each tab, verify content switches |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 8s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
