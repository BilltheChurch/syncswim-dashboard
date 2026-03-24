# Phase 3: Progress Tracking - Research

**Researched:** 2026-03-24
**Domain:** Multi-set comparison, trend visualization, radar charts, history tables, CSV export (Streamlit + Plotly)
**Confidence:** HIGH

## Summary

Phase 3 transforms the Analysis page from a placeholder into a full progress tracking dashboard. The core challenge is computing metrics across all recorded sets (currently 7 sets across 2 dates), presenting trend charts with regression lines for fatigue detection, enabling radar chart comparison between any two sets, displaying a filterable history table, and exporting CSV summaries.

The existing codebase provides strong foundations: `compute_all_metrics(set_dir)` returns a `SetReport` per set, `load_or_rebuild_index()` provides session metadata, and Phase 2 chart builders establish a pure-function pattern in `dashboard/components/`. The primary new APIs needed are `go.Scatterpolar` for radar charts (verified working in Plotly 6.3.0), `scipy.stats.linregress` for regression trend lines (verified working in scipy 1.15.3), and Streamlit's `on_select` parameter for both `st.plotly_chart` (point selection for radar) and `st.dataframe` (row selection for navigation). All three APIs are confirmed available in the installed stack.

**Primary recommendation:** Build a `dashboard/core/progress.py` data aggregation layer that batch-computes and caches SetReports across all sets, then feed that data to four new pure-function chart builders (trend, radar, history table builder) plus a CSV export helper. The analysis page orchestrates these via `st.tabs()` with `p3_` namespaced session_state keys.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- 5 small charts vertically stacked -- one per metric, each with its own Y-axis scale
- Fatigue detection: both regression line (green=improving, red=declining, show slope) AND colored background zones (green/yellow/red)
- Toggle: single day vs all sets -- default shows all sets chronologically, date picker filters to one day
- X-axis = set index (or date-indexed when showing all)
- Radar: 6 axes: leg_deviation, leg_height_index, shoulder_knee_alignment, smoothness, stability + overall_score
- Selection method: click 2 data points on trend chart to compare
- Default state: empty radar with instruction text
- Values normalized to 0-1 using MetricResult.max_value for each axis
- Compact history table columns: date, set#, score, status (4 columns)
- Filter: date range only
- Sortable columns via st.dataframe
- Each row clickable to navigate to that set's analysis report (training page)
- CSV: Computed summaries only -- one row per set: date, set#, 5 metric values, overall score, deductions
- Two export buttons: "export all" + "export filtered"
- Uses st.download_button
- Analysis page tabs: Tab 1 = "Progress" (trend+radar+table+export), Tab 2 = "AI Analysis" (Phase 4 placeholder)
- Within Progress tab: trend charts on top -> radar chart -> history table -> export buttons (vertical scroll)
- Toggle between single day and all-time via date picker
- All-time view: X-axis = chronological set index across all days
- Single-day view: X-axis = set index within that day

### Claude's Discretion
- Whether radar appears below trend charts or in a side panel -- decide based on Streamlit layout constraints

### Deferred Ideas (OUT OF SCOPE)
- Action type tagging -- requires recording pipeline modification
- Cross-athlete comparison -- Phase 6
- AI-generated trend analysis text -- Phase 4

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROG-01 | Multi-set trend chart -- X=set number, Y=each metric, regression line for direction, fatigue flag | `scipy.stats.linregress` for regression; `go.Scatter` for data points + trend line; colored `go.layout.Shape` rects for background zones; 5 stacked subplots pattern |
| PROG-02 | Radar chart comparison -- select 2 sets, overlay 6-axis spider chart | `go.Scatterpolar` with `fill='toself'` for two overlaid traces; `st.plotly_chart(on_select="rerun")` for point click capture; `MetricResult.max_value` normalization |
| PROG-03 | History table with filter -- by date; sortable columns | `st.dataframe(on_select="rerun", selection_mode="single-row")` for clickable rows; `st.date_input` for date range filter; column_config for formatting |
| PROG-04 | CSV export -- download button for computed summary per set | `st.download_button` with `df.to_csv().encode('utf-8')`; two buttons for all vs filtered; `@st.cache_data` for conversion |

