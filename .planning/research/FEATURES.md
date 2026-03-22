# Feature Research

**Domain:** Sports analytics dashboard -- synchronized swimming training analysis (IMU + vision fusion)
**Researched:** 2026-03-22
**Confidence:** MEDIUM-HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features the coach and athlete assume exist. Missing these means the dashboard adds no value over raw CSV files and matplotlib plots already produced by `analyze.py`.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Skeleton overlay on video playback** | Every sports video analysis tool (Dartfish, Kinovea, CoachNow Analyze) shows skeleton on footage. Without it the dashboard feels like a data tool, not a coaching tool. | MEDIUM | Already have MediaPipe skeleton in `vision.py` (OpenCV window). Port to Streamlit via `st.image` frame rendering. Real work is decode + overlay at usable playback speed. No need for real-time streaming -- post-recording playback is sufficient. |
| **Joint angle gauges with threshold coloring** | Color-coded feedback (green/yellow/red) is how every coaching dashboard communicates quality instantly. Coaches read colors, not numbers. Standard in Catapult, Output Sports, Vitruve dashboards. | LOW | Three-zone coloring mapped to FINA execution deductions: green = within tolerance, yellow = minor deduction zone (< 15 deg deviation), red = major deduction zone (> 30 deg). Plotly `go.Indicator` gauge mode. |
| **IMU time-series waveform display** | Raw sensor data visualization is the baseline for any motion capture system. Without showing the IMU streams, half the sensor fusion story is invisible. | LOW | Plotly `go.Scatter` with rolling window for accel/gyro. Already have CSV pipeline. Show fused tilt angle prominently alongside raw streams. |
| **Post-set scoring report (auto-generated)** | After stopping a recording, coach expects "what just happened" without manual steps. Catapult and Hudl auto-generate post-session summaries. This is the core value delivery moment -- the entire system exists for this. | MEDIUM | Trigger on set selection. Generate: time-segmented angle plots, key metrics (peak deviation, stability score, hold duration), pass/fail per FINA threshold. Five core metrics forming a scoring card. |
| **Quantitative scoring card (5 metrics)** | Numbers that map to judging criteria. Without quantified metrics, this is just "video with lines on it." The whole point of sensor fusion is quantification that a coach's eye cannot achieve. | MEDIUM | Leg vertical deviation (degrees from 90), leg height index (% of max extension), shoulder-knee alignment (degrees), smoothness (jerk metric from IMU angular velocity derivative), exhibition hold stability (std dev during hold phase). Each metric needs a FINA-mapped interpretation. |
| **Multi-page navigation (5 views)** | Coach needs different views at different workflow moments. Single page with everything = unusable clutter. Standard in every analytics platform. | LOW | Streamlit multipage app (`pages/` directory). One file per view. Sidebar navigation. Maps to PROJECT.md Views 1-5. |
| **Session/set selector** | Coach must pick which training session and which set to review. Without selection, the dashboard shows nothing or shows the wrong thing. | LOW | `st.selectbox` + filesystem scan of `data/set_XXX_YYYYMMDD_HHMMSS/` directories. Parse directory names for metadata. |
| **Coach vs athlete view toggle** | Two user types with different needs. Coach wants overview + comparison across athletes. Athlete wants personal detail + improvement tips. Every coaching platform (Vitruve, TeamBuildr, Output Sports) separates these views. | LOW | Streamlit sidebar radio button. Coach view = all athletes, comparison tools, session management. Athlete view = personal metrics, AI suggestions, progress only. Not a login -- just a UI switch. |
| **Multi-set trend chart** | Coach needs to see "is the athlete improving within this session?" Trend across sets (X=set number, Y=metric) is standard in TrainingPeaks, Output Sports, and every athlete tracking platform. Fatigue detection is a basic coaching need. | LOW | Plotly line chart. X = set index, Y = each metric. Show regression line for trend direction. Flag fatigue pattern (scores declining in later sets). |
| **Data export (CSV)** | Coaches and researchers expect to extract data. Data in but not out = broken trust. Also needed for the academic paper/PS write-up. | LOW | Already storing CSV. Add `st.download_button` for raw data and computed summary metrics. Include summary CSV alongside raw data per set. |

