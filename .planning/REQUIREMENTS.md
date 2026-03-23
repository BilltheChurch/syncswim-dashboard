# Requirements: SyncSwim Dashboard

**Defined:** 2026-03-22
**Core Value:** 让传感器数据变成教练和学员看得懂、用得上的训练反馈

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Infrastructure

- [x] **INFRA-01**: Streamlit multi-page app skeleton with 5 views + sidebar navigation
- [x] **INFRA-02**: Coach/athlete view toggle via sidebar switch (UI-only, no auth)
- [x] **INFRA-03**: CSV data loading layer — scan data/ directory, parse set metadata from filenames
- [x] **INFRA-04**: Session/set selector — dropdown to pick which recording to analyze
- [x] **INFRA-05**: Python 3.12 environment upgrade + requirements.txt with pinned versions
- [x] **INFRA-06**: Configuration module — FINA thresholds, camera URL, BLE UUIDs as editable config

### Single-Set Analysis (View 2)

- [ ] **ANAL-01**: Quantitative scoring card — 5 metrics: leg vertical deviation, leg height index, shoulder-knee alignment, smoothness (Jerk), exhibition hold stability
- [ ] **ANAL-02**: FINA deduction rule mapping — <15°=clean, 15-30°=0.2 deduction, >30°=0.5+ deduction, auto-scored per set
- [ ] **ANAL-03**: Action phase timeline — horizontal bar with prep/entry/lift/exhibition/descent phases, color-coded quality per phase
- [ ] **ANAL-04**: Phase detection from IMU signals — acceleration peaks for transitions, jerk plateau for holds (scipy.signal.find_peaks)
- [x] **ANAL-05**: Keyframe comparison — exhibition pose vs standard template side-by-side, deviation angles marked in red
- [ ] **ANAL-06**: Post-set report auto-generation — triggered on set selection, 2-3 second render

### Visualization

- [ ] **VIZ-01**: Joint angle gauges with FINA zone coloring — green/yellow/red circular indicators (Plotly go.Indicator)
- [ ] **VIZ-02**: IMU waveform display — accel/gyro scrolling time-series curves + fused tilt angle
- [x] **VIZ-03**: Skeleton overlay on recorded video frames — MediaPipe bones rendered on playback frames via st.image
- [ ] **VIZ-04**: IMU + Vision fusion chart — dual-axis Plotly showing both sensor angles on same timeline with correlation coefficient

### AI Integration (View 4 partial)

- [ ] **AI-01**: Claude API integration wrapper — button-gated calls, response caching in session_state, mock mode for development
- [ ] **AI-02**: AI coach per-set feedback — structured prompt with 5 metrics + phase data → natural language improvement suggestions
- [ ] **AI-03**: Motion pattern clustering — PCA 2D scatter + K-Means/DBSCAN grouping of historical set feature vectors
- [ ] **AI-04**: AI training plan suggestions — cross-session trend analysis, Claude API with multi-session context

### Progress Tracking (View 3)

- [ ] **PROG-01**: Multi-set trend chart — X=set number, Y=each metric, regression line for direction, fatigue flag
- [ ] **PROG-02**: Radar chart comparison — select 2 sets, overlay 6-axis spider chart (Plotly go.Scatterpolar)
- [ ] **PROG-03**: History table with filter — by date, action type; sortable columns
- [ ] **PROG-04**: CSV export — download button for raw data + computed summary per set

### Real-Time Monitoring (View 1)

- [ ] **LIVE-01**: Live angle gauges during recording — st.fragment(run_every=0.5s) reading latest CSV data
- [ ] **LIVE-02**: Live IMU waveform — scrolling accel/gyro curves updated via fragment polling
- [ ] **LIVE-03**: Recording status bar — current set, duration, BLE connection status, data rate
- [ ] **LIVE-04**: Process isolation — sync_recorder.py runs as separate OS process, dashboard reads CSV tail

### Team Synchronization (View 5)