</phase_requirements>

## Standard Stack

### Core (Already Installed -- Verified)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Plotly | 6.3.0 | Trend charts (`go.Scatter`), radar (`go.Scatterpolar`), background shapes | Already used for all Phase 2 charts; `go.Scatterpolar` verified working |
| Streamlit | 1.49.1 | `st.plotly_chart(on_select=)`, `st.dataframe(on_select=)`, `st.download_button`, `st.tabs` | Already installed; `on_select` parameter confirmed in both plotly_chart and dataframe |
| scipy | 1.15.3 | `scipy.stats.linregress` for regression lines | Already installed; returns slope, intercept, rvalue -- exactly what we need for trend direction |
| pandas | 2.2.3 | DataFrame for history table, CSV export via `to_csv()` | Already used throughout project |
| numpy | 1.26.4 | Array math for normalization, metric aggregation | Already used throughout project |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dashboard.core.scoring` | (internal) | `MetricResult`, `SetReport` dataclasses | Source of all metric data; `.value`, `.max_value`, `.zone`, `.deduction` fields |
| `dashboard.core.metrics` | (internal) | `compute_all_metrics(set_dir)` | Per-set computation entry point; returns `SetReport` or `None` |
| `dashboard.core.data_loader` | (internal) | `load_or_rebuild_index()` | Session metadata with date, set_number, has_imu, has_vision |
| `dashboard.components` | (internal) | `CHART_THEME` | Consistent styling for all new charts |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `scipy.stats.linregress` | `numpy.polyfit(x, y, 1)` | polyfit works but linregress also returns r-value and p-value useful for fatigue significance |
| `st.plotly_chart(on_select=)` | `streamlit-plotly-events` (3rd party) | Third-party adds dependency; native `on_select` is sufficient for point selection |
| `st.dataframe` | `st.data_editor` | data_editor allows editing; dataframe is read-only which is correct here |

**Installation:** No new packages needed. All dependencies are already installed.

## Architecture Patterns

### Recommended Project Structure

```
dashboard/
  core/
    progress.py          # NEW: batch compute + cache SetReports across sets
  components/
    trend_chart.py       # NEW: 5 individual trend chart builders
    radar_chart.py       # NEW: radar chart builder (6-axis Scatterpolar)
  pages/
    analysis.py          # REPLACE: placeholder -> Progress tab + AI placeholder tab
```

### Pattern 1: Progress Data Aggregation Layer

**What:** A `progress.py` module in `dashboard/core/` that batch-computes `SetReport` for every set and returns a structured summary DataFrame.
**When to use:** Called once when the analysis page loads; cached in session_state.
**Why:** `compute_all_metrics()` is per-set (~0.1s per set). With 7 sets currently (could grow to 50+), calling it sequentially is fine now but caching prevents recomputation on every Streamlit rerun.

```python
# Source: project pattern from dashboard/core/metrics.py
from dataclasses import dataclass
import pandas as pd
from dashboard.core.metrics import compute_all_metrics
from dashboard.core.data_loader import load_or_rebuild_index
from dashboard.core.scoring import SetReport

@dataclass
class ProgressData:
    """Aggregated data for all sets, ready for charting."""
    summary_df: pd.DataFrame       # One row per set: date, set#, 5 metrics, score, deductions
    reports: dict[str, SetReport]   # set_name -> SetReport mapping
    set_names: list[str]            # Ordered set names for X-axis indexing

