# Technology Stack

**Project:** SyncSwim Dashboard
**Researched:** 2026-03-22
**Mode:** Ecosystem (Streamlit sports analytics dashboard)

## Recommended Stack

This stack extends the existing Python ecosystem (bleak, OpenCV, MediaPipe, matplotlib, numpy) with dashboard, visualization, AI, and analysis libraries. No existing dependencies are replaced.

### Dashboard Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Streamlit | >=1.55.0 | Web dashboard framework | Project constraint (Python-only). v1.55 adds dynamic containers (`on_change` for tabs/expanders) critical for coach/athlete view switching. `st.fragment(run_every=...)` enables real-time sensor streaming without full page reruns. Multipage app support is mature. No JS build tooling needed. | HIGH |

**Key Streamlit features to leverage:**
- `st.fragment(run_every="1s")` -- partial reruns for live IMU waveforms without refreshing the whole page
- `st.navigation()` / multipage -- View 1-5 as separate pages
- `st.session_state` -- persist recording state, selected athlete, current set number
- `st.cache_data` / `st.cache_resource` -- cache CSV loads, MediaPipe model, Claude client
- `.streamlit/secrets.toml` -- Claude API key storage (native, no python-dotenv needed)

### Visualization

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Plotly | >=6.5.2 | Primary charting library | Best real-time dashboard charting in Streamlit. `go.Indicator` for gauge meters (joint angle gauges with FINA zones). `go.Scatter` for IMU waveforms. `go.Heatmap` for sync heat maps. `go.Scatterpolar` for radar charts (multi-dimension comparison). Plotly 6.x has Narwhals abstraction (native Polars support) and WebGL for 3D. Interactive zoom/hover essential for coach drill-down. | HIGH |
| matplotlib | 3.10.0 (existing) | Static export charts | Already in stack. Keep for PNG report generation in `analyze.py`. Do NOT use for dashboard interactive charts -- Plotly is superior for interactivity and real-time. | HIGH |

**Why NOT Altair:** Altair's Grammar of Graphics is elegant but has a row limit (~5000 rows default, configurable but still slower) that would choke on 72.5Hz IMU data streams. Plotly handles large time-series better with WebGL rendering and is more intuitive for gauge/indicator charts needed for FINA scoring displays.

**Why NOT Bokeh:** Bokeh community momentum has slowed. Streamlit's native Bokeh support required a separate `streamlit-bokeh` package as of 2025. Plotly has better Streamlit integration via `st.plotly_chart()` built-in.

### AI Integration

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| anthropic | >=0.86.0 | Claude API Python SDK | Official Anthropic SDK. Supports sync and async clients, streaming responses (SSE), and structured outputs (beta). Async client (`AsyncAnthropic`) pairs well with asyncio already used in BLE code. Streaming enables progressive display of AI coaching advice. | HIGH |

**Usage pattern:**
```python
import anthropic
import streamlit as st

@st.cache_resource
def get_claude_client():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# For coaching advice generation
def generate_coaching_advice(metrics: dict) -> str:
    client = get_claude_client()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text
```

**Model choice:** Use `claude-sonnet-4-20250514` (not Opus) for coaching advice. Sonnet is faster and cheaper -- coaching advice doesn't need Opus-level reasoning. Keep latency low for post-set report generation.

### Data Processing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| pandas | >=2.2.0 | DataFrame operations, CSV I/O | Standard for tabular data. Existing CSV pipeline produces files that pandas reads natively. Ecosystem integration with Plotly, scikit-learn, and Streamlit is seamless. Dataset sizes (72.5Hz * ~60s sets * 6 channels = ~26K rows per set) are well within pandas' sweet spot. | HIGH |
| numpy | 2.4.x (upgrade from 1.26.4) | Array math, signal processing | Already in stack. Pin to 2.x for performance gains on Apple Silicon (ARM NEON vectorization). Used across all analysis code. | HIGH |

**Why NOT Polars:** Polars is 5-30x faster than pandas on large datasets (>1M rows). But SyncSwim's per-set data is ~26K rows -- pandas handles this in <100ms. The entire ecosystem (Plotly, scikit-learn, Streamlit) has native pandas integration. Polars would add complexity for zero practical benefit at this data scale. Re-evaluate only if historical data across hundreds of sessions needs batch processing.

### Signal Processing & Biomechanics

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| scipy | >=1.17.1 | Butterworth filtering, signal analysis | `scipy.signal.butter` + `scipy.signal.filtfilt` for zero-phase Butterworth low-pass filtering of IMU data -- the standard in sports biomechanics. `scipy.signal.find_peaks` for phase segmentation (prep/entry/lift/display/descent). `scipy.interpolate` for resampling IMU (72.5Hz) to vision (26fps) timeline alignment. | HIGH |

