# Phase 3: Progress Tracking - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Multi-set comparison and progress tracking on the Analysis page. Coaches can view trend charts across sets, compare any two sets via radar chart, browse history in a filterable table, and export computed summaries as CSV. Date toggle switches between single-day and all-time views.

</domain>

<decisions>
## Implementation Decisions

### Trend Chart Display
- 5 small charts vertically stacked — one per metric, each with its own Y-axis scale
- Fatigue detection: both regression line (green=improving, red=declining, show slope) AND colored background zones (green/yellow/red)
- Toggle: single day vs all sets — default shows all sets chronologically, date picker filters to one day
- X-axis = set index (or date-indexed when showing all)

### Radar Chart Comparison
- 6 axes: leg_deviation, leg_height_index, shoulder_knee_alignment, smoothness, stability + overall_score
- Selection method: click 2 data points on trend chart to compare
- Default state: empty radar with instruction "请在趋势图上选择两组训练进行对比"
- Values normalized to 0-1 using MetricResult.max_value for each axis

### Claude's Discretion — Radar Position
- Whether radar appears below trend charts or in a side panel — Claude decides based on Streamlit layout constraints

### History Table Design
- Compact columns: 日期, 训练组#, 总分, 数据状态 (4 columns)
- Filter: date range only for now (action type deferred until recording pipeline tags it)
- Sortable columns via st.dataframe
- Each row clickable to navigate to that set's analysis report (training page)

### CSV Export
- Computed summaries only — one row per set: date, set#, 5 metric values, overall score, deductions
- Two export buttons: "导出全部" (all sets) + "导出筛选结果" (currently filtered sets)
- Uses st.download_button

### Analysis Page Layout
- Tabs within the Analysis page: Tab 1 = "进步追踪" (Progress — trend+radar+table+export), Tab 2 = "AI 分析" (Phase 4 placeholder)
- Within Progress tab: trend charts on top → radar chart → history table → export buttons (vertical scroll)

### Multi-Session Support
- Toggle between single day and all-time via date picker
- All-time view: X-axis = chronological set index across all days, shows long-term progress
- Single-day view: X-axis = set index within that day, shows within-session fatigue

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Core value, requirements, FINA scoring rules
- `.planning/REQUIREMENTS.md` — PROG-01~04 detailed specs
- `.planning/ROADMAP.md` — Phase 3 success criteria (4 items)

### Prior Phase Decisions
- `.planning/phases/01-foundation-environment/01-CONTEXT.md` — Project structure, data loading, config, page layout
- `.planning/phases/02-single-set-analysis/02-CONTEXT.md` — Scoring metrics, FINA display, tab layout patterns

### Research
- `.planning/research/STACK.md` — Plotly 6.5 charting patterns
- `.planning/research/FEATURES.md` — Table stakes: trend tracking, radar comparison, data export

### Existing Code
- `dashboard/core/scoring.py` — MetricResult, SetReport dataclasses (value, max_value, zone, deduction)
- `dashboard/core/metrics.py` — compute_all_metrics() orchestrator
- `dashboard/core/data_loader.py` — load_imu(), load_vision(), load_or_rebuild_index(), sessions.json
- `dashboard/components/__init__.py` — CHART_THEME constant
- `dashboard/components/gauge_chart.py` — build_gauge pattern (reference for chart builder style)
- `dashboard/pages/analysis.py` — Current placeholder page (to be replaced)
- `dashboard/config.py` — load_config() for FINA thresholds

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scoring.py` MetricResult has `.value`, `.max_value`, `.zone`, `.deduction` — perfect for radar normalization (value/max_value)
- `compute_all_metrics(set_path)` — call per set to get SetReport with all 5 metrics + overall_score
- `CHART_THEME` — consistent Plotly styling across all new charts
- `load_or_rebuild_index()` — returns sessions list with date, set_number, has_imu, has_vision metadata
- Phase 2 chart builders (gauge_chart.py, timeline_chart.py, waveform_chart.py) — established pattern: pure functions returning go.Figure, no Streamlit imports

### Established Patterns
- Chart builders are pure functions in `dashboard/components/` — no Streamlit dependency
- Computation logic in `dashboard/core/` — separated from UI
- st.tabs() for sub-page organization (Phase 2 pattern)
- session_state with namespaced keys (p2_ prefix in Phase 2)
- st.download_button for file export (Streamlit native)

### Integration Points
- `dashboard/pages/analysis.py` — replace placeholder with Progress tab + AI placeholder tab
- sessions.json index — source for history table and multi-set trend data
- compute_all_metrics() — call per set for trend/radar data (may need batch caching)
- Trend chart click → radar chart update via session_state (Plotly clickData + Streamlit)

</code_context>

<specifics>
## Specific Ideas

- Trend chart click-to-compare: Plotly's clickData event → store selected set indices in session_state → radar chart reads from session_state
- Fatigue zones: use regression slope sign to determine zone color (positive slope = green, negative = red, near-zero = yellow)
- History table row click → set session_state["selected_set"] and switch to training page for detailed analysis

</specifics>

<deferred>
## Deferred Ideas

- Action type tagging — requires recording pipeline modification, defer until that's built
- Cross-athlete comparison — belongs in Phase 6 (Team Synchronization)
- AI-generated trend analysis text — belongs in Phase 4 (AI Coaching)

</deferred>

---

*Phase: 03-progress-tracking*
*Context gathered: 2026-03-24*