def compute_progress_data(data_dir: str = "data") -> ProgressData:
    """Batch compute all sets and return aggregated progress data."""
    sessions = load_or_rebuild_index(data_dir)
    rows = []
    reports = {}
    set_names = []

    for session in sessions:
        report = compute_all_metrics(session["path"])
        if report is None:
            continue

        set_names.append(session["name"])
        reports[session["name"]] = report

        # Build summary row
        row = {
            "name": session["name"],
            "date": session["date"],
            "time": session["time"],
            "set_number": session["set_number"],
            "overall_score": report.overall_score,
            "has_imu": session["has_imu"],
            "has_vision": session["has_vision"],
        }
        # Add per-metric values and deductions
        for m in report.metrics:
            row[m.name] = m.value
            row[f"{m.name}_deduction"] = m.deduction
            row[f"{m.name}_zone"] = m.zone
            row[f"{m.name}_max"] = m.max_value

        rows.append(row)

    summary_df = pd.DataFrame(rows)
    return ProgressData(summary_df=summary_df, reports=reports, set_names=set_names)
```

### Pattern 2: Pure Function Chart Builders (Established Pattern)

**What:** Each chart builder is a pure function in `dashboard/components/` that takes data and returns `go.Figure`. No Streamlit imports.
**When to use:** Always -- this is the established project pattern from Phase 2.
**Example:**

```python
# Source: established pattern from dashboard/components/gauge_chart.py
import plotly.graph_objects as go
from scipy.stats import linregress
import numpy as np
from dashboard.components import CHART_THEME

def build_trend_chart(
    set_indices: np.ndarray,
    values: np.ndarray,
    metric_name: str,
    y_label: str,
) -> go.Figure:
    """Build a single metric trend chart with regression line and background zones."""
    fig = go.Figure()

    # Data points
    fig.add_trace(go.Scatter(
        x=set_indices, y=values,
        mode="markers+lines",
        name=metric_name,
        line={"color": "#0068C9", "width": 2},
        marker={"size": 8},
    ))

    # Regression line
    if len(set_indices) >= 2:
        result = linregress(set_indices, values)
        trend_y = result.intercept + result.slope * set_indices
        trend_color = "#09AB3B" if result.slope <= 0 else "#FF4B4B"  # Lower = better for most metrics
        fig.add_trace(go.Scatter(
            x=set_indices, y=trend_y,
            mode="lines",
            name=f"趋势 (斜率: {result.slope:.3f})",
            line={"color": trend_color, "width": 2, "dash": "dash"},
        ))

    fig.update_layout(
        height=200,
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
        # ... standard theme application
    )
    return fig
```

### Pattern 3: Radar Chart with Normalized Values

**What:** `go.Scatterpolar` with 6 axes, values normalized to 0-1 range using `max_value`.
**When to use:** When user has selected exactly 2 sets from trend chart.

```python
# Source: verified with Plotly 6.3.0 go.Scatterpolar
def build_radar_chart(
    metrics_a: list,  # List of MetricResult from set A
    score_a: float,
    label_a: str,
    metrics_b: list,  # List of MetricResult from set B
    score_b: float,
    label_b: str,
) -> go.Figure:
    """Build 6-axis radar chart comparing two sets."""
    categories = ["腿部偏差", "腿高指数", "肩膝对齐", "流畅度", "稳定性", "总分"]

    # Normalize to 0-1 using max_value
    def normalize(metrics, score):
        vals = []
        for m in metrics:
            vals.append(m.value / m.max_value if m.max_value > 0 else 0)
        vals.append(score / 10.0)  # overall_score out of 10
        return vals

    r_a = normalize(metrics_a, score_a)
    r_b = normalize(metrics_b, score_b)

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=r_a + [r_a[0]],  # Close the polygon
        theta=categories + [categories[0]],
        fill='toself', name=label_a,
        fillcolor='rgba(0,104,201,0.2)',
        line={"color": "#0068C9"},
    ))
    fig.add_trace(go.Scatterpolar(
        r=r_b + [r_b[0]],
        theta=categories + [categories[0]],
        fill='toself', name=label_b,
        fillcolor='rgba(255,75,75,0.2)',
        line={"color": "#FF4B4B"},
    ))
    fig.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 1]}},
        height=400,
    )
    return fig
