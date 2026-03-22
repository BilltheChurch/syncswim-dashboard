---
phase: 1
slug: foundation-environment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | INFRA-05 | integration | `python -c "import streamlit; import plotly; import numpy; import scipy; import mediapipe"` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | INFRA-03 | unit | `python -m pytest tests/test_data_loader.py -x -q` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | INFRA-06 | unit | `python -m pytest tests/test_config.py -x -q` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 2 | INFRA-01 | manual | `streamlit run dashboard/app.py` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 2 | INFRA-02 | manual | visual toggle check | N/A | ⬜ pending |
| 01-03-03 | 03 | 2 | INFRA-04 | manual | select session from dropdown | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/` directory created
- [ ] `tests/conftest.py` — shared fixtures (test data paths, sample CSV)
- [ ] `tests/test_data_loader.py` — stubs for INFRA-03 (CSV loading, sessions.json index)
- [ ] `tests/test_config.py` — stubs for INFRA-06 (TOML read/write)
- [ ] `pytest` installed in requirements.txt

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Streamlit sidebar navigation shows 5 views in 3 pages | INFRA-01 | Visual UI check | Run `streamlit run dashboard/app.py`, verify sidebar has Training/Analysis/Team pages |
| Coach/athlete toggle switches perspective label | INFRA-02 | Visual UI check | Toggle sidebar radio, verify header text changes |
| Session dropdown loads CSV metadata | INFRA-04 | Visual + data check | Select a set from dropdown, verify metadata (set count, duration, timestamps) displays |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
