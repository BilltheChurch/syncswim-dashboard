# Architecture Patterns

**Domain:** Real-time sports analytics dashboard (Streamlit + IMU/Vision sensor fusion)
**Researched:** 2026-03-22

## Recommended Architecture

**Pattern: Layered Service Architecture with Fragment-Based UI**

The dashboard sits on top of the existing multi-script pipeline as a presentation and analysis layer. It does NOT replace the recording scripts (`sync_recorder.py`); instead, it reads their output (CSV files in `data/set_*/`) and, for real-time monitoring, connects to the same data sources through a shared data service.

```
+-------------------------------------------------------------------+
|  STREAMLIT APP (app.py entrypoint + st.navigation router)         |
|                                                                   |
|  +--------------------+  +---------------------+  +------------+  |
|  | View 1: Live       |  | View 2: Set Report  |  | View 3:    |  |
|  | Monitor            |  | (post-session)      |  | Trends     |  |
|  | [@st.fragment      |  |                     |  |            |  |
|  |  run_every=0.5s]   |  | View 4: AI Deep     |  | View 5:    |  |
|  +--------+-----------+  | Analysis            |  | Team Sync  |  |
|           |              +----------+----------+  +-----+------+  |
|           |                         |                   |         |
|  +--------v-------------------------v-------------------v------+  |
|  |              STATE LAYER (st.session_state)                 |  |
|  |  - current_set, selected_sets[], athlete_id, role           |  |
|  |  - live_buffer (deque), ai_cache, filter_params             |  |
|  +-----+-------------------+-------------------+--------------+  |
|        |                   |                   |                  |
|  +-----v------+  +---------v-------+  +--------v-----------+     |
|  | Data        |  | Analysis        |  | AI Service         |     |
|  | Service     |  | Service         |  | (Claude API)       |     |
|  | (CSV I/O,   |  | (tilt calc,     |  | (prompt templates, |     |
|  |  caching,   |  |  correlation,   |  |  streaming resp,   |     |
|  |  live feed) |  |  DTW, scoring)  |  |  response cache)   |     |
|  +-----+------+  +---------+-------+  +--------+-----------+     |
|        |                   |                                      |
+-------------------------------------------------------------------+
         |                   |
    +----v-------------------v----+
    |  FILESYSTEM (data/set_*/)   |
    |  imu_NODE_A1.csv            |
    |  vision.csv                 |
    |  analysis.png               |
    +-----------------------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With | Build Phase |
|-----------|---------------|-------------------|-------------|
| **app.py** (Entrypoint) | Page routing via `st.navigation`, global config, role selection (coach/athlete), sidebar layout | All pages, session state | Phase 1 |
| **Data Service** (`services/data_service.py`) | CSV loading with `@st.cache_data`, set directory discovery, data schema normalization, live data buffer management | Filesystem (CSV), session state | Phase 1 |
| **Analysis Service** (`services/analysis_service.py`) | IMU tilt calculation, correlation, smoothing, scoring, DTW, clustering -- refactored from existing `analyze.py` logic | Data Service | Phase 2 |
| **AI Service** (`services/ai_service.py`) | Claude API client wrapper, prompt template management, response streaming, response caching | Claude API (external), Analysis Service (for context) | Phase 3 |
| **View 1: Live Monitor** (`pages/live_monitor.py`) | Real-time skeleton overlay, joint color coding, IMU waveforms, status bar. Uses `@st.fragment(run_every="0.5s")` for auto-refresh | Data Service (live buffer), session state | Phase 2 |
| **View 2: Set Report** (`pages/set_report.py`) | Timeline, keyframe comparison, scoring card, FINA deduction mapping | Data Service, Analysis Service, AI Service | Phase 2-3 |
| **View 3: Trends** (`pages/trends.py`) | Multi-set trend charts, radar comparison, history table, CSV export | Data Service, Analysis Service | Phase 3 |
| **View 4: AI Deep Analysis** (`pages/ai_analysis.py`) | DTW sync analysis, pattern clustering, anomaly detection, AI training plan | Analysis Service, AI Service | Phase 4 |
| **View 5: Team Sync** (`pages/team_sync.py`) | Multi-athlete heatmap, pairwise DTW matrix, rhythm overlay, AI sync report | Data Service, Analysis Service, AI Service | Phase 5 |

### Data Flow

**Flow A: Post-Session Analysis (primary path, build first)**

```
CSV files on disk
  --> Data Service loads with @st.cache_data(ttl=60)
    --> Analysis Service computes metrics (tilt, correlation, scoring)
      --> View 2/3 renders charts via Plotly
        --> AI Service generates natural language feedback (on-demand, cached)
