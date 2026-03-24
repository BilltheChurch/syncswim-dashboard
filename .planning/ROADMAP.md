# Roadmap: SyncSwim Dashboard

## Overview

Transform existing IMU + vision sensor fusion data into a Streamlit web dashboard that coaches and athletes can actually use. The journey starts with environment setup and data loading (Python 3.12 upgrade is a blocker), then builds post-recording analysis views (highest immediate coaching value), adds cross-session progress tracking, integrates AI coaching via Claude API (with cost management infrastructure), enables real-time monitoring during training sessions, and finally tackles multi-person synchronization analysis (the hardest technical challenge, depends on everything above).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Environment** - Python 3.12 upgrade, Streamlit skeleton, data loading, configuration (completed 2026-03-22)
- [x] **Phase 2: Single-Set Analysis** - Post-recording analysis report with scoring, phase timeline, keyframe comparison, and sensor visualizations (completed 2026-03-24)
- [ ] **Phase 3: Progress Tracking** - Multi-set trend charts, radar comparison, history table, CSV export
- [ ] **Phase 4: AI Coaching** - Claude API integration with cost management, per-set feedback, pattern clustering, training plan suggestions
- [ ] **Phase 5: Real-Time Monitoring** - Live gauges, waveforms, and status bar during recording sessions via process isolation
- [ ] **Phase 6: Team Synchronization** - Multi-person BLE connections, DTW sync analysis, calibration, AI sync reports

## Phase Details

### Phase 1: Foundation & Environment
**Goal**: A running Streamlit app that loads existing CSV data and provides the navigation skeleton for all 5 views
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06
**Success Criteria** (what must be TRUE):
  1. Running `streamlit run` launches the app with sidebar navigation showing all 5 view pages
  2. Coach/athlete toggle in sidebar switches the UI perspective label (no auth required)
  3. Selecting a recording session from the dropdown loads its CSV data and displays basic metadata (set count, duration, timestamps)
  4. App runs on Python 3.12 with all dependencies (numpy, scipy, mediapipe, plotly, streamlit) installed and importable
  5. FINA thresholds and hardware config (camera URL, BLE UUIDs) are editable in a config file without code changes
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Environment setup, core library extraction, config module, data loader, and tests
- [x] 01-02-PLAN.md — Streamlit app skeleton with navigation, role toggle, set selector, and settings

### Phase 2: Single-Set Analysis
**Goal**: After selecting a recorded set, coaches see a complete analysis report with quantitative scoring, phase timeline, keyframe comparison, and sensor fusion visualizations
**Depends on**: Phase 1
**Requirements**: ANAL-01, ANAL-02, ANAL-03, ANAL-04, ANAL-05, ANAL-06, VIZ-01, VIZ-02, VIZ-03, VIZ-04
**Success Criteria** (what must be TRUE):
  1. Selecting a recorded set auto-generates an analysis report within 3 seconds showing 5 scored metrics (leg vertical deviation, leg height index, shoulder-knee alignment, smoothness, hold stability) with FINA deduction mapping
  2. The action phase timeline displays horizontal bars for prep/entry/lift/exhibition/descent with per-phase quality color coding, derived from IMU signal peak detection
  3. Keyframe comparison shows the exhibition pose skeleton side-by-side with the standard template, with deviation angles marked in red
  4. Joint angle gauges display green/yellow/red FINA zone coloring, and IMU waveform charts show accel/gyro curves with fused tilt angle
  5. A dual-axis fusion chart overlays IMU tilt angle and vision joint angle on the same timeline with correlation coefficient displayed
**Plans**: 4 plans

Plans:
- [ ] 02-01-PLAN.md — Scoring engine (5 metrics + FINA deductions), phase detection (scipy find_peaks), metrics orchestrator
- [ ] 02-02-PLAN.md — Plotly chart builders: gauge charts, phase timeline, IMU waveform, fusion dual-axis chart
- [ ] 02-03-PLAN.md — Recording pipeline MP4/landmarks + dashboard skeleton overlay renderer
- [ ] 02-04-PLAN.md — Training page integration: scoring card + 3-tab report layout + visual verification