**Butterworth filter parameters for IMU data:**
- 4th order low-pass at 10Hz cutoff (standard for human movement, removes sensor noise while preserving motion dynamics)
- Use `filtfilt` (not `lfilter`) to avoid phase distortion -- critical for time-alignment with vision data

### Time Series Analysis (Synchronization)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| tslearn | >=0.8.0 | DTW distance computation | Purpose-built for time series machine learning. `tslearn.metrics.dtw` computes Dynamic Time Warping distance for multi-person synchronization scoring. Integrates with scikit-learn API conventions. Well-maintained (v0.8.0, Feb 2026). | MEDIUM |

**Why tslearn over dtaidistance:** dtaidistance is faster in raw DTW computation (C/Cython backend), but tslearn provides the full pipeline: DTW + DTW Barycenter Averaging + time series clustering (TimeSeriesKMeans). For SyncSwim's use case (DTW matrices, pattern recognition, clustering), tslearn's integrated API is more productive. The pairwise DTW matrix for 3 athletes is only 3 computations -- raw speed is irrelevant.

**Why NOT fastdtw:** fastdtw is an approximation algorithm. For 3-person sync analysis with ~26K points, exact DTW via tslearn is fast enough and more accurate.

### Machine Learning (Pattern Recognition)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| scikit-learn | >=1.8.0 | KMeans, DBSCAN, PCA | Industry standard for clustering and dimensionality reduction. KMeans/DBSCAN for motion pattern clustering (View 4). PCA for 2D scatter visualization of motion patterns. v1.8 adds native Array API support. Already a dependency of tslearn. | HIGH |

### Video Processing (Existing + Extension)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| OpenCV | 4.10.0 (existing) | Frame processing, skeleton overlay | Already in stack. Keep for frame decode and MediaPipe preprocessing. For dashboard playback, write annotated frames to video files post-recording, then serve via Streamlit `st.video()`. | HIGH |
| MediaPipe | 0.10.33 (existing) | Pose landmark detection | Already in stack. Tasks API PoseLandmarker. For multi-person: use multiple PoseLandmarker instances or switch to `pose_landmarker_full.task` model for better accuracy on multiple subjects. | MEDIUM |

**Video in dashboard strategy:** Do NOT use streamlit-webrtc. The camera source is DroidCam MJPEG (not browser webcam), and the processing runs server-side. Instead:
1. During recording: save annotated frames as MP4 via `cv2.VideoWriter`
2. In dashboard: play back via `st.video()` with timeline scrubbing
3. For "live" monitoring (future): use `st.image()` inside `st.fragment(run_every="0.1s")` to push frames -- simpler than WebRTC for LAN-only use

### Configuration & Secrets

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Streamlit secrets | (built-in) | API key management | Native `.streamlit/secrets.toml` for Claude API key. No additional dependency needed. Works locally and in deployment. | HIGH |
| python-dotenv | >=1.1.0 | Fallback env loading | Only if scripts run outside Streamlit context (e.g., standalone `analyze.py`). Lightweight, well-maintained. | LOW |

### Project Structure

| Technology | Purpose | Why | Confidence |
|------------|---------|-----|------------|
| pyproject.toml | Dependency management | The project currently has no requirements.txt or lockfile. Adding `pyproject.toml` with `[project.dependencies]` pins all versions and enables `pip install -e .` for development. Modern Python standard (PEP 621). | HIGH |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Dashboard | Streamlit | Dash (Plotly) | Dash is more powerful for production apps but requires Flask knowledge, callback decorators, and more boilerplate. Streamlit's script-based model matches the existing codebase style. Project constraint explicitly mandates Streamlit. |
| Dashboard | Streamlit | Gradio | Gradio is ML-demo focused, not dashboard-focused. Poor support for custom layouts, multi-page apps, and real-time sensor data. |
| Charting | Plotly | Altair | Row limits, weaker gauge/indicator support, less intuitive for real-time streaming charts. |
| Charting | Plotly | Bokeh | Weaker Streamlit integration (needs separate package), slower community momentum. |
| DTW | tslearn | dtaidistance | Faster raw DTW but lacks integrated clustering/barycenter pipeline. |
| DTW | tslearn | fastdtw | Approximation algorithm -- unnecessary when exact DTW is fast enough for 3-person data. |
| DataFrames | pandas | Polars | Overkill for ~26K row datasets. Poor ecosystem integration with Streamlit/Plotly/sklearn compared to pandas. |
| AI SDK | anthropic | langchain | LangChain adds massive dependency tree and abstraction overhead for what is a simple messages API call. Direct SDK is cleaner, faster, and easier to debug. |
| Video | st.video() + cv2 | streamlit-webrtc | WebRTC is for browser camera sources. DroidCam MJPEG is server-side. st.video() is simpler for playback. |

## Full Dependency List

