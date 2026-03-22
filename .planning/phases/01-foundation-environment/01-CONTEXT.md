# Phase 1: Foundation & Environment - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Set up the Python 3.12 environment with pinned dependencies, create the Streamlit multi-page app skeleton with 5 views grouped into 3 workflow pages, extract shared analysis code from existing scripts into a reusable library, implement CSV data loading with a sessions.json index, and create a TOML-based configuration module with in-dashboard editing. Coach/athlete view toggle in sidebar.

</domain>

<decisions>
## Implementation Decisions

### Project Structure
- Dashboard code lives in `dashboard/` subdirectory — clean separation from existing recorder/analyze scripts
- Multi-page app: `dashboard/app.py` as entry point, `dashboard/pages/` for page files
- Computation logic in `dashboard/core/`, reusable chart builders in `dashboard/components/`
- 5 views grouped into 3 Streamlit pages by workflow:
  - `pages/training.py` — Live Monitor (View 1) + Set Report (View 2)
  - `pages/analysis.py` — Progress Tracking (View 3) + AI Analysis (View 4)
  - `pages/team.py` — Team Synchronization (View 5)

### Shared Library
- Extract core math functions from `analyze.py` into a shared `core/` module: `calc_imu_tilt()`, `calc_angle()`, `smooth()`, correlation computation
- Both `analyze.py` (existing CLI) and dashboard import from the same shared module
- Existing scripts must continue working after extraction (backward compatible imports)

### Claude's Discretion — Shared Lib Scope
- Whether to also extract MjpegStreamReader and BLE protocol parsing now vs. deferring to Phase 5/6
- Claude decides based on code coupling analysis and phase dependency needs

### Python Environment
- Use `venv`: `python3.12 -m venv .venv`
- Drop `tensorflow-macos` dependency — MediaPipe 0.10.33 on Python 3.12 doesn't require it
- This unblocks numpy 2.x + latest opencv + scipy 1.17 + streamlit + plotly
- Generate `requirements.txt` with pinned versions for reproducibility

### Data Loading
- Build a `sessions.json` index file with set metadata (set#, date, time, duration, sample count, has_vision, has_imu)
- Index auto-rebuilds on dashboard startup if stale (new sets detected)
- Use pandas DataFrames for data loading — standard for Streamlit + Plotly integration
- Graceful degradation: show partial data + yellow warning badge when CSV missing/corrupted in a set directory (e.g. IMU without vision)

### Config Approach
- TOML format (`config.toml`) — Python 3.12 has built-in `tomllib`, human-readable, Streamlit ecosystem native
- Stores: FINA thresholds (angle deviation zones), hardware config (camera URL, BLE UUIDs, device names), dashboard preferences
- Dashboard settings page in sidebar — edit FINA thresholds and hardware config from within the UI
- Settings page writes back to `config.toml` so changes persist across restarts

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Core value, requirements, constraints, key decisions
- `.planning/REQUIREMENTS.md` — INFRA-01 through INFRA-06 detailed specs
- `.planning/ROADMAP.md` — Phase 1 success criteria (5 items)

### Research
- `.planning/research/STACK.md` — Streamlit 1.55, Plotly 6.5, package versions and compatibility
- `.planning/research/ARCHITECTURE.md` — Multipage app structure, st.navigation, service layer pattern
- `.planning/research/PITFALLS.md` — Dependency conflicts, session state bugs, Streamlit rerun model

### Existing Code
- `.planning/codebase/STACK.md` — Current Python 3.10 dependencies and versions
- `.planning/codebase/ARCHITECTURE.md` — Existing data flow, entry points, state management patterns
- `.planning/codebase/STRUCTURE.md` — Directory layout, file locations, naming conventions
- `.planning/codebase/CONCERNS.md` — Dependency conflicts, code duplication, hardcoded config

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `analyze.py`: `load_imu()`, `load_vision()`, `calc_imu_tilt()`, `smooth()`, `find_set_dir()` — extract to `core/data_loader.py` and `core/analysis.py`
- `sync_recorder.py` / `vision.py`: `calc_angle(shoulder, elbow, wrist)` using dot-product — extract to `core/analysis.py`
- `vision.py` / `sync_recorder.py`: `MjpegStreamReader` class — potential shared asset for Phase 5

### Established Patterns
- CSV storage in `data/set_NNN_YYYYMMDD_HHMMSS/` directories with `imu_NODE_A1.csv` and `vision.csv`
- `csv.DictReader` for loading — will be replaced by pandas in dashboard but CLI scripts keep original
- Constants hardcoded at top of each script — will be centralized to `config.toml`
- `threading.Lock` for shared state — pattern continues in dashboard for any concurrent operations

### Integration Points
- Dashboard reads from same `data/` directory that `sync_recorder.py` writes to
- `streamlit run dashboard/app.py` launched separately from recording scripts
- Shared `core/` module imported by both dashboard and existing `analyze.py`

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches within the decisions captured above.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation-environment*
*Context gathered: 2026-03-22*