### Phase 3: Progress Tracking
**Goal**: Coaches can compare multiple sets within a session and track improvement over time with charts, tables, and data export
**Depends on**: Phase 2
**Requirements**: PROG-01, PROG-02, PROG-03, PROG-04
**Success Criteria** (what must be TRUE):
  1. A trend chart plots each metric across sets (X=set number, Y=metric value) with regression lines indicating improvement or fatigue
  2. Selecting any two sets displays an overlaid 6-axis radar chart comparing their performance profiles
  3. A filterable history table shows all recorded sets (filterable by date and action type) with sortable columns
  4. A download button exports raw data plus computed summaries as a CSV file
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

### Phase 4: AI Coaching
**Goal**: Claude API provides natural language coaching advice per set and cross-session training suggestions, with cost management infrastructure preventing accidental API spend
**Depends on**: Phase 2, Phase 3
**Requirements**: AI-01, AI-02, AI-03, AI-04
**Success Criteria** (what must be TRUE):
  1. AI coaching calls are gated behind explicit button clicks (never triggered by page reruns), responses are cached in session_state, and a mock mode works without an API key
  2. Clicking "Get AI Feedback" on a set report sends the 5 metrics + phase data to Claude and displays natural language improvement suggestions within the report view
  3. A PCA 2D scatter plot shows historical sets clustered by motion pattern (K-Means/DBSCAN), revealing which sets are similar and which are outliers
  4. An AI training plan view synthesizes multi-session trends into stage-specific improvement suggestions via Claude API
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Real-Time Monitoring
**Goal**: During a live recording session, the dashboard displays live sensor data (angles, waveforms, status) without interfering with the recording process
**Depends on**: Phase 1, Phase 2
**Requirements**: LIVE-01, LIVE-02, LIVE-03, LIVE-04
**Success Criteria** (what must be TRUE):
  1. While sync_recorder.py runs as a separate OS process, the dashboard reads the CSV tail and displays live joint angle gauges updated every ~0.5 seconds via st.fragment
  2. A scrolling IMU waveform chart shows accel/gyro curves updating in near-real-time during recording
  3. A status bar displays the current set number, recording duration, BLE connection status, and data rate
  4. Starting/stopping the recording process does not crash or freeze the dashboard, and the dashboard does not interfere with recording data integrity
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

### Phase 6: Team Synchronization
**Goal**: Three athletes' sensor data is captured simultaneously, and the dashboard visualizes their synchronization quality with DTW analysis, rhythm overlays, and AI-generated sync reports
**Depends on**: Phase 4, Phase 5
**Requirements**: SYNC-01, SYNC-02, SYNC-03, SYNC-04, SYNC-05, SYNC-06
**Success Criteria** (what must be TRUE):
  1. The BLE connection manager successfully connects to 6 M5StickC Plus2 devices (3 athletes x 2 nodes) simultaneously and records synchronized data
  2. A calibration flow maps each IMU device to its athlete via a fixed-position lineup and characteristic motion sequence
  3. A synchronization heatmap (time x athlete) and a 3x3 pairwise DTW distance matrix visualize who is in sync and who is drifting
  4. All athletes' angle time-series curves overlay on the same chart, revealing rhythm alignment and divergence points
  5. An AI synchronization report (via Claude API) identifies which athlete is out of sync, during which phase, and suggests corrections
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD
- [ ] 06-03: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Environment | 2/2 | Complete   | 2026-03-22 |
| 2. Single-Set Analysis | 4/4 | Complete   | 2026-03-24 |
| 3. Progress Tracking | 0/2 | Not started | - |
| 4. AI Coaching | 0/2 | Not started | - |
| 5. Real-Time Monitoring | 0/2 | Not started | - |
| 6. Team Synchronization | 0/3 | Not started | - |