```

### Pattern 4: Session State for Cross-Chart Interaction

**What:** Use `p3_` namespaced session_state keys to pass selected set indices from trend chart clicks to radar chart.
**When to use:** Trend chart point selection -> radar chart update.

```python
# Source: established pattern from Phase 2 (p2_ prefix)
# In analysis page:
if "p3_selected_sets" not in st.session_state:
    st.session_state.p3_selected_sets = []  # Max 2 entries

# Trend chart with on_select
event = st.plotly_chart(fig, key="p3_trend_leg_dev", on_select="rerun", selection_mode="points")

# Read selection
if event and event.selection.points:
    point = event.selection.points[0]
    point_index = point["point_index"]
    # Add to selected sets (max 2)
    selected = st.session_state.p3_selected_sets
    if point_index not in selected:
        selected.append(point_index)
        if len(selected) > 2:
            selected.pop(0)  # FIFO: drop oldest
        st.session_state.p3_selected_sets = selected
```

### Pattern 5: Date Toggle for Single-Day vs All-Time

**What:** `st.date_input` controls whether trend shows one day or all sets.
**When to use:** Top of Progress tab, filtering the summary DataFrame.

```python
# Date toggle implementation pattern
all_dates = sorted(summary_df["date"].unique())
use_all = st.toggle("显示全部训练", value=True, key="p3_show_all")
if not use_all:
    selected_date = st.date_input("选择日期", key="p3_date_filter")
    filtered_df = summary_df[summary_df["date"] == str(selected_date)]
else:
    filtered_df = summary_df