### Differentiators (Competitive Advantage)

Features that make this project stand out. Especially important for the university application PS narrative. These occupy the gap no commercial tool fills for synchronized swimming.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **IMU + vision fusion angle display** | No commercial synchro tool fuses wearable IMU data with computer vision skeleton. This is the core technical novelty. Show both data streams and their correlation. Demonstrates genuine sensor fusion research capability, not just "I used a library." | MEDIUM | Already validated in `analyze.py` (correlation -0.497). Dashboard version: dual-axis Plotly chart showing IMU tilt angle and MediaPipe joint angle on same timeline with real-time correlation coefficient. The "fusion" is the PS story -- show it prominently as the hero visualization. |
| **FINA deduction rule mapping** | Translate raw angle data into actual competition scoring language. "15 deg deviation = 0.2 point deduction" is something no tool does automatically for synchro. Coaches currently estimate by eye. Bridges the gap between engineering data and sport-specific meaning. | MEDIUM | World Aquatics 2022-2025 rules: execution deductions per element scored 0-10 in 0.25 increments. Synchronization: minor error = -0.1, obvious = -0.5, major (missed element) = -3.0. Leg deviation thresholds: < 15 deg = clean, 15-30 deg = small deduction, > 30 deg = large deduction. Encode as configurable thresholds since rules change between Olympic cycles. |
| **AI coach natural language feedback (Claude API)** | Instead of "deviation = 23.4 deg," generate "Your right leg drifted 23 degrees during the vertical hold. Focus on engaging your core and pressing your hip forward to maintain the line." Bridges data to actionable coaching. This is the highest-perception-value feature for demonstrations. | MEDIUM | Prompt template with structured data input (metrics, phase, athlete level). Claude API call with ~500 token response. Cache results per set to avoid redundant API calls. Rate-limit to control costs. The "wow factor" for PS narrative and interview demonstrations. |
| **Action phase timeline with quality rating** | Segment a routine into phases (preparation / entry / lift / exhibition / descent) and rate each independently. No synchro tool does automated phase detection + per-phase scoring. More actionable than a single overall score. | HIGH | Phase detection from IMU signal patterns: acceleration peaks for transitions, low-jerk plateau for holds. Semi-automated: `scipy.signal.find_peaks` for initial detection, coach can adjust boundaries via slider. Per-phase quality = average metric score within that window. Visualize as horizontal timeline bar with color-coded segments. |
| **Multi-athlete synchronization heatmap (DTW)** | The research contribution. Quantify exactly who is out of sync and when, using Dynamic Time Warping distance. FINA scores synchronization as one of three major components. Currently assessed entirely by subjective judging. This is the gap the project fills. | HIGH | Requires multi-person data (3 athletes x 2 IMU nodes = 6 BLE connections). DTW via tslearn between each pair's angle time series. Visualize: time x athlete heatmap where color = deviation from group mean. Pairwise DTW distance matrix (3x3). This is v2+ territory -- needs hardware expansion first. |
| **Radar chart multi-dimensional comparison** | Select two sets and overlay six-axis radar: leg deviation, height index, alignment, smoothness, stability, phase timing. Instantly shows strengths vs weaknesses. More intuitive than comparing six separate numbers. High visual impact for presentations. | LOW | Plotly `go.Scatterpolar`. Six axes from scoring card metrics, normalized to 0-1. Overlay two or more sets. Low implementation cost, high demo value. |
| **Anomaly detection with frame flagging** | Auto-detect sudden angle changes (jerk spikes) and flag the exact frame/timestamp. Coach jumps directly to problem moments instead of scrubbing through entire recordings. Saves review time. | MEDIUM | Calculate jerk (derivative of angular velocity) from IMU data. Flag frames where jerk > 2 std dev from mean. Link flagged timestamps to video playback position. Z-score based, no training data needed. |
| **Motion pattern clustering (PCA + K-Means)** | Discover groupings in movement data that coaches have not noticed. "Your athlete has two distinct movement patterns -- one efficient, one compensating." Academic credibility for the PS without requiring large datasets. | MEDIUM | scikit-learn pipeline: StandardScaler -> PCA (2D) -> KMeans/DBSCAN. Visual output: 2D scatter with cluster colors. Each point = one set's feature vector. Interesting for paper but lower direct coaching value than other differentiators. |
| **AI training plan suggestions** | Cross-session pattern analysis: "Over the last 3 sessions, exhibition stability has improved 15% but leg height is declining. Recommend focused flexibility work." Goes beyond single-set advice. | MEDIUM | Claude API with multi-session context window. Requires accumulated session data. More meaningful after 5+ sessions of data. Prompt engineering challenge: avoid overly specific medical/training advice. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but will derail this project. Critical given this is a time-bounded academic project, not a commercial product.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Real-time video streaming in dashboard** | "See the live camera feed in Streamlit." Seems obvious for a monitoring tool. | Streamlit uses a request-response model with periodic rerun -- not designed for video streaming. Pushing 26fps video through `st.image` in a loop will be janky, high-latency, and CPU-heavy. WebRTC integration adds massive complexity. Explicitly out of scope per PROJECT.md. | Record video during capture (already working in `sync_recorder.py`). Dashboard shows post-recording playback with skeleton overlay via `st.video()` or frame-by-frame `st.image`. For live monitoring during recording, keep using the existing OpenCV window which already works at 26fps. Dashboard's live view (View 1) shows lightweight IMU waveforms and angle gauges only -- not video. |
| **Cloud deployment** | "Deploy to cloud so coach can access from anywhere." | Adds authentication, hosting costs, latency to BLE/camera data, deployment complexity, GDPR concerns for athlete data. The system runs poolside on a single laptop -- local network is the correct architecture. Out of Scope per PROJECT.md. | Streamlit runs on laptop, accessible via `http://laptop-ip:8501` from any device on same WiFi (iPad, phone). Zero deployment complexity. Coach walks poolside with tablet and connects to local Streamlit. |
| **User authentication system** | "Coach and athlete should have separate logins." | LAN-only tool for a single coaching team. Auth adds session management, password hashing, token refresh -- weeks of work for zero security benefit in this context. No sensitive data beyond training metrics. | Single-user mode. Coach/athlete toggle is a UI switch (`st.sidebar.radio`), not a login. If the tool ever goes multi-team, add auth then. |
| **Database backend (PostgreSQL/SQLite)** | "Store everything in a proper database for querying." | Over-engineering for a prototype with < 100 sessions. CSV files are human-readable, git-friendly, and the existing 4-phase pipeline already writes them. Adding a DB means migration scripts, ORM setup, schema design -- weeks of work for zero user-facing benefit at this scale. | Keep CSV storage. Add a lightweight data loading abstraction layer (`data_loader.py`) so DB can be swapped later if needed. Add a `sessions.json` index file for fast session listing without directory scanning. |
| **Custom ML model for pose estimation** | "Train a synchro-specific pose model for better accuracy." | Insufficient training data (micro-research project, not a dataset effort). MediaPipe is good enough for above-water poses. Custom model training is months of work with uncertain improvement and requires GPU infrastructure. | Use MediaPipe as-is. Compensate for its limitations (water reflections, partial occlusion) with IMU fusion -- that is literally the thesis of the project. Document MediaPipe failure modes as "future work" in the paper. |
| **Real-time multi-person pose tracking (single camera)** | "Track all 3 athletes simultaneously in one camera view." | MediaPipe multi-person detection is unreliable in aquatic environments (water reflections, splashing, partial submersion). Tracking ID persistence across frames is an unsolved problem in this domain. | Single-camera single-person for MVP. Multi-person synchronization analysis uses IMU data (one device per athlete), not simultaneous vision tracking. Vision serves as spot-check confirmation, not primary multi-person data source. |
| **Comprehensive weekly training plan generator** | "AI should create a full weekly training plan based on data." | Way outside scope. Training plans depend on competition schedule, athlete fitness, injury history, team dynamics -- none captured by the system. A bad AI-generated plan could cause injury or misguide training periodization. | AI gives per-set improvement suggestions only: "In your next attempt, focus on X." Scoped, safe, immediately actionable. Leave long-term training planning to the human coach. |
| **Mobile native app** | "Build an iOS/Android app for poolside use." | Months of development (React Native or Flutter) for marginal benefit. Web via Streamlit works on any mobile browser already. Out of Scope per PROJECT.md. | Streamlit responsive layout. Test on iPad Safari (primary coach device). `st.set_page_config(layout="wide")` and mobile-friendly component sizing. |
| **Metric dashboard showing 10+ KPIs simultaneously** | "Show all the data so coach sees everything at once." | 68% of coaches report feeling overwhelmed by analytics dashboards (Harvard Science Review 2025). More metrics visible = less actionable insight. Cognitive overload is the number one anti-pattern in sports analytics UX. "If your analytics need more tutorials than a video game, you've gone too far." | Show 3-5 key metrics prominently per view. Use progressive disclosure: summary card with drill-down to detail. Scoring card has 5 metrics max. Radar chart shows all dimensions at once without number overload. |

