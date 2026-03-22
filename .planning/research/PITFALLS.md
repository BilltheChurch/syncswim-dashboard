# Pitfalls Research

**Domain:** Real-time Streamlit dashboard for synchronized swimming motion capture (BLE IMU + MediaPipe vision + Claude AI)
**Researched:** 2026-03-22
**Confidence:** HIGH (multiple sources cross-verified, project-specific codebase concerns integrated)

## Critical Pitfalls

### Pitfall 1: Streamlit's Rerun Model Destroys Real-Time Sensor State

**What goes wrong:**
Developers treat Streamlit like a traditional GUI framework and put BLE data acquisition, MediaPipe processing, and video capture directly in the main script. Every user interaction (button click, slider change, page navigation) triggers a full script rerun, which tears down and recreates all connections. BLE devices disconnect mid-recording. MediaPipe model reloads on every click. Video stream restarts. The dashboard becomes unusable during active training sessions.

**Why it happens:**
Streamlit's execution model reruns the entire script top-to-bottom on every interaction. This is fundamentally incompatible with persistent hardware connections (BLE) and continuous data streams (MJPEG camera). The existing codebase (`sync_recorder.py`) already runs BLE in a daemon thread with its own asyncio event loop -- but naively porting that into Streamlit will break because Streamlit's ScriptRunner thread owns the execution context, and daemon threads spawned inside the script get killed on rerun.

**How to avoid:**
1. **Separate data acquisition from visualization entirely.** Run BLE collection and MJPEG capture in a standalone background process (not a Streamlit thread). Use `st.cache_resource` to hold a singleton reference to a shared data buffer (e.g., `collections.deque` or `queue.Queue`) that the background process writes to and Streamlit reads from.
2. **Use `@st.fragment(run_every="0.5s")` for live data panels** so only the fragment reruns, not the whole page. This prevents widget interactions elsewhere from disrupting the live data display.
3. **Never create BLE connections or MediaPipe models inside the rerunnable script body.** Initialize them once via `@st.cache_resource` or in a separate process launched at app startup.

**Warning signs:**
- BLE status shows "disconnected" every time any button is clicked
- MediaPipe model load time (500ms-1s) appears on every interaction
- Camera feed freezes momentarily when changing tabs or adjusting settings
- Console shows repeated "Starting BLE scan..." or "Loading pose model..." messages

**Phase to address:**
Phase 1 (App skeleton / infrastructure). The data acquisition architecture must be decoupled from Streamlit's rerun lifecycle from day one. Retrofitting this later requires a full rewrite.

---

### Pitfall 2: st.image() Video Loop Causes Memory Leak and Caps at ~14 FPS