- [ ] **SYNC-01**: Multi-person BLE connection manager — 3 athletes × 2 nodes = 6 simultaneous BLE connections
- [ ] **SYNC-02**: DTW synchronization heatmap — time × athlete, color = deviation from group mean (tslearn)
- [ ] **SYNC-03**: Pairwise DTW distance matrix — 3×3 grid showing sync quality between each pair
- [ ] **SYNC-04**: Rhythm curve overlay — all athletes' angle time-series superimposed on same chart
- [ ] **SYNC-05**: Calibration flow — fixed position lineup + characteristic motion for IMU-to-person mapping
- [ ] **SYNC-06**: AI synchronization report — Claude API analysis of who's out of sync, when, and why

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Visualization

- **VIZ-V2-01**: Real-time video streaming in dashboard (streamlit-webrtc)
- **VIZ-V2-02**: 3D skeleton visualization with rotation controls

### Advanced AI

- **AI-V2-01**: Anomaly detection with frame-level flagging (jerk spike auto-detection)
- **AI-V2-02**: Competition score prediction based on training data
- **AI-V2-03**: Automated drill recommendation engine

### Platform

- **PLAT-V2-01**: Cloud deployment (Vercel + Supabase) for remote access
- **PLAT-V2-02**: User authentication for multi-team support
- **PLAT-V2-03**: SQLite/PostgreSQL migration for large dataset management

### Team Expansion

- **SYNC-V2-01**: ESP-NOW protocol for >6 device scalability
- **SYNC-V2-02**: MediaPipe multi-person vision-based sync (single camera, all athletes)
- **SYNC-V2-03**: Multi-camera stitching for full-pool coverage

## Out of Scope

| Feature | Reason |
|---------|--------|
| Custom ML pose model | Insufficient training data; MediaPipe + IMU fusion is the thesis |
| Mobile native app | Streamlit responsive web works on any browser |
| Database backend | CSV sufficient for <100 sessions; add abstraction layer for future swap |
| Real-time video in Streamlit | Framework limitation; keep existing OpenCV window for live video |
| Weekly training plan generator | Outside scope; requires injury/fitness/schedule context system doesn't capture |
| 10+ KPI simultaneous display | Research shows coach cognitive overload at >5 metrics; use progressive disclosure |
| User login/auth | LAN-only single-team tool; coach/athlete toggle is UI switch |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 1 | Complete |
| INFRA-05 | Phase 1 | Complete |
| INFRA-06 | Phase 1 | Complete |
| ANAL-01 | Phase 2 | Pending |
| ANAL-02 | Phase 2 | Pending |
| ANAL-03 | Phase 2 | Pending |
| ANAL-04 | Phase 2 | Pending |
| ANAL-05 | Phase 2 | Complete |
| ANAL-06 | Phase 2 | Pending |
| VIZ-01 | Phase 2 | Pending |
| VIZ-02 | Phase 2 | Pending |
| VIZ-03 | Phase 2 | Complete |
| VIZ-04 | Phase 2 | Pending |
| PROG-01 | Phase 3 | Pending |
| PROG-02 | Phase 3 | Pending |
| PROG-03 | Phase 3 | Pending |
| PROG-04 | Phase 3 | Pending |
| AI-01 | Phase 4 | Pending |
| AI-02 | Phase 4 | Pending |
| AI-03 | Phase 4 | Pending |
| AI-04 | Phase 4 | Pending |
| LIVE-01 | Phase 5 | Pending |
| LIVE-02 | Phase 5 | Pending |
| LIVE-03 | Phase 5 | Pending |
| LIVE-04 | Phase 5 | Pending |
| SYNC-01 | Phase 6 | Pending |
| SYNC-02 | Phase 6 | Pending |
| SYNC-03 | Phase 6 | Pending |
| SYNC-04 | Phase 6 | Pending |
| SYNC-05 | Phase 6 | Pending |
| SYNC-06 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 34 total
- Mapped to phases: 34
- Unmapped: 0

---
*Requirements defined: 2026-03-22*
*Last updated: 2026-03-22 after roadmap creation*