## Feature Dependencies

```
[Streamlit App Skeleton + Multi-Page Navigation]
    |
    +---> [Data Loader (CSV)] ---> [Session/Set Selector]
    |         |
    |         +---> [Data Export CSV]  (trivial once loader exists)
    |         |
    |         +---> [Coach/Athlete View Toggle]  (UI-only, no data dependency)
    |
    +---> [IMU Waveform Display]  (needs data loader)
    |
    +---> [Joint Angle Gauges + Threshold Coloring]
    |         |
    |         +---> [FINA Deduction Rule Mapping]  (needs angle values as input)
    |         |
    |         +---> [Quantitative Scoring Card]  (aggregates all angle metrics)
    |                   |
    |                   +---> [Radar Chart Comparison]  (needs scoring card metrics)
    |                   |
    |                   +---> [AI Coach Feedback]  (needs scoring card as prompt input)
    |                   |
    |                   +---> [Multi-Set Trend Chart]  (needs scoring across sets)
    |                   |
    |                   +---> [AI Training Plan Suggestions]  (needs multi-session scores)
    |
    +---> [Skeleton Overlay on Video Playback]
    |         |
    |         +---> [Anomaly Detection + Frame Flagging]  (needs video timeline + jerk calc)
    |         |
    |         +---> [Key Frame Comparison vs Template]  (needs skeleton + reference)
    |
    +---> [IMU + Vision Fusion Overlay Plot]  (needs both data streams aligned)
    |
    +---> [Action Phase Timeline]  (needs IMU signal processing for phase detection)
    |         |
    |         +---> [Per-Phase Quality Rating]  (needs phases + scoring card)
    |
    +---> [Motion Pattern Clustering PCA]  (needs feature vectors from scoring)

[Multi-Person BLE Extension]  (independent infrastructure track)
    |
    +---> [Multi-Athlete Sync Heatmap / DTW]  (needs 3+ athlete data streams)
              |
              +---> [Pairwise DTW Matrix]  (needs DTW computation engine)
              |
              +---> [AI Synchronization Report]  (needs DTW + scoring data)
              |
              +---> [Rhythm Curve Overlay]  (needs multi-athlete angle streams)
```