```

**Flow B: Real-Time Monitoring (secondary path, build after post-session works)**

```
sync_recorder.py writes CSV in real-time
  --> Data Service polls file with @st.fragment(run_every="0.5s")
    --> Reads tail of CSV (last N rows) into session_state live_buffer
      --> View 1 renders rolling charts + skeleton overlay
```

**Flow C: AI Insights (tertiary, layered on top of analysis)**

```
User triggers "Generate AI Feedback" button
  --> Analysis Service produces structured metrics dict
    --> AI Service builds prompt from template + metrics
      --> Claude API streams response
        --> st.write_stream renders tokens as they arrive
          --> Response cached in session_state to avoid re-calling
```

## Directory Structure

```
test_rec/
  app.py                    # Streamlit entrypoint (router only)
  pages/
    live_monitor.py         # View 1: real-time during training
    set_report.py           # View 2: single set analysis
    trends.py               # View 3: multi-set comparison
    ai_analysis.py          # View 4: AI deep analysis
    team_sync.py            # View 5: team synchronization
  services/
    data_service.py         # CSV loading, caching, set discovery
    analysis_service.py     # Metric computation, scoring, DTW
    ai_service.py           # Claude API wrapper, prompts
  config/
    scoring.py              # FINA deduction rules, thresholds
    prompts.py              # AI prompt templates
    constants.py            # Shared constants (colors, joint maps)
  components/
    skeleton_renderer.py    # Plotly-based skeleton drawing
    gauge_chart.py          # Angle gauge components
    radar_chart.py          # Radar comparison chart
    timeline.py             # Action timeline component
  data/                     # Existing CSV data (unchanged)
    set_001_.../
    set_002_.../
  # Existing scripts (unchanged)
  sync_recorder.py
  recorder.py
  vision.py
  analyze.py
```

**Rationale:** This structure separates concerns cleanly. The `services/` layer is importable by any page without circular dependencies. The `components/` layer holds reusable chart builders that multiple views share. The `config/` layer centralizes domain knowledge (FINA rules, joint names, thresholds) so changes propagate everywhere.

## Patterns to Follow

### Pattern 1: st.navigation Router (Entrypoint)

**What:** The `app.py` entrypoint does ONLY routing and global sidebar. No business logic.
**When:** Always -- this is the Streamlit-recommended pattern for multi-page apps.
**Why:** Keeps the router lightweight. Pages load independently. Role-based page visibility is trivial.

```python
# app.py
import streamlit as st

st.set_page_config(page_title="SyncSwim Dashboard", layout="wide")

# Role selection in sidebar
role = st.sidebar.selectbox("Role", ["Coach", "Athlete"])
st.session_state["role"] = role

# Define pages -- conditionally include based on role
coach_pages = [
    st.Page("pages/live_monitor.py", title="Live Monitor", icon="📡"),
    st.Page("pages/set_report.py", title="Set Report", icon="📊"),
    st.Page("pages/trends.py", title="Trends", icon="📈"),
    st.Page("pages/ai_analysis.py", title="AI Analysis", icon="🤖"),
    st.Page("pages/team_sync.py", title="Team Sync", icon="👥"),
]
athlete_pages = [
    st.Page("pages/set_report.py", title="My Report", icon="📊"),
    st.Page("pages/trends.py", title="My Progress", icon="📈"),
]

pages = coach_pages if role == "Coach" else athlete_pages
pg = st.navigation(pages)
pg.run()
```

**Confidence:** HIGH -- `st.navigation` is the official recommended approach per Streamlit docs.

### Pattern 2: Fragment-Based Real-Time Updates

**What:** Use `@st.fragment(run_every="0.5s")` for the live monitoring panel instead of full page reruns.
**When:** View 1 (Live Monitor) where sensor data streams in continuously.
**Why:** Only the live chart fragment reruns every 500ms, not the entire page. This prevents sidebar flicker, preserves widget state, and is far more performant than `st.rerun()` loops.

```python
# pages/live_monitor.py
import streamlit as st
from services.data_service import get_live_data