**What goes wrong:**
The natural approach for showing live video with skeleton overlay is a `while True` loop calling `st.empty().image(frame)`. This pattern has a confirmed memory leak (Streamlit issue #3911) -- memory grows continuously as frames accumulate in the frontend. Even without the leak, the rendering pipeline tops out at ~14 FPS for 480p, far below the 26 FPS MediaPipe target. The dashboard becomes sluggish, then crashes after extended sessions.

**Why it happens:**
`st.image()` serializes each frame to PNG/JPEG, sends it over WebSocket to the browser, and the browser renders it as a new `<img>` element. This round-trip is inherently too slow for video-rate updates. The `st.empty()` container is supposed to clear the previous frame, but internal reference counting doesn't fully release memory in long-running sessions. The existing project's MJPEG parser (`MjpegStreamReader`) already decodes frames efficiently -- the bottleneck is entirely on the Streamlit rendering side.

**How to avoid:**
1. **For live monitoring (View 1):** Use `streamlit-webrtc` component which handles video via WebRTC (peer-to-peer, not through Streamlit's rerun loop). MediaPipe processing runs in the WebRTC callback thread, and only the annotated skeleton overlay is sent to the browser. This achieves 20-30 FPS.
2. **For post-session replay (View 2):** Pre-render annotated video to an MP4 file using OpenCV's `VideoWriter`, then display with `st.video()`. No frame-by-frame loop needed.
3. **If `streamlit-webrtc` is too complex for MVP:** Display video at reduced rate (5 FPS) via `@st.fragment(run_every="0.2s")` with `st.image()`, and accept the limitation. Show a "recording indicator" instead of full live video, with skeleton data rendered as charts rather than video overlay.

**Warning signs:**
- Python process memory grows steadily during live monitoring (check with `psutil`)
- Browser tab memory exceeds 500MB after 10 minutes
- Frame rate visually stuttery (below 15 FPS)
- CPU usage pegged at 100% on one core

**Phase to address:**
Phase 1 (infrastructure decision) -- must decide streamlit-webrtc vs. reduced-rate approach before building View 1. This is a foundational architectural choice.

---

### Pitfall 3: BLE + Streamlit asyncio Event Loop Collision

**What goes wrong:**
Bleak (the BLE library already used in the project) requires an asyncio event loop. Streamlit also uses asyncio internally for its server. Running `asyncio.run()` inside a Streamlit script raises `RuntimeError: This event loop is already running`. Using `loop.run_until_complete()` fails similarly. Developers then try `nest_asyncio` as a hack, which introduces subtle deadlocks. Or they spawn a thread with its own event loop, but on macOS, CoreBluetooth requires BLE operations to run on the main thread (bleak issue #206, #242), so the thread approach silently fails with "Bluetooth device is turned off" errors.

**Why it happens:**
The existing codebase runs bleak in `asyncio.run()` within a daemon thread (`sync_recorder.py` line ~216). This works standalone because the daemon thread owns its event loop. Inside Streamlit, the ScriptRunner thread already has an event loop, and macOS CoreBluetooth has thread affinity requirements that conflict with both approaches.

**How to avoid:**
1. **Run BLE acquisition as a separate Python process** (not thread, not coroutine inside Streamlit). Use `multiprocessing` or launch a standalone `recorder.py` subprocess. Communicate via a shared file, SQLite WAL-mode database, or `multiprocessing.Queue`.
2. **On macOS specifically:** The BLE process must be the one that starts first and owns the main thread. Streamlit becomes the child or sibling process, not the parent of BLE.
3. **Use a message broker pattern:** BLE process writes timestamped sensor data to a ring buffer (shared memory or file). Streamlit polls the buffer via `@st.fragment(run_every=...)`. This cleanly separates the two event loops.

**Warning signs:**
- `RuntimeError: This event loop is already running` on app start
- `BleakError: Bluetooth device is turned off` when BLE hardware is clearly on
- BLE connections work in standalone script but fail inside Streamlit
- Silent notification callback failures (no data arriving but no error either)

**Phase to address:**
Phase 1 (infrastructure). This must be solved before any BLE integration with the dashboard. The inter-process communication pattern chosen here determines the architecture of everything that follows.

---

### Pitfall 4: Multi-Device BLE Throughput Collapse at 6 Simultaneous Connections

**What goes wrong:**
The project plans to scale from 1 to 6 M5StickC Plus2 devices (3 swimmers x 2 nodes each). At 72.5 Hz per device with binary batch protocol, that is ~435 packets/second total. macOS BLE adapters can handle ~6 connections theoretically, but real-world throughput degrades non-linearly. At 4+ connections, notification callbacks start arriving late, the asyncio event loop falls behind, and packet loss jumps from 0% to 5-15%. The carefully validated 0% packet loss from Phase 1 evaporates.

**Why it happens:**
BLE connection intervals are negotiated per-device but share the same radio. More connections mean more scheduling conflicts. The existing binary batch protocol packs ~12 samples per notification to reduce packet count, but with 6 devices the total BLE radio utilization approaches saturation. Additionally, bleak's notification callbacks are serialized through asyncio -- if one callback blocks (e.g., writing CSV), all other devices' callbacks queue up. The existing `sync_recorder.py` already has a `state.lock` mutex that serializes writes, creating a bottleneck.

**How to avoid:**
1. **Profile incrementally:** Test with 2 devices, then 4, then 6. Measure actual packet loss at each step. Do not assume 6 will work because 1 works.
2. **Eliminate lock contention in the BLE callback:** Use lock-free ring buffers (`collections.deque(maxlen=N)`) instead of mutex-guarded CSV writes. Batch CSV writes to a separate thread.
3. **Increase the BLE connection interval** on the M5StickC firmware from the current default to 15-30ms to give the scheduler more headroom. Accept slightly higher latency for better reliability.
4. **Have a fallback plan:** If 6 simultaneous connections prove unreliable on the MacBook's BLE adapter, consider a USB BLE dongle for additional bandwidth, or stagger recording start times.

**Warning signs:**
- Packet loss above 1% when adding the 4th or 5th device
- BLE notification callback latency exceeding 50ms (measure with timestamps)
- Increasing gap between firmware-reported timestamps and host-received timestamps
- One device's data consistently arriving late compared to others

**Phase to address:**
Multi-person phase (View 5 infrastructure). Must be validated with hardware testing before building any multi-person synchronization features.

---

### Pitfall 5: Claude API Calls Block the Dashboard and Blow the Budget

**What goes wrong:**
Claude API calls for "AI coach suggestions" (View 2) and "AI training plan" (View 4) take 3-15 seconds each. If called synchronously in Streamlit's script execution, the entire dashboard freezes. Users click the button again, creating duplicate requests. With no cost controls, a training session generating analysis for every set (5-10 sets per session, each requiring 2-3 API calls) can consume $2-5 per session. Multiply by daily training and the API bill becomes significant for a student project.

**Why it happens:**
Streamlit is synchronous by default. `anthropic.Client().messages.create()` blocks until the response is complete. The existing project spec calls for Claude API integration in View 2 (per-set analysis), View 4 (deep analysis), and View 5 (sync reports) -- potentially 15+ API calls per training session. There is no caching, no rate limiting, and no cost monitoring planned.

**How to avoid:**
1. **Use streaming responses** with `st.write_stream()` so the user sees progressive output instead of a frozen screen. The Claude API supports SSE streaming natively.
2. **Cache AI results aggressively** with `@st.cache_data(ttl=3600)` keyed on the recording set hash. The same set analyzed twice should not cost twice.
3. **Use Claude Haiku for simple analyses** (per-set summaries, basic feedback) and reserve Sonnet/Opus for deep analysis (training plans, cross-session patterns). Haiku is 10-60x cheaper.
4. **Set `max_tokens` explicitly** (500-1000 for per-set feedback, 2000 for training plans). Never leave it at the default maximum.
5. **Add a cost tracking utility** that logs token usage per API call and displays cumulative session cost in the sidebar.
6. **Batch prompt design:** Send all set data for a session in one API call for the training plan, rather than one call per set.

**Warning signs:**
- Dashboard freezes for 5+ seconds when generating AI feedback
- Users clicking "Generate Analysis" multiple times during the wait
- API bill exceeding $1/day during testing
- Same analysis regenerated on every page navigation (cache miss)

**Phase to address:**
Phase 2 (View 2: per-set analysis) for basic integration. Cost controls and model routing should be built into the API wrapper from the first integration, not added later.

---

### Pitfall 6: Session State Loss on Page Navigation Corrupts Live Recording State

**What goes wrong:**
In Streamlit's multipage app model, navigating between pages (e.g., from "Live Monitor" to "Set Analysis" and back) can lose `st.session_state` values. This is a documented, long-standing issue (Streamlit GitHub #5689). For this project, losing state means: the current recording set number resets, BLE connection status indicator shows stale data, the "current session" context disappears, and the user (coach) thinks they need to restart the recording.

**Why it happens:**
Streamlit's page navigation triggers a full script rerun with a fresh page context. While `st.session_state` is nominally preserved across pages, widgets that were defined on the previous page are garbage-collected, and any state tied to those widgets' keys disappears. HTML-link-based navigation (vs. sidebar navigation) is especially prone to state loss. The project needs 5 views that share recording state -- this is exactly the scenario where this bug bites hardest.

**How to avoid:**
1. **Use `st.navigation()` with `st.Page()` (not the `pages/` directory convention)** for maximum control over page routing and shared state.
2. **Store all critical state in a dedicated state manager class** held in `st.session_state["app_state"]` rather than individual session_state keys. Initialize it once in the entrypoint file with a guard: `if "app_state" not in st.session_state: st.session_state["app_state"] = AppState()`.
3. **Never rely on widget keys for persistent state.** Widget keys are tied to their page's lifecycle. Use callbacks to copy widget values into the centralized state object.
4. **For the coach/athlete view split:** Use a single entrypoint with a role selector, not separate apps. This keeps `st.session_state` in one session.

**Warning signs:**
- Set number resets to 0 when switching from Live Monitor to Analysis
- "BLE: disconnected" shown on a page even though BLE is connected (stale indicator)
- Coach switches to athlete view and loses the selected recording context
- Browser refresh wipes all in-progress session data

**Phase to address:**
Phase 1 (app skeleton). The state management architecture must be established in the first phase. Every subsequent view depends on reliable shared state.

---

### Pitfall 7: MediaPipe Model + OpenCV in Streamlit Process Causes Import/Deployment Chaos

**What goes wrong:**
MediaPipe, OpenCV, TensorFlow (transitive dependency), and numpy have notoriously brittle version interdependencies. The existing codebase already discovered this the hard way (DEVLOG problem #10: numpy<2, opencv-python<4.11, mediapipe 0.10.33, tensorflow-macos 2.15.0). Adding Streamlit into this mix introduces another dependency (protobuf, pillow, pyarrow) that can conflict. The `mediapipe.tasks` import that is currently deferred inside `main()` will fail at Streamlit startup if versions drift. On macOS ARM specifically, tensorflow-macos pins numpy to 1.x, but newer Streamlit versions may pull numpy 2.x.

**Why it happens:**
No `requirements.txt` exists (documented in CONCERNS.md). The working dependency combination is known but not codified. Any `pip install streamlit` in the existing environment risks upgrading numpy or protobuf, breaking mediapipe. The project also has the macOS ARM-specific constraint of using tensorflow-macos rather than standard tensorflow.

**How to avoid:**
1. **Create `requirements.txt` immediately** before adding any new dependencies. Pin exact versions of the known working set:
   ```
   numpy<2
   opencv-python<4.11
   mediapipe==0.10.33
   tensorflow-macos==2.15.0
   bleak>=0.21
   streamlit>=1.39,<2.0
   anthropic>=0.39
   ```
2. **Use a virtual environment** (`python -m venv .venv`) dedicated to this project. Document the setup in a single command.
3. **Test the full import chain at startup:** Add a `check_dependencies()` function that imports all critical packages and reports version conflicts before the app renders.
4. **Consider process isolation:** If MediaPipe/TensorFlow conflicts with Streamlit's dependencies, run the vision processing in a separate subprocess with its own venv.

**Warning signs:**
- `ImportError` or `AttributeError` after running `pip install streamlit`
- `numpy.core.multiarray failed to import` errors
- MediaPipe model loading crash with cryptic protobuf errors
- Different behavior between `python vision.py` (works) and `streamlit run app.py` (crashes)

**Phase to address:**
Phase 0 (pre-Phase 1 setup). Must be resolved before writing any Streamlit code. A broken environment blocks all development.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Polling CSV files for inter-process data sharing | Simple, no new dependencies | Disk I/O latency (50-100ms), file locking issues, stale reads | MVP only; replace with shared memory or SQLite WAL for production |
| Using `time.sleep()` + `st.rerun()` for live updates | Works in 5 lines of code | Full page rerun on every tick, widget state reset, CPU waste | Never -- use `@st.fragment(run_every=...)` instead |
| Hardcoding FINA scoring thresholds in view code | Fast to implement | Impossible to adjust without code changes, coaches can't customize | MVP only; extract to a config file or sidebar controls by Phase 2 |
| Running MediaPipe in IMAGE mode (current codebase) | No timestamp management needed | 2-3x more CPU than VIDEO mode, less stable landmarks between frames | Acceptable for post-session replay; must switch to VIDEO mode for live |
| Storing all session data in `st.session_state` | No external storage needed | Lost on browser refresh, memory pressure with large DataFrames | MVP only; persist to disk/SQLite for anything the coach expects to survive a refresh |
| Calling Claude API synchronously | Simpler code, no callback management | Dashboard freezes 3-15 seconds per call | Never -- always use streaming or background task |

## Integration Gotchas

Common mistakes when connecting to external services and hardware.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Bleak BLE in Streamlit | Calling `asyncio.run()` inside the Streamlit script, causing event loop collision | Run BLE in a separate process; share data via queue or shared buffer |
| DroidCam MJPEG stream | Using `cv2.VideoCapture()` which is broken on macOS ARM (known bug in codebase) | Use the existing `MjpegStreamReader` class; extract to a shared module first |
| Claude API | Sending raw sensor data arrays in the prompt (huge token count, low value) | Pre-compute summary statistics (mean angles, jerk, stability score) and send only those. Include FINA rules in a cached system prompt |
| MediaPipe PoseLandmarker | Loading the `.task` model file with a path relative to working directory | Use `pathlib.Path(__file__).parent / "pose_landmarker_lite.task"` for script-relative resolution (already flagged in CONCERNS.md) |
| Streamlit multipage + BLE status | Showing BLE connection status via a widget that resets on page change | Use a persistent status bar in the entrypoint file (outside any page), updated by reading from the shared data buffer |
| Claude API key | Hardcoding in source or passing via `st.text_input` | Use `st.secrets` (`.streamlit/secrets.toml`) or environment variable. Add `.streamlit/secrets.toml` to `.gitignore` |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Loading full CSV into DataFrame on every fragment rerun | Dashboard freezes for 2-3 seconds on page load | Use `@st.cache_data(ttl=5)` with file-hash key; load once, update incrementally | CSV files exceed 5MB (>10 minutes of 72.5Hz recording) |
| Plotly chart full redraw on every data update | Chart flickers, CPU spikes, confirmed Streamlit bug #8782 | Use `st.empty()` container for chart; install `orjson` for faster serialization; limit visible data window to last 30 seconds | More than 2-3 charts updating simultaneously |
| Per-frame RGB conversion copying full frame array | 24 MB/s memory allocation pressure at 26 FPS (documented in CONCERNS.md) | Accept for current 640x480; if resolution increases, convert in-place or use a pre-allocated buffer | Resolution exceeds 1080p |
| `State.calc_rate()` rebuilding list on every packet | O(n) per packet at 72.5 Hz across 6 devices = 435 list rebuilds/second | Replace with `collections.deque(maxlen=N)` (already recommended in CONCERNS.md) | 3+ BLE devices connected simultaneously |
| Re-computing DTW sync matrix on every page load | DTW on 3-person time series is O(n^2); 10+ seconds for a full session | Compute once after recording stops; cache result in session state and on disk | Session length exceeds 5 minutes |
| Rendering all 26 MediaPipe landmarks when only 5-6 joints matter | Unnecessary draw calls and data transfer | Filter to only the joints used in scoring (shoulder, elbow, hip, knee, ankle) before rendering | Live overlay at >15 FPS target |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Claude API key in source code or `st.session_state` | Key leaked via GitHub push or session state inspection | Use `st.secrets` with `.streamlit/secrets.toml` in `.gitignore`; never log API responses that might echo the key |
| No `max_tokens` on Claude API calls | A single malformed prompt could generate 4096+ tokens at Opus pricing ($75/M output tokens) | Set explicit `max_tokens` on every API call (500 for feedback, 2000 for plans) |
| MJPEG buffer grows unbounded on corrupt stream | RAM exhaustion crash (documented in CONCERNS.md, no current mitigation) | Add `MAX_BUF_SIZE = 5 * 1024 * 1024` cap; reset buffer if exceeded |
| BLE `set_number` wraps at 255, overwrites earlier data | Silent data loss after 255 recording sets | Use Python-side counter for directory naming, not the device-reported `uint8_t` byte |
| No input validation on loaded CSV data | `analyze.py` crashes on truncated/malformed CSV (documented in CONCERNS.md) | Add try/except around CSV parsing; skip malformed rows with warning |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing raw sensor values (quaternions, radians, acceleration m/s^2) to coaches | Coach has no idea what "pitch: -0.342 rad" means; ignores the dashboard | Convert everything to degrees, percentage of ideal, or traffic-light color coding (green/yellow/red) |
| AI feedback uses technical jargon | "DTW distance of 0.847 indicates moderate desynchronization" is useless to a coach | Prompt Claude to use coaching language: "Swimmer B enters the lift position 0.3 seconds late. Cue: watch the count on the preparation phase." |
| Dashboard requires keyboard/mouse interaction during poolside use | Coach has wet hands, is watching swimmers, can't click tiny buttons on a laptop | Design for touch (large buttons, swipe gestures); auto-advance between recording sets; voice-announce key alerts |
| Showing all 5 views simultaneously in navigation | Information overload; coach only needs View 1 during training, View 2-3 between sets, View 4-5 after session | Context-aware navigation: during recording show only View 1; after stop show View 2; in review mode show View 3-5 |
| AI analysis available only after manual trigger | Coach forgets to click; analysis not ready when they walk over to the swimmer | Auto-generate View 2 analysis immediately when recording stops; show a loading spinner, not a button |
| No offline fallback when Claude API is unreachable | Dashboard crashes or shows error when poolside Wi-Fi drops | Cache the last AI response; show quantitative scores (which are computed locally) even when AI is unavailable; queue AI requests for when connectivity returns |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Live video overlay:** Works in demo but memory leaks after 15 minutes of continuous use -- verify with `psutil.Process().memory_info().rss` over a 30-minute session
- [ ] **BLE multi-device connection:** Connects 6 devices on a quiet bench -- verify packet loss under 1% while MediaPipe and Streamlit are also running (CPU contention)
- [ ] **AI coach feedback:** Generates plausible text -- verify it references the actual sensor data (not hallucinated numbers) by including ground truth in the prompt and checking output
- [ ] **FINA scoring:** Displays a score -- verify the threshold-to-deduction mapping matches the actual FINA 2024 rules (15 deg = -0.2, 30 deg = -0.5, >30 deg = -1.0)
- [ ] **Multi-person sync analysis:** DTW produces a number -- verify the distance metric is meaningful by testing with known-synchronized and known-desynchronized recordings
- [ ] **Page navigation:** All 5 views accessible -- verify `st.session_state` preserves the current recording context when navigating between all views in every possible order
- [ ] **CSV export:** File downloads -- verify it includes headers, uses consistent timestamp format, and handles Unicode swimmer names
- [ ] **Session persistence:** Coach closes laptop, reopens 10 minutes later -- verify the current session data is still accessible (not just in RAM-only session_state)

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Event loop collision (BLE + Streamlit) | MEDIUM | Extract BLE to subprocess; define IPC protocol (shared deque or SQLite); takes 1-2 days |
| Memory leak from st.image() video loop | LOW | Switch to `@st.fragment(run_every=...)` with throttled frame rate; or adopt `streamlit-webrtc`; takes 0.5-1 day |
| Session state loss on page navigation | LOW | Centralize all state in a single `AppState` dataclass in `st.session_state`; audit all pages; takes 0.5 day |
| Dependency version conflict after pip install | MEDIUM | Recreate venv from pinned `requirements.txt`; if txt doesn't exist yet, reconstruct from DEVLOG problem #10; takes 0.5-1 day |
| Claude API cost overrun | LOW | Add `max_tokens` limits, switch to Haiku for simple tasks, add `@st.cache_data` on all API calls; takes 0.5 day |
| 6-device BLE packet loss | HIGH | Requires hardware testing and potentially firmware changes (connection interval tuning); may need to reduce to 4 devices or add USB BLE dongle; takes 2-5 days |
| Full-page rerun killing live data display | HIGH | Requires architectural refactor to fragment-based updates; if caught late, affects all views; takes 2-3 days |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Dependency version conflict | Phase 0 (Environment Setup) | `pip install -r requirements.txt && python -c "import streamlit, mediapipe, cv2, bleak, anthropic"` succeeds cleanly |
| Rerun model destroys sensor state | Phase 1 (App Skeleton) | BLE data continues flowing while clicking buttons and switching pages |
| Event loop collision (BLE + asyncio) | Phase 1 (App Skeleton) | BLE process runs independently; Streamlit restart does not kill BLE collection |
| Session state loss on navigation | Phase 1 (App Skeleton) | Navigate through all 5 view stubs in every order; verify a test session_state value persists |
| st.image() memory leak | Phase 1 (Live Monitor architecture) | 30-minute soak test shows memory growth under 50MB |
| Claude API blocking + cost | Phase 2 (AI Integration) | AI feedback streams progressively; session cost displayed in sidebar; same set cached |
| Plotly chart flicker | Phase 2 (Charts) | Live IMU waveform updates without visible flicker at 2 Hz refresh |
| Multi-device BLE throughput | Phase 4 (Multi-person) | 6 devices connected with packet loss under 2% while dashboard is running |
| DTW computation time | Phase 4 (Sync Analysis) | 3-person sync matrix computed in under 5 seconds for a 3-minute recording |
| MediaPipe multi-person tracking | Phase 4 (Multi-person) | Correctly identifies and tracks 3 swimmers with stable IDs for >80% of frames |

## Sources

- [Streamlit Threading Documentation](https://docs.streamlit.io/develop/concepts/design/multithreading) -- official constraints on multithreading in Streamlit apps
- [Streamlit Fragments Documentation](https://docs.streamlit.io/develop/concepts/architecture/fragments) -- `run_every`, element accumulation caveats, fragment scope
- [Streamlit st.fragment API](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment) -- auto-rerun pattern for real-time updates
- [Streamlit Session State issue #5689](https://github.com/streamlit/streamlit/issues/5689) -- session state loss during page switch
- [Streamlit Memory Leak issue #3911](https://github.com/streamlit/streamlit/issues/3911) -- memory increase with st.empty() video frames
- [Streamlit Plotly Flicker issue #8782](https://github.com/streamlit/streamlit/issues/8782) -- chart flickering since v1.35.0
- [Streamlit Performance Pain Points Discussion](https://discuss.streamlit.io/t/what-are-your-performance-pain-points-with-streamlit/8218) -- community-reported bottlenecks
- [Bleak BLE Troubleshooting](https://bleak.readthedocs.io/en/latest/troubleshooting.html) -- macOS threading constraints, connection limits
- [Bleak Multiple Connections Discussion #574](https://github.com/hbldh/bleak/discussions/574) -- practical multi-device BLE limits
- [Bleak macOS Thread Issue #242](https://github.com/hbldh/bleak/issues/242) -- CoreBluetooth thread affinity
- [Bleak High-Frequency Notification Issue #1386](https://github.com/hbldh/bleak/issues/1386) -- data loss at high notification rates
- [streamlit-webrtc GitHub](https://github.com/whitphx/streamlit-webrtc) -- WebRTC-based real-time video processing for Streamlit
- [Claude API Rate Limits](https://platform.claude.com/docs/en/api/rate-limits) -- token bucket algorithm, RPM/ITPM/OTPM limits
- [Claude API Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming) -- SSE streaming for progressive responses
- [Efficiently Visualizing Multiple Live Data Streams](https://discuss.streamlit.io/t/efficiently-visualizing-multiple-live-data-streams-in-streamlit/88653) -- community patterns for multi-stream dashboards
- Project codebase: `.planning/codebase/CONCERNS.md` -- pre-existing tech debt, known bugs, performance bottlenecks, fragile areas

---
*Pitfalls research for: SyncSwim Dashboard -- Streamlit real-time sports analytics with BLE sensor fusion and AI*
*Researched: 2026-03-22*