```

### Anti-Patterns to Avoid

- **Recomputing metrics on every rerun:** Cache the batch `ProgressData` in `session_state` with a cache key based on sessions.json mtime. Never call `compute_all_metrics()` inside a loop on every Streamlit rerun.
- **Importing Streamlit in chart builders:** Follow established pattern -- chart builders in `components/` are pure functions returning `go.Figure`. All `st.*` calls live in `pages/analysis.py`.
- **Using `st.data_editor` for history table:** The history table is read-only. Use `st.dataframe` with `on_select` for row click navigation.
- **Single large subplot for 5 trends:** User decided 5 separate small charts stacked vertically, not one combined chart. Each metric has its own Y-axis scale.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Linear regression | Manual slope calculation | `scipy.stats.linregress` | Returns slope, intercept, r-value, p-value, stderr in one call |
| Radar chart normalization | Custom scaling logic | `MetricResult.max_value` division | Already available in dataclass; consistent with FINA scoring |
| CSV byte encoding | Manual string encoding | `df.to_csv(index=False).encode('utf-8')` | Pandas handles proper CSV escaping, encoding, BOM for Chinese characters |
| Sortable table | Custom sort buttons | `st.dataframe` built-in sorting | Native column header sort -- automatic, no code needed |
| Point click handling | JavaScript/postMessage | `st.plotly_chart(on_select="rerun")` | Native Streamlit; returns `selection.points` with `point_index` |
| Row click handling | Checkbox column hack | `st.dataframe(on_select="rerun", selection_mode="single-row")` | Native row selection; returns `selection.rows` with positional indices |

**Key insight:** Streamlit 1.49.1 has native `on_select` support for both `st.plotly_chart` and `st.dataframe`, eliminating the need for third-party event handling libraries. This was added in Streamlit 1.35.0+.

## Common Pitfalls

### Pitfall 1: Sorting Resets Row Selection in st.dataframe

**What goes wrong:** User selects a row in the history table, then sorts by a column -- the selection is lost.
**Why it happens:** Streamlit documents that "If a user sorts a dataframe, row selections will be reset."
**How to avoid:** Store the selected set's `name` (unique identifier) in session_state, not the row index. After sorting, the name persists even if the positional index changes.
**Warning signs:** Row click navigation stops working after user sorts columns.

### Pitfall 2: Metric Ordering Inconsistency Across Sets

**What goes wrong:** IMU-only sets have 3 metrics (leg_deviation, smoothness, stability), vision-only sets have 2 metrics (leg_height_index, shoulder_knee_alignment). Full sets have 5. Radar chart expects exactly 6 axes.
**Why it happens:** `compute_set_report()` conditionally adds metrics based on data availability.
**How to avoid:** In the progress aggregation layer, always produce 5 metric columns + overall_score. Fill missing metrics with `NaN` or `0.0`. The radar chart must handle missing axes gracefully (display 0 for unavailable metrics).
**Warning signs:** KeyError when accessing metric by name; radar chart has fewer than 6 points.

### Pitfall 3: Empty Selection State on First Load

**What goes wrong:** Radar chart crashes because `p3_selected_sets` is empty or has only 1 entry.
**Why it happens:** User hasn't clicked any trend chart points yet.
**How to avoid:** Show instruction text ("click 2 data points on trend chart to compare") when fewer than 2 sets selected. Never call `build_radar_chart()` with incomplete data.
**Warning signs:** IndexError on first page load.

### Pitfall 4: on_select Returns Curve Number, Not Data Index

**What goes wrong:** When trend chart has both data trace and regression line trace, clicking the regression line returns `curve_number=1` which maps to the wrong trace.
**Why it happens:** `on_select` returns `curve_number` for which trace was clicked, and `point_index` for the point within that trace.
**How to avoid:** Only process clicks where `curve_number == 0` (the data trace). Ignore clicks on the regression line (curve 1).
**Warning signs:** Clicking regression line selects wrong set or crashes.

### Pitfall 5: Date String Format Mismatch

**What goes wrong:** `st.date_input` returns `datetime.date` object, but sessions.json stores dates as strings like "2026-03-19".
**Why it happens:** Type mismatch between Streamlit widget and data source.
**How to avoid:** Convert `st.date_input` result to string with `str(selected_date)` before filtering. The sessions.json format is "YYYY-MM-DD" which matches Python's `str(datetime.date)`.
**Warning signs:** Date filter shows no results even when data exists.

### Pitfall 6: CSV Export with Chinese Characters

**What goes wrong:** Downloaded CSV shows garbled Chinese characters when opened in Excel.
**Why it happens:** Excel defaults to ANSI encoding, not UTF-8.
**How to avoid:** Use `df.to_csv(index=False).encode('utf-8-sig')` -- the BOM (Byte Order Mark) from `utf-8-sig` tells Excel to use UTF-8 decoding.
**Warning signs:** CSV column headers or status text display as garbled characters in Excel on Windows/Mac.

## Code Examples

### Trend Chart with Regression Line and Background Zones

```python
# Source: verified with Plotly 6.3.0 + scipy 1.15.3
import plotly.graph_objects as go
from scipy.stats import linregress
import numpy as np
from dashboard.components import CHART_THEME