@st.fragment(run_every="0.5s")
def live_imu_chart():
    data = get_live_data()  # reads tail of active CSV
    st.line_chart(data[["ax", "ay", "az"]], height=200)
    st.metric("Tilt Angle", f"{data['tilt'].iloc[-1]:.1f} deg")

@st.fragment(run_every="1s")
def live_status_bar():
    st.write(f"Set: {st.session_state.get('current_set', 'N/A')}")
    st.write(f"BLE: {'Connected' if st.session_state.get('ble_ok') else 'Disconnected'}")

live_imu_chart()
live_status_bar()
```

**Confidence:** HIGH -- `st.fragment` with `run_every` is the official Streamlit pattern for streaming dashboards, documented with sensor/real-time examples.

### Pattern 3: Service Layer with Caching

**What:** All data access goes through service functions decorated with `@st.cache_data` or `@st.cache_resource`.
**When:** Every CSV load, every computed metric, every AI response.
**Why:** Streamlit reruns the entire page script on every interaction. Without caching, a 5000-row CSV reload + metric computation happens on every button click. Caching eliminates this.

```python
# services/data_service.py
import streamlit as st
import pandas as pd
import os

@st.cache_data(ttl=60)
def load_set(set_dir: str) -> dict:
    """Load a set's IMU and vision CSVs. Cached for 60s."""
    imu_path = os.path.join(set_dir, "imu_NODE_A1.csv")
    vis_path = os.path.join(set_dir, "vision.csv")
    result = {}
    if os.path.exists(imu_path):
        result["imu"] = pd.read_csv(imu_path)
    if os.path.exists(vis_path):
        result["vision"] = pd.read_csv(vis_path)
    return result

@st.cache_data(ttl=300)
def list_sets(data_dir: str = "data") -> list[str]:
    """Discover all set directories, sorted by date."""
    sets = [d for d in os.listdir(data_dir)
            if d.startswith("set_") and os.path.isdir(os.path.join(data_dir, d))]
    return sorted(sets, reverse=True)
```

**Confidence:** HIGH -- `@st.cache_data` for DataFrames is the primary recommended pattern in Streamlit docs.

### Pattern 4: Session State as Cross-Page Memory

**What:** Use `st.session_state` for user selections, computed results, and AI response cache. Never use module-level globals.
**When:** Any data that must persist across page navigations or widget interactions.
**Why:** Streamlit reruns scripts top-to-bottom. Module-level variables reset. Session state survives reruns and page switches.

```python
# Initialize defaults (in app.py or at top of page)
if "selected_set" not in st.session_state:
    st.session_state["selected_set"] = None
if "ai_cache" not in st.session_state:
    st.session_state["ai_cache"] = {}
```

**Confidence:** HIGH -- this is fundamental to Streamlit's execution model.

### Pattern 5: Plotly for Interactive Charts (not Matplotlib)

**What:** Use Plotly (`st.plotly_chart`) for all dashboard visualizations instead of Matplotlib.
**When:** All charts in the dashboard.
**Why:** Plotly renders interactive charts natively in the browser (hover, zoom, pan, select). Matplotlib generates static PNGs that require server-side rendering. For a dashboard that coaches interact with on iPads, interactivity is essential. The existing `analyze.py` uses Matplotlib, but the dashboard should use Plotly. Keep `analyze.py` as-is for standalone CLI use.

**Confidence:** HIGH -- Plotly is the standard choice for Streamlit dashboards requiring interactivity.

### Pattern 6: AI Response Streaming

**What:** Stream Claude API responses token-by-token using `st.write_stream` for natural UX.
**When:** View 2 (AI Coach Suggestions) and View 4 (AI Deep Analysis).
**Why:** AI responses take 3-10 seconds. Showing a spinner for that long feels broken. Streaming shows the response building in real-time, which feels responsive and lets coaches start reading immediately.

```python
# services/ai_service.py
import anthropic

