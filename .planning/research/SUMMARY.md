# Research Summary: SyncSwim Dashboard

**Domain:** Real-time sports analytics dashboard (synchronized swimming IMU + vision sensor fusion)
**Researched:** 2026-03-22
**Overall confidence:** HIGH

## Executive Summary

The Streamlit ecosystem in early 2026 is mature enough to build the SyncSwim Dashboard without significant technical risk. Version 1.55.0 introduces dynamic containers and continues the fragment-based partial rerun model (`st.fragment(run_every=...)`) that is essential for mixing live sensor displays with static analysis views. The core challenge is not "can this be built?" but "how to structure it so Streamlit's full-page rerun model doesn't destroy performance."

Plotly 6.5.x is the clear charting choice. Its `go.Indicator` gauge mode maps directly to the FINA scoring zone displays. WebGL rendering handles the 72.5Hz IMU waveform data smoothly. Plotly 6.x's Narwhals abstraction means if the project ever moves to Polars DataFrames, charting code doesn't change. Altair and Bokeh were considered and rejected -- Altair hits row limits on time-series data, Bokeh's Streamlit integration requires a separate package.

The Anthropic Python SDK (v0.86.0) provides a clean, well-documented API for the AI coaching features. The key architectural decision is gating ALL Claude API calls behind explicit user actions (button clicks) and caching responses, because Streamlit's rerun model would otherwise trigger repeated API calls on every widget interaction. Claude Sonnet is recommended over Opus for coaching advice -- faster response time, lower cost, and coaching feedback doesn't require Opus-level reasoning.

The most critical technical risk is Python version compatibility. The existing system runs Python 3.10.16, but NumPy 2.x and SciPy 1.17 require Python 3.11+. Upgrading to Python 3.12 should be the first task before any dashboard code is written, or dependency versions must be pinned to older releases.

## Key Findings

**Stack:** Streamlit 1.55 + Plotly 6.5 + Anthropic SDK 0.86 + pandas + scipy + tslearn + scikit-learn. All Python, no JS tooling.

**Architecture:** Multipage Streamlit app with `core/` (computation) and `components/` (chart builders) separation. All expensive work behind `@st.cache_data`. Live sections use `@st.fragment(run_every=...)`.

**Critical pitfall:** Streamlit reruns the entire page on every interaction. Without disciplined caching and fragment isolation, the dashboard will be unusably slow and Claude API costs will explode.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **Foundation & Environment** -- Python upgrade + dependency setup + Streamlit skeleton + data loading layer
   - Addresses: Multipage navigation, CSV loading, session selector
   - Avoids: Python 3.10 incompatibility pitfall (blocks everything if not resolved first)

2. **Single-Athlete Analysis Views** -- Views 2 and 3 (post-set report + comparison)
   - Addresses: Joint angle gauges, scoring, radar charts, trend tracking
   - Avoids: Over-scoping to real-time before analysis works
   - Rationale: Post-recording analysis has immediate coaching value and is simpler than real-time

3. **AI Integration** -- Claude API coaching advice + AI deep analysis (View 4)
   - Addresses: Natural language feedback, pattern recognition, anomaly detection
   - Avoids: AI cost explosion pitfall (build mocking/caching infrastructure first)

4. **Real-Time Monitoring** -- View 1 (live gauges + waveforms during recording)
   - Addresses: Live IMU display, skeleton overlay, recording status
   - Avoids: Starting with the hardest UX problem; analysis views validate the data pipeline first

5. **Multi-Person Synchronization** -- View 5 (team sync + 3-person DTW)
   - Addresses: Sync heatmap, DTW matrix, AI sync report
   - Avoids: MediaPipe ID-swapping pitfall (needs its own research + tracker implementation)

**Phase ordering rationale:**
- Foundation first because Python version upgrade is a blocker
- Analysis before real-time because post-recording analysis is higher coaching value and validates the metrics pipeline
- AI integration as a separate phase because it requires prompt engineering iteration and cost management infrastructure
- Multi-person last because it depends on single-person metrics being correct and introduces the hardest technical challenge (person ID tracking)

**Research flags for phases:**
- Phase 1: Standard setup -- unlikely to need additional research
- Phase 2: Standard Plotly patterns -- unlikely to need research
- Phase 3: May need deeper research on Claude prompt engineering for sports coaching domain
- Phase 4: Needs research on Streamlit + asyncio integration for live BLE data → dashboard pipeline
- Phase 5: NEEDS deeper research on MediaPipe multi-person tracking, ID persistence, and DTW parameters for sync scoring

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI. Streamlit + Plotly is a proven combination with extensive documentation. |
| Features | HIGH | Feature set derived directly from PROJECT.md requirements. Table stakes / differentiator classification based on sports analytics dashboard conventions. |
| Architecture | HIGH | Streamlit multipage + fragment pattern is well-documented. Component/core separation is standard Python project structure. |
| Pitfalls | HIGH | Streamlit rerun model pitfalls are extensively documented in official docs and community forums. Python version issue verified against PyPI metadata. |
| AI Integration | MEDIUM | Anthropic SDK API is stable, but optimal prompt templates for sports coaching need iteration. Cost management strategy is sound but untested. |
| Multi-person Sync | MEDIUM | DTW via tslearn is well-documented. MediaPipe multi-person ID tracking is the least-researched area -- needs phase-specific deep dive. |

## Gaps to Address

- **MediaPipe multi-person tracking persistence:** How to maintain consistent person IDs across frames. Needs Phase 5 research with actual multi-person test recordings.
- **Streamlit + asyncio BLE integration:** The existing recording code uses asyncio (bleak). Streamlit runs its own event loop. How these coexist for live monitoring (Phase 4) needs investigation.
- **Claude prompt optimization:** The coaching advice prompt template is a starting point. Needs iteration with real coaching feedback to tune tone, specificity, and language.
- **Phase segmentation rules:** Defining movement phase boundaries (prep/entry/lift/display/descent) requires domain expertise from the coaching team. Signal processing can detect transitions, but thresholds need human input.
- **SciPy compatibility with Python 3.10:** If Python upgrade is blocked for any reason, need to verify exact version ceiling for scipy/numpy on Python 3.10.

## Sources

All sources documented per-file in STACK.md, ARCHITECTURE.md, FEATURES.md, and PITFALLS.md.