def build_trend_chart(
    set_indices: np.ndarray,
    values: np.ndarray,
    metric_name: str,
    y_label: str,
    lower_is_better: bool = True,
) -> go.Figure:
    """Build one metric trend chart with regression + fatigue zones.

    Args:
        set_indices: X-axis values (0..N).
        values: Metric values per set.
        metric_name: Display name for title.
        y_label: Y-axis label.
        lower_is_better: If True, negative slope = green (improving).

    Returns:
        Plotly Figure.
    """
    fig = go.Figure()

    # Data points (scatter + line)
    fig.add_trace(go.Scatter(
        x=set_indices, y=values,
        mode="markers+lines",
        name=metric_name,
        line={"color": CHART_THEME["colorway"][0], "width": 2},
        marker={"size": 8},
    ))

    # Regression line + fatigue zone
    if len(set_indices) >= 2:
        res = linregress(set_indices.astype(float), values.astype(float))
        trend_y = res.intercept + res.slope * set_indices.astype(float)

        improving = (res.slope < 0) if lower_is_better else (res.slope > 0)
        trend_color = "#09AB3B" if improving else "#FF4B4B"
        zone_color = "rgba(9,171,59,0.1)" if improving else "rgba(255,75,75,0.1)"

        fig.add_trace(go.Scatter(
            x=set_indices, y=trend_y,
            mode="lines",
            name=f"趋势 ({res.slope:+.3f})",
            line={"color": trend_color, "width": 2, "dash": "dash"},
        ))

        # Background zone (colored rectangle)
        fig.add_shape(
            type="rect",
            x0=set_indices[0], x1=set_indices[-1],
            y0=min(values.min(), trend_y.min()) * 0.9,
            y1=max(values.max(), trend_y.max()) * 1.1,
            fillcolor=zone_color,
            line={"width": 0},
            layer="below",
        )

    fig.update_layout(
        title={"text": metric_name, "font_size": 14},
        height=180,
        xaxis_title="训练组",
        yaxis_title=y_label,
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "font_size": 10},
        margin={"l": 48, "r": 16, "t": 36, "b": 32},
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
        font_color=CHART_THEME["font_color"],
        paper_bgcolor=CHART_THEME["paper_bgcolor"],
        plot_bgcolor=CHART_THEME["plot_bgcolor"],
    )

    return fig
```

### Radar Chart for Two-Set Comparison

```python
# Source: verified with Plotly 6.3.0 go.Scatterpolar
import plotly.graph_objects as go
from dashboard.components import CHART_THEME
from dashboard.core.scoring import MetricResult

RADAR_CATEGORIES = ["腿部偏差", "腿高指数", "肩膝对齐", "流畅度", "稳定性", "总分"]
METRIC_ORDER = ["leg_deviation", "leg_height_index", "shoulder_knee_alignment",
                "smoothness", "stability"]

def normalize_for_radar(metrics: list[MetricResult], overall_score: float) -> list[float]:
    """Normalize metrics to 0-1 for radar chart axes."""
    metric_map = {m.name: m for m in metrics}
    values = []
    for name in METRIC_ORDER:
        if name in metric_map:
            m = metric_map[name]
            values.append(m.value / m.max_value if m.max_value > 0 else 0.0)
        else:
            values.append(0.0)
    values.append(overall_score / 10.0)
    return values

def build_radar_comparison(
    r_a: list[float], label_a: str,
    r_b: list[float], label_b: str,
) -> go.Figure:
    """Build overlaid 6-axis radar chart comparing two sets."""
    cats = RADAR_CATEGORIES + [RADAR_CATEGORIES[0]]  # Close polygon

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=r_a + [r_a[0]], theta=cats,
        fill='toself', name=label_a,
        fillcolor='rgba(0,104,201,0.15)',
        line={"color": "#0068C9", "width": 2},
    ))
    fig.add_trace(go.Scatterpolar(
        r=r_b + [r_b[0]], theta=cats,
        fill='toself', name=label_b,
        fillcolor='rgba(255,75,75,0.15)',
        line={"color": "#FF4B4B", "width": 2},
    ))

    fig.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 1], "tickfont_size": 10}},
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.15},
        height=400,
        margin={"l": 60, "r": 60, "t": 40, "b": 60},
        template=CHART_THEME["template"],
        font_family=CHART_THEME["font_family"],
    )
    return fig
```

### CSV Export with Chinese Character Support

```python
# Source: Streamlit docs st.download_button + pandas to_csv
import streamlit as st
import pandas as pd