### Dependency Notes

- **Scoring Card requires Angle Gauges:** The scoring card aggregates individual joint angle metrics. Without angle calculation infrastructure, scoring has no inputs.
- **AI Coach requires Scoring Card:** Claude API prompt needs structured metric data as context. Without quantified scores, the AI generates vague generic advice rather than specific actionable feedback.
- **Radar Chart requires Scoring Card:** Each radar axis maps 1:1 to a scoring card metric. Build scoring computation first, visualization second.
- **DTW Sync Analysis requires Multi-Person BLE:** Synchronization analysis is meaningless with one athlete. This entire branch depends on hardware expansion (6 simultaneous BLE connections) being validated first. Do not attempt DTW features until multi-device BLE is proven.
- **Phase Timeline enhances Scoring Card:** Phase-segmented scoring is more valuable than whole-set scoring, but the whole-set version must work first as a fallback and baseline.
- **Anomaly Detection enhances Video Playback:** Flagged frames are only useful if the coach can jump to that moment in the video player. Build playback navigation before anomaly flagging.
- **FINA Mapping conflicts with Custom Scoring in MVP:** Do not build both a rigid FINA rule engine and a "define your own scoring" system simultaneously. Start with FINA rules hardcoded with configurable thresholds, add full customization later if coaches request it.
- **Fusion Plot is independent:** The IMU + vision correlation plot can be built as soon as the data loader works -- it has minimal dependencies and is the project's technical centerpiece.