### New Dependencies (to add)

```bash
pip install streamlit>=1.55.0 plotly>=6.5.2 anthropic>=0.86.0 pandas>=2.2.0 scipy>=1.17.1 tslearn>=0.8.0 scikit-learn>=1.8.0
```

### Existing Dependencies (already installed, pin versions)

```bash
pip install bleak opencv-python==4.10.0 mediapipe==0.10.33 matplotlib==3.10.0 numpy>=2.4.0
```

### Dev Dependencies

```bash
pip install ruff pytest
```

### Recommended pyproject.toml

```toml
[project]
name = "syncswim-dashboard"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    # Existing
    "bleak",
    "opencv-python>=4.10.0",
    "mediapipe>=0.10.33",
    "matplotlib>=3.10.0",
    "numpy>=2.4.0",
    # Dashboard
    "streamlit>=1.55.0",
    "plotly>=6.5.2",
    # AI
    "anthropic>=0.86.0",
    # Analysis
    "pandas>=2.2.0",
    "scipy>=1.17.1",
    "tslearn>=0.8.0",
    "scikit-learn>=1.8.0",
]

[project.optional-dependencies]
dev = ["ruff", "pytest"]
```

## Version Compatibility Notes

| Package | Min Python | Notes |
|---------|-----------|-------|
| streamlit 1.55 | 3.9+ | Project uses 3.10 -- OK |
| plotly 6.5 | 3.8+ | OK |
| anthropic 0.86 | 3.9+ | OK |
| scipy 1.17 | 3.11+ | **WARNING: May require Python 3.11+.** Verify against Python 3.10. If incompatible, use scipy 1.14.x which supports 3.10. |
| scikit-learn 1.8 | 3.10+ | OK |
| tslearn 0.8 | 3.9+ | OK |
| numpy 2.4 | 3.11+ | **WARNING: NumPy 2.x may require Python 3.11+.** If on Python 3.10, pin to numpy 1.26.x (current). |
| mediapipe 0.10.33 | 3.8-3.12 | OK |

**CRITICAL:** The existing system runs Python 3.10.16. NumPy 2.x and SciPy 1.17 may require Python 3.11+. Two paths:
1. **Upgrade Python to 3.11+** (recommended) -- unlocks latest numpy/scipy, better performance on Apple Silicon
2. **Pin older versions** -- numpy==1.26.4, scipy==1.14.1 -- works on 3.10 but misses optimizations

Recommendation: Upgrade to Python 3.12 before starting dashboard work. All dependencies support 3.12.

## Sources

- [Streamlit 2026 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026) -- v1.55.0 features (HIGH confidence)
- [Streamlit 2025 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2025) -- fragment/multipage maturity (HIGH confidence)
- [st.fragment documentation](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment) -- run_every for real-time (HIGH confidence)
- [Streamlit secrets management](https://docs.streamlit.io/develop/concepts/connections/secrets-management) -- native TOML secrets (HIGH confidence)
- [Plotly PyPI](https://pypi.org/project/plotly/) -- v6.5.2 current (HIGH confidence)
- [Plotly 6.0 release blog](https://plotly.com/blog/plotly-dash-major-release/) -- Narwhals, Plotly.js 3.0 (HIGH confidence)
- [Plotly gauge charts docs](https://plotly.com/python/gauge-charts/) -- go.Indicator for KPI (HIGH confidence)
- [anthropic PyPI](https://pypi.org/project/anthropic/) -- v0.86.0 current (HIGH confidence)
- [Anthropic streaming docs](https://docs.anthropic.com/en/api/messages-streaming) -- SSE streaming (HIGH confidence)
- [SciPy PyPI](https://pypi.org/project/SciPy/) -- v1.17.1 current (HIGH confidence)
- [SciPy Butterworth docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html) -- filter design (HIGH confidence)
- [Kinetics Toolkit Butterworth guide](https://kineticstoolkit.uqam.ca/doc/filters_butter.html) -- biomechanics standard (MEDIUM confidence)
- [scikit-learn PyPI](https://pypi.org/project/scikit-learn/) -- v1.8.0 current (HIGH confidence)
- [tslearn PyPI / docs](https://tslearn.readthedocs.io/en/stable/user_guide/dtw.html) -- v0.8.0, DTW (MEDIUM confidence)
- [NumPy PyPI](https://pypi.org/project/numpy/) -- v2.4.3 current (HIGH confidence)
- [Pandas vs Polars benchmarks](https://www.shuttle.dev/blog/2025/09/24/pandas-vs-polars) -- performance at scale (MEDIUM confidence)
- [Streamlit chart libraries comparison](https://dev.to/squadbase/streamlit-chart-libraries-comparison-a-frontend-developers-guide-54il) -- Plotly vs Altair vs Bokeh (MEDIUM confidence)