def render_export_buttons(all_df: pd.DataFrame, filtered_df: pd.DataFrame):
    """Render two CSV export download buttons."""
    col1, col2 = st.columns(2)

    with col1:
        csv_all = all_df.to_csv(index=False).encode('utf-8-sig')  # BOM for Excel
        st.download_button(
            label="导出全部",
            data=csv_all,
            file_name="training_summary_all.csv",
            mime="text/csv",
            key="p3_export_all",
        )

    with col2:
        csv_filtered = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="导出筛选结果",
            data=csv_filtered,
            file_name="training_summary_filtered.csv",
            mime="text/csv",
            key="p3_export_filtered",
        )
```

### History Table with Row Selection

```python
# Source: Streamlit 1.49.1 st.dataframe on_select verified
import streamlit as st

def render_history_table(display_df: pd.DataFrame) -> str | None:
    """Render filterable history table, return selected set name or None."""
    event = st.dataframe(
        display_df,
        column_config={
            "日期": st.column_config.TextColumn("日期", width="medium"),
            "训练组#": st.column_config.NumberColumn("训练组#", width="small"),
            "总分": st.column_config.NumberColumn("总分", format="%.1f", width="small"),
            "数据状态": st.column_config.TextColumn("数据状态", width="medium"),
        },
        column_order=["日期", "训练组#", "总分", "数据状态"],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="p3_history_table",
    )

    if event.selection.rows:
        row_idx = event.selection.rows[0]
        return display_df.iloc[row_idx]["name"]  # Return set name for navigation
    return None
```

### Plotly Chart Point Selection for Radar

```python
# Source: Streamlit 1.49.1 st.plotly_chart on_select verified
import streamlit as st

# Render trend chart with selection enabled
event = st.plotly_chart(
    fig,
    key=f"p3_trend_{metric_name}",
    on_select="rerun",
    selection_mode="points",
    use_container_width=True,
)

# Process selection (only from data trace, not regression line)
if event and event.selection and event.selection.points:
    for pt in event.selection.points:
        if pt.get("curve_number", 0) == 0:  # Data trace only
            idx = pt["point_index"]
            # Store in session state
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `streamlit-plotly-events` 3rd party | `st.plotly_chart(on_select=)` native | Streamlit 1.35.0 (2024) | No external dependency needed for click events |
| Checkbox column for row selection | `st.dataframe(on_select=)` native | Streamlit 1.35.0 (2024) | Clean row selection without hacks |
| Manual CSV string building | `df.to_csv().encode('utf-8-sig')` | Always available | BOM encoding for Excel Chinese character support |

**Deprecated/outdated:**
- `streamlit-plotly-events` package: replaced by native `on_select` parameter
- `st.experimental_data_editor`: replaced by `st.data_editor` (but we use `st.dataframe` here)

## Open Questions

1. **Radar chart position: below trends or side panel?**
   - What we know: Streamlit's column layout can create a side panel, but the Progress tab already has trend charts + table + export. Vertical space is the primary constraint.
   - Recommendation: Place radar BELOW trend charts in the main column. Streamlit's single-column default flow is simpler and avoids responsive layout issues. A side panel with `st.columns([2, 1])` would compress the trend charts too much on narrow screens. Vertical scroll is acceptable for a coach workflow.

2. **Trend slope direction semantics per metric**
   - What we know: For `leg_deviation`, `smoothness`, and `stability`, lower values = better (negative slope = improving). For `leg_height_index` and `shoulder_knee_alignment`, interpretation is less clear since they use proxy metrics in Phase 2.
   - Recommendation: Add a `lower_is_better` flag per metric. Default `True` for all deviation/jerk/stability metrics. For height_index and alignment proxies, set `False` (higher angle_deg = more visible leg = better). This can be refined when proxy metrics are replaced with real landmark-based computation.

3. **Batch computation performance with 50+ sets**
   - What we know: Current data has 7 sets. `compute_all_metrics` takes ~0.1s per set. At 50 sets = ~5s which is noticeable.
   - Recommendation: Cache in `session_state` with a key based on `len(sessions)`. Only recompute when sessions list changes. For Phase 3 scope, sequential computation is sufficient. Parallel processing deferred to when dataset grows.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already configured) |