## MVP Definition

### Launch With (v1) -- Single Athlete Post-Recording Analysis

The minimum that delivers the core value: "sensor data becomes coaching feedback the coach can act on."

- [ ] **Streamlit multi-page skeleton** -- App infrastructure with sidebar navigation, coach/athlete view toggle, data directory scanner. Foundation for all views.
- [ ] **Data loader for existing CSV structure** -- Read IMU + vision CSVs from `data/set_XXX_YYYYMMDD_HHMMSS/` directories. Parse, align timestamps via common time origin (already validated in `analyze.py`), expose as DataFrames.
- [ ] **Skeleton overlay video playback** -- Render recorded frames with MediaPipe skeleton overlay and joint coloring (green/yellow/red). Frame-by-frame playback with scrubber. This replaces the existing OpenCV window for post-recording review.
- [ ] **Joint angle gauges with FINA threshold coloring** -- Gauge display of key angles at current playback position. Three-zone color mapped to FINA execution deduction brackets.
- [ ] **IMU waveform display** -- Scrolling accel/gyro plots synchronized to video playback position.
- [ ] **IMU + vision fusion overlay plot** -- Dual-axis timeline showing both sensor streams with correlation coefficient. The technical showcase.
- [ ] **Quantitative scoring card (5 metrics)** -- Leg deviation, height index, alignment, smoothness, stability. Each with value + FINA interpretation text.
- [ ] **Multi-set trend chart** -- Line chart of metric progression across sets within a session.
- [ ] **CSV export** -- Download buttons for raw data and summary metrics.

### Add After Validation (v1.x) -- Analysis Depth + AI

Features to add once core dashboard is working and coach feedback confirms metric relevance.

- [ ] **AI coach natural language feedback** -- Claude API integration with structured prompt template. Add when scoring card metrics are stable and prompts are tested with real data.
- [ ] **FINA deduction rule mapping** -- Formal angle-to-deduction mapping with configurable thresholds. Add when angle calculation accuracy is validated against manual scoring by a coach.
- [ ] **Action phase timeline** -- Semi-automated phase segmentation with `scipy.signal.find_peaks` + coach-adjustable boundaries. Per-phase quality ratings.
- [ ] **Radar chart comparison** -- Six-axis overlay of two selected sets. Add when coaches confirm which metrics matter most (axes may need adjustment).
- [ ] **Anomaly detection with frame flagging** -- Jerk-based spike detection with clickable timestamps that jump to video playback position.
- [ ] **Motion pattern clustering** -- PCA + K-Means/DBSCAN scatter plot for pattern discovery. Academic value for paper/PS.

### Future Consideration (v2+) -- Multi-Athlete Synchronization

Features requiring hardware expansion. These represent the research contribution portion of the project.