def stream_coaching_feedback(metrics: dict, prompt_template: str):
    """Stream Claude response for coaching feedback."""
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    prompt = prompt_template.format(**metrics)

    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text

# In page:
# st.write_stream(stream_coaching_feedback(metrics, template))
```

**Confidence:** MEDIUM -- Claude streaming API is well-documented; `st.write_stream` integration is standard but exact error handling patterns need validation during implementation.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Putting BLE Collection Inside Streamlit

**What:** Running the BLE asyncio event loop and `bleak` connection inside the Streamlit app process.
**Why bad:** Streamlit reruns the entire script on every interaction. A BLE connection cannot survive reruns. Asyncio event loops conflict with Streamlit's internal event loop. Threading with `bleak` inside Streamlit's process model leads to race conditions, zombie connections, and `NoSessionContext` errors.
**Instead:** Keep `sync_recorder.py` as the data collection process. Run it separately. The Streamlit dashboard reads the CSV files it produces. For "real-time" monitoring, the dashboard polls the CSV file tail every 500ms via `@st.fragment(run_every)`. This gives near-real-time display (500ms latency) without any of the BLE complexity inside Streamlit.

**Confidence:** HIGH -- Streamlit's own threading docs warn against running long-lived async processes inside the app.

### Anti-Pattern 2: Global Variables for State

**What:** Using module-level Python variables to store user selections, computed results, or data.
**Why bad:** Streamlit reruns the entire script on each interaction. Module-level variables reset to their initial values. In multi-user scenarios, module-level state is shared across all sessions (a security and correctness disaster).
**Instead:** Always use `st.session_state` for per-user mutable state and `@st.cache_data` / `@st.cache_resource` for expensive computations.

### Anti-Pattern 3: One Giant Page File

**What:** Putting all 5 views into a single `app.py` with tabs.
**Why bad:** A single file grows to 2000+ lines. Every tab's code runs on every rerun (even hidden tabs). Import time grows. Collaborative editing becomes impossible.
**Instead:** Use `st.navigation` with separate page files. Each page is a self-contained module that only runs when navigated to.

### Anti-Pattern 4: Calling Claude API on Every Rerun

**What:** Making an API call inside the main page body without caching or gating.
**Why bad:** Streamlit reruns the page on every widget interaction. A slider change triggers a $0.01 API call. 50 slider adjustments = $0.50 wasted. Response time degrades.
**Instead:** Gate AI calls behind an explicit "Generate" button. Cache responses in `st.session_state` keyed by input hash. Only re-call when inputs change AND user explicitly requests it.

### Anti-Pattern 5: Loading All Sets at Once

**What:** Loading every CSV from every set directory into memory on page load.
**Why bad:** With 50+ recording sessions, this could mean loading hundreds of MB of sensor data. Streamlit's 200MB upload limit is irrelevant here but memory pressure is real on a laptop.
**Instead:** Load only the selected set(s) on demand. Use `@st.cache_data` so re-selecting a previously viewed set is instant.

## Scalability Considerations

| Concern | Current (6 sets) | At 50 sets | At 200+ sets |
|---------|-------------------|------------|--------------|
| Set Discovery | `os.listdir` is instant | Still fine | Consider index file or SQLite catalog |
| CSV Loading | `pd.read_csv` < 100ms | Cache handles it | Consider Parquet conversion for large files |
| Real-Time Update | File polling 0.5s | Same | Same (only reads active set) |
| AI API Costs | Negligible | ~$5/month | Cache aggressively, batch similar requests |
| Multi-Athlete | 1 IMU CSV | 3 IMU CSVs per set | 6 CSVs per set, still manageable with caching |
| Concurrent Users | 1 (local) | 2-3 (LAN) | Streamlit handles multi-session; memory is the limit |

## Build Order (Dependency Chain)

The architecture has clear dependency layers. Build bottom-up:

```
Phase 1: Foundation (no external dependencies)
  app.py (router) + Data Service + config/
  --> Can display: set list, raw CSV data, basic navigation
  --> Validates: multi-page structure, caching, session state