| Config file | pyproject.toml or pytest default discovery |
| Quick run command | `python3 -m pytest tests/ -x -q` |
| Full suite command | `python3 -m pytest tests/ -v` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROG-01a | build_trend_chart returns go.Figure with data + regression traces | unit | `python3 -m pytest tests/test_progress_charts.py::TestBuildTrendChart -x` | Wave 0 |
| PROG-01b | Regression line color green when improving, red when declining | unit | `python3 -m pytest tests/test_progress_charts.py::TestBuildTrendChart::test_regression_color -x` | Wave 0 |
| PROG-01c | compute_progress_data returns ProgressData with summary_df | unit | `python3 -m pytest tests/test_progress_data.py::TestComputeProgressData -x` | Wave 0 |
| PROG-02a | build_radar_comparison returns go.Figure with 2 Scatterpolar traces | unit | `python3 -m pytest tests/test_progress_charts.py::TestBuildRadarChart -x` | Wave 0 |
| PROG-02b | normalize_for_radar handles missing metrics (returns 0.0) | unit | `python3 -m pytest tests/test_progress_charts.py::TestNormalizeForRadar -x` | Wave 0 |
| PROG-03a | History table DataFrame has 4 display columns | unit | `python3 -m pytest tests/test_progress_data.py::TestHistoryTable -x` | Wave 0 |
| PROG-04a | CSV export produces valid UTF-8-sig bytes with correct columns | unit | `python3 -m pytest tests/test_progress_data.py::TestCsvExport -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m pytest tests/test_progress_charts.py tests/test_progress_data.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_progress_charts.py` -- covers PROG-01 (trend chart builders) and PROG-02 (radar chart builder)
- [ ] `tests/test_progress_data.py` -- covers PROG-01 (progress data aggregation), PROG-03 (history table format), PROG-04 (CSV export)
- Framework install: not needed -- pytest already installed and 93 tests pass

## Sources

### Primary (HIGH confidence)

- Plotly 6.3.0 installed -- `go.Scatterpolar` verified working locally with `fill='toself'` and dual traces
- Streamlit 1.49.1 installed -- `on_select` parameter confirmed via `inspect.signature()` on both `st.plotly_chart` and `st.dataframe`
- scipy 1.15.3 installed -- `scipy.stats.linregress` verified returning slope, intercept, rvalue
- [Streamlit st.plotly_chart docs](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart) -- on_select API, selection_mode options, returned object structure
- [Streamlit st.dataframe docs](https://docs.streamlit.io/develop/api-reference/data/st.dataframe) -- on_select, selection_mode, column_config, sorting behavior
- [Streamlit dataframe row selections tutorial](https://docs.streamlit.io/develop/tutorials/elements/dataframe-row-selections) -- complete code pattern
- [Plotly radar chart docs](https://plotly.com/python/radar-chart/) -- go.Scatterpolar examples with multiple traces
- [scipy.stats.linregress docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.linregress.html) -- return values and usage

### Secondary (MEDIUM confidence)

- [Streamlit st.download_button docs](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button) -- CSV download pattern
- [Streamlit CSV export FAQ](https://docs.streamlit.io/knowledge-base/using-streamlit/how-download-pandas-dataframe-csv) -- `to_csv().encode('utf-8')` pattern

### Tertiary (LOW confidence)

- None -- all findings verified against installed packages or official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages already installed and verified working
- Architecture: HIGH -- extends established Phase 2 patterns (pure chart builders, core computation layer, session_state namespacing)
- Pitfalls: HIGH -- sorting reset, metric ordering, empty state, curve_number filtering all verified against official Streamlit docs
- Radar chart position: MEDIUM -- recommendation based on Streamlit layout constraints, but could be adjusted during implementation

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable -- all APIs are established, no fast-moving dependencies)
