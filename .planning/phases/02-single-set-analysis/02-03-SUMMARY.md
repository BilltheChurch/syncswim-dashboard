---
phase: 02-single-set-analysis
plan: 03
subsystem: recording, visualization
tags: [opencv, mediapipe, videowriter, skeleton-overlay, csv, pose-landmarks]

# Dependency graph
requires:
  - phase: 01-foundation-environment
    provides: "Project structure, .venv, dashboard skeleton, config.py"
provides:
  - "sync_recorder.py saves MP4 video (avc1 codec) alongside CSV data"
  - "sync_recorder.py saves 134-column landmarks.csv with all 33 MediaPipe landmarks"
  - "dashboard/core/landmarks.py for frame extraction, MediaPipe re-processing, landmark CSV loading"
  - "dashboard/components/skeleton_renderer.py for green/red wireframe overlay rendering"
  - "LANDMARK_NAMES constant and get_landmark_csv_header() available in both recorder and dashboard"
affects: [02-04, visual-tab-integration, training-page-report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wide-format CSV for landmark export (134 columns, 1 row per frame)"
    - "VideoWriter with avc1 fourcc for H.264 MP4 on macOS"
    - "Clean frame copy before OSD overlay for video recording"
    - "Deferred VideoWriter init (pending flag) until first frame dimensions known"
    - "st.cache_resource for MediaPipe PoseLandmarker singleton in dashboard"

key-files:
  created:
    - "dashboard/core/landmarks.py"
    - "dashboard/components/skeleton_renderer.py"
    - "tests/test_skeleton.py"
  modified:
    - "sync_recorder.py"

key-decisions:
  - "Wide-format landmarks.csv (134 columns) over long-format for pandas loading speed"
  - "Separate landmarks.csv file alongside existing vision.csv for backward compatibility"
  - "VideoWriter initialized on first recording frame (not in start_recording) to get correct frame dimensions"
  - "Clean frame copy saved before any OSD/skeleton drawing for video recording"

patterns-established:
  - "LANDMARK_NAMES duplicated in dashboard for independence from sync_recorder"
  - "Skeleton rendering via OpenCV line/circle on frame copies (not Plotly)"
  - "Deviation angle annotations with white background rectangles for readability"

requirements-completed: [ANAL-05, VIZ-03]

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 2 Plan 03: Skeleton Overlay & Video Pipeline Summary

**MP4 video recording with avc1 codec and 134-column landmarks CSV in sync_recorder, plus OpenCV skeleton overlay renderer with green/red wireframe comparison and deviation callouts**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T03:35:29Z
- **Completed:** 2026-03-23T03:39:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- sync_recorder.py now saves video.mp4 (H.264 avc1) and landmarks.csv (33 landmarks x 4 values = 134 columns) during recording alongside existing CSVs
- landmarks.py provides frame extraction, MediaPipe re-processing (IMAGE mode), and CSV loading for dashboard use
- skeleton_renderer.py draws green (template) and red (actual) wireframe overlays with deviation angle annotations at joints exceeding clean threshold
- All 8 unit tests pass covering landmark names, CSV header, pose connections, rendering outputs, and error handling

## Task Commits

Each task was committed atomically:

1. **Task 1: Modify sync_recorder.py for MP4 video and landmarks CSV** - `f461882` (feat)
2. **Task 2 RED: Failing tests for landmarks and skeleton renderer** - `36e9b66` (test)
3. **Task 2 GREEN: Implement landmarks module and skeleton renderer** - `268e32b` (feat)

## Files Created/Modified
- `sync_recorder.py` - Added LANDMARK_NAMES, get_landmark_csv_header(), VideoWriter with avc1 codec, landmarks.csv writing, clean frame recording
- `dashboard/core/landmarks.py` - Frame extraction, MediaPipe re-processing, landmark CSV loading, total frames utility
- `dashboard/components/skeleton_renderer.py` - Green/red wireframe rendering, deviation angle annotations, POSE_CONNECTIONS
- `tests/test_skeleton.py` - 8 unit tests for landmark utilities and skeleton rendering

## Decisions Made
- Wide-format landmarks.csv (134 columns, 1 row per frame) chosen over long-format for instant frame lookup via df.iloc[frame_idx]
- Separate landmarks.csv file created alongside existing vision.csv to maintain backward compatibility
- VideoWriter initialized on first recording frame via pending flag pattern since frame dimensions unknown at start_recording time
- LANDMARK_NAMES duplicated in dashboard module for independence from sync_recorder imports

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Video recording pipeline ready for use in next recording session
- landmarks.py and skeleton_renderer.py ready for Visual tab (Tab 2) integration in training page
- POSE_CONNECTIONS and rendering functions ready for keyframe comparison UI
- get_landmarker() cached via st.cache_resource for efficient re-processing

## Self-Check: PASSED

All 4 files verified present. All 3 commit hashes verified in git log.

---
*Phase: 02-single-set-analysis*
*Completed: 2026-03-23*