- [ ] **Multi-person BLE connection (3 athletes x 2 nodes)** -- Hardware and firmware validation for 6 simultaneous BLE connections. Prerequisite for all synchronization features.
- [ ] **MediaPipe multi-person detection** -- Multi-person skeleton extraction + ID tracking. Known to be unreliable in aquatic environments -- IMU is primary data source for sync.
- [ ] **Calibration workflow** -- Pre-session standing calibration + IMU-to-athlete mapping.
- [ ] **Multi-athlete synchronization heatmap** -- DTW-based time x athlete visualization. The flagship research feature.
- [ ] **Pairwise DTW distance matrix** -- N x N synchronization distance between all athlete pairs.
- [ ] **Rhythm curve overlay** -- All athletes' angle curves superimposed for visual sync assessment.
- [ ] **AI synchronization report** -- Natural language analysis of who is out of sync and when, specific to which phase.
- [ ] **Key frame comparison (actual vs template)** -- Requires reference pose definition workflow. Defer template creation UX.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Streamlit app skeleton + multi-page nav | HIGH | LOW | P1 |
| Data loader for CSV structure | HIGH | LOW | P1 |
| Session/set selector | HIGH | LOW | P1 |
| Coach/athlete view toggle | MEDIUM | LOW | P1 |
| Skeleton overlay video playback | HIGH | MEDIUM | P1 |
| Joint angle gauges + threshold coloring | HIGH | LOW | P1 |
| IMU waveform display | MEDIUM | LOW | P1 |
| IMU + vision fusion overlay plot | HIGH | LOW | P1 |
| Quantitative scoring card (5 metrics) | HIGH | MEDIUM | P1 |
| Multi-set trend chart | MEDIUM | LOW | P1 |
| CSV export | MEDIUM | LOW | P1 |
| AI coach feedback (Claude API) | HIGH | MEDIUM | P2 |
| FINA deduction rule mapping | HIGH | MEDIUM | P2 |
| Action phase timeline + quality rating | HIGH | HIGH | P2 |
| Radar chart comparison | MEDIUM | LOW | P2 |
| Anomaly detection + frame flagging | MEDIUM | MEDIUM | P2 |
| Motion pattern clustering (PCA) | LOW | MEDIUM | P2 |
| Multi-person BLE extension | HIGH | HIGH | P3 |
| Synchronization heatmap (DTW) | HIGH | HIGH | P3 |
| Pairwise DTW matrix | MEDIUM | MEDIUM | P3 |
| Rhythm curve overlay | MEDIUM | LOW | P3 |
| AI synchronization report | MEDIUM | MEDIUM | P3 |
| Key frame comparison vs template | MEDIUM | HIGH | P3 |
| Calibration workflow | MEDIUM | MEDIUM | P3 |

**Priority key:**
- **P1:** Must have for launch -- delivers the core "sensor data to coaching feedback" value proposition
- **P2:** Should have -- deepens analysis, adds AI, and creates the "wow factor" for PS narrative and interview demos
- **P3:** Future / research phase -- requires hardware expansion (6 BLE devices), represents the synchronization research contribution

## Competitor Feature Analysis

| Feature | Dartfish | Catapult | Kinovea | CoachNow | **SyncSwim Dashboard** |
|---------|----------|----------|---------|----------|------------------------|
| Video playback + annotation | Full-featured, multi-angle, AI-enhanced | Cloud-based team video | Free, open-source, precise manual tools | Mobile-first, social sharing | Streamlit-based, auto skeleton overlay |
| Skeleton / pose tracking | AI-powered auto-track (2024+) | No (GPS/IMU focus) | Manual point tracking only | Single-tap AI skeleton | MediaPipe auto-detection, full body |
| Joint angle measurement | Yes, manual + auto | No | Yes, manual protractor tool | Yes, AI-assisted single tap | Auto from MediaPipe + IMU tilt fusion |
| IMU / wearable integration | No (video only) | Yes (proprietary Catapult sensors, $$$$) | No | No | Yes -- BLE M5StickC Plus2 (budget hardware) |
| **Sensor fusion (IMU + vision)** | No | Partial (GPS + video, not joint-level) | No | No | **Yes -- core differentiator** |
| **Sport-specific scoring rules** | No (generic tool) | No (generic load/distance metrics) | No | No | **Yes -- FINA artistic swimming rules** |
| **AI natural language feedback** | No | Basic automated insights | No | No | **Yes -- Claude API coaching text** |
| **Team synchronization analysis** | No | Basic formation tracking | No | No | **Yes -- DTW quantification** |
| Target sport | Individual technique (any) | Team invasion sports | Any (manual setup) | Any (video-first coaching) | **Synchronized swimming** |
| Price | $$$$ enterprise | $$$$ enterprise | Free | $$ subscription | Free (self-hosted, open-source) |
| Setup complexity | High (cameras, software) | Very high (sensors, infrastructure) | Low (any camera) | Low (phone camera) | Medium (IMU devices + camera + laptop) |