Phase 2: Core Analysis (depends on Phase 1)
  Analysis Service + View 2 (Set Report) + View 1 (Live Monitor)
  --> Refactors analyze.py logic into reusable service
  --> Can display: scoring cards, timelines, live IMU charts
  --> Validates: Plotly charts, fragment-based updates, FINA scoring

Phase 3: Comparison + AI (depends on Phase 2)
  AI Service + View 3 (Trends) + AI features in View 2
  --> Can display: trend charts, radar comparisons, AI coaching text
  --> Validates: Claude API integration, streaming, cost management

Phase 4: Advanced Analysis (depends on Phase 2-3)
  View 4 (AI Deep Analysis) -- DTW, clustering, anomaly detection
  --> Can display: pattern clustering, anomaly markers, training plans
  --> Validates: scipy/sklearn integration, advanced Plotly charts

Phase 5: Team Features (depends on all above)
  View 5 (Team Sync) + multi-athlete BLE extension
  --> Can display: sync heatmaps, pairwise DTW, rhythm overlay
  --> Validates: multi-device data handling, N-athlete scaling
```

**Ordering rationale:** Each phase produces a usable dashboard increment. Phase 1 delivers value immediately (coaches can browse recorded data). Phase 2 replaces the CLI `analyze.py` with a visual interface. Phase 3 adds the AI differentiator. Phases 4-5 are the advanced features that make the project stand out for university applications but depend on everything below them.

## Key Technical Decisions

### CSV Polling vs WebSocket for Real-Time

**Decision:** Poll CSV file tail via `@st.fragment(run_every="0.5s")`.
**Why not WebSocket:** The existing `sync_recorder.py` writes to CSV. Adding a WebSocket server to it adds complexity to a working pipeline for marginal latency improvement (500ms vs ~50ms). The dashboard is for coaches watching training, not controlling a nuclear reactor. 500ms latency is imperceptible for human observation of swimming movements.
**Confidence:** HIGH

### Plotly vs Matplotlib vs Streamlit Native Charts

**Decision:** Plotly for complex charts (skeleton overlay, radar, timeline), Streamlit native (`st.line_chart`, `st.metric`) for simple displays.
**Why:** Plotly gives hover tooltips, zoom, and animation. Streamlit native charts are faster for simple time series (they use Vega-Lite under the hood). Use each where it fits.
**Confidence:** HIGH

### Separate Process Architecture (Recorder + Dashboard)

**Decision:** `sync_recorder.py` and `streamlit run app.py` run as separate processes.
**Why:** Clean separation of concerns. Recorder handles real-time BLE/camera. Dashboard handles visualization. They communicate through the filesystem (CSV). This is the simplest correct architecture that avoids threading nightmares.
**Confidence:** HIGH

## Sources

- [Streamlit Multi-Page Apps: st.Page and st.navigation](https://docs.streamlit.io/develop/concepts/multipage-apps/page-and-navigation) -- HIGH confidence
- [Streamlit Fragments (st.fragment)](https://docs.streamlit.io/develop/concepts/architecture/fragments) -- HIGH confidence
- [Streamlit Threading](https://docs.streamlit.io/develop/concepts/design/multithreading) -- HIGH confidence
- [Streamlit Caching Overview](https://docs.streamlit.io/develop/concepts/architecture/caching) -- HIGH confidence
- [Streamlit Session State](https://docs.streamlit.io/develop/concepts/architecture/session-state) -- HIGH confidence
- [Streamlit 2026 Release Notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026) -- HIGH confidence
- [How to Build a Real-Time Live Dashboard with Streamlit](https://blog.streamlit.io/how-to-build-a-real-time-live-dashboard-with-streamlit) -- MEDIUM confidence
- [Streamlit Real-Time Design Patterns](https://dev-kit.io/blog/python/streamlit-real-time-design-patterns-creating-interactive-and-dynamic-data-visualizations) -- MEDIUM confidence
- [Claude Streaming Messages API](https://platform.claude.com/docs/en/build-with-claude/streaming) -- HIGH confidence
- [Streamlit as UI Layer for Claude-Powered Agents](https://medium.com/@hadiyolworld007/streamlit-as-the-ui-layer-for-claude-powered-agents-9ff2e98f3744) -- LOW confidence

---

*Architecture research: 2026-03-22*