**Key competitive insight:** No existing tool combines wearable IMU data with computer vision at the joint angle level for synchronized swimming. Dartfish and Kinovea are video-only. Catapult has sensors but targets team invasion sports (football, rugby) with GPS/load metrics, not biomechanical angles. CoachNow added skeleton overlay in 2024 but has no wearable integration or sport-specific scoring. The fusion approach combined with FINA rules and AI coaching occupies a genuinely empty niche. This is the strongest PS narrative: "I identified a gap where coaches have no quantitative tools, and I built a novel solution combining two sensor modalities."

## Sources

- [KINEXON Sports -- Features of Sports Analysis Software for Coaches](https://kinexon-sports.com/blog/benefits-and-features-of-sports-analysis-software-for-coaches/) -- general feature expectations, MEDIUM confidence
- [Harvard Science Review -- Sports Analytics for Coaches: Tools, Metrics, Implementation](https://harvardsciencereview.org/2025/07/09/sports-analytics-for-coaches-tools-metrics-and-implementation/) -- adoption metrics (68% coach overwhelm stat), MEDIUM confidence
- [Harvard Science Review -- Visualizing Sports Metrics](https://harvardsciencereview.org/2025/08/08/visualizing-sports-metrics-transforming-data-into-winning-decisions/) -- dashboard anti-patterns, KPI overload, MEDIUM confidence
- [Inside Synchro -- New Artistic Swimming Rules](https://insidesynchro.org/2022/09/25/what-is-changing-with-the-new-artistic-swimming-rules/) -- FINA/World Aquatics scoring rule changes, HIGH confidence
- [NBC Olympics -- Artistic Swimming Scoring Rules](https://www.nbcolympics.com/news/artistic-swimming-101-olympic-scoring-rules-and-regulations) -- execution/synchronization deduction specifics (minor -0.1, obvious -0.5, major -3.0), HIGH confidence
- [World Aquatics -- AS Rules 2022-2025 (PDF)](https://resources.fina.org/fina/document/2022/11/01/4b3598b6-18cd-411e-ac09-16e49965df3a/00-AS-Rules-2022-2025-Confirmed.pdf) -- official rule document, HIGH confidence
- [Vitruve -- Athlete Dashboards for Coaches](https://vitruve.fit/blog/athlete-dashboards-for-coaches-track-compare-and-optimize-performance/) -- dashboard UX patterns, cross-athlete comparison, MEDIUM confidence
- [Output Sports -- Athlete Dashboards](https://www.outputsports.com/blog/introducing-athlete-dashboards-a-game-changer-for-strength-coaches-physio-practitioners) -- coach/athlete view separation pattern, MEDIUM confidence
- [Dartfish](https://www.dartfish.com/) -- video analysis feature benchmark for individual sports, HIGH confidence (official site)
- [CoachNow Analyze](https://coachnow.com/analyze) -- skeleton overlay and angle measurement benchmark, HIGH confidence (official site)
- [SWIM-360 Project (MDPI Sensors 2025)](https://www.mdpi.com/1424-8220/25/22/7047) -- multimodal sensing for swimming, closest academic comparable, HIGH confidence
- [PoseCoach (IEEE TVCG 2022)](https://dl.acm.org/doi/10.1109/TVCG.2022.3230855) -- video-based coaching system with pose comparison visualization, HIGH confidence
- [tslearn DTW documentation](https://tslearn.readthedocs.io/en/stable/user_guide/dtw.html) -- DTW implementation reference, HIGH confidence
- [GitHub -- Actions-Synchronization-with-DTW](https://github.com/fralomba/Actions-Synchronization-with-Dynamic-Time-Warping) -- DTW for sports video synchronization, MEDIUM confidence
- [World Aquatics -- Competition Regulations 2025 Updates](https://www.worldaquatics.com/news/4186172/world-aquatics-updates-competition-regulations-2025) -- latest rule changes including harsher sync penalties, HIGH confidence
- PROJECT.md requirements (Views 1-5, constraints, out of scope) -- LOCAL, HIGH confidence

---
*Feature research for: SyncSwim Dashboard -- synchronized swimming training analysis (IMU + vision fusion)*
*Researched: 2026-03-22*
