# SyncSwim Dashboard — Student Development Guide

## Quick Start

### 1. Fork and Clone
```bash
# Fork this repo on GitHub, then:
git clone https://github.com/<your-username>/test_rec.git
cd test_rec
```

### 2. Environment Setup
```bash
# Install Python 3.12+ (recommended: Homebrew on macOS)
brew install python@3.12

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 3. Verify Setup
```bash
# Run tests (all should pass)
python -m pytest tests/ -v

# Launch dashboard
streamlit run dashboard/app.py
```

### 4. Keep in Sync with Coach Repo
```bash
# One-time: add coach repo as upstream
git remote add upstream https://github.com/<coach-username>/test_rec.git

# Periodically pull updates
git fetch upstream
git merge upstream/main
```

## Project Structure

```
test_rec/
├── dashboard/                 # Streamlit web application
│   ├── app.py                 # Entry point
│   ├── config.py              # Configuration management
│   ├── core/                  # Pure Python analysis logic
│   │   ├── analysis.py        # IMU signal processing
│   │   ├── angles.py          # Joint angle math
│   │   ├── data_loader.py     # CSV loading
│   │   ├── landmarks.py       # MediaPipe landmark utilities
│   │   ├── metrics.py         # Metrics orchestrator
│   │   ├── phase_detect.py    # Action phase detection
│   │   ├── scoring.py         # FINA scoring engine
│   │   └── vision_angles.py   # Vision-based angle calculations
│   ├── components/            # Plotly chart builders
│   │   ├── gauge_chart.py     # Score gauge
│   │   ├── skeleton_renderer.py # Pose skeleton overlay
│   │   ├── timeline_chart.py  # Phase timeline
│   │   └── waveform_chart.py  # IMU waveform + fusion chart
│   └── pages/                 # Dashboard pages
│       ├── training.py        # Training analysis (main page)
│       ├── analysis.py        # Progress tracking (TODO)
│       └── team.py            # Team sync (TODO)
├── config.toml                # FINA thresholds + hardware config
├── data/                      # Recorded training data
│   └── set_001_YYYYMMDD_HHMMSS/
│       ├── imu_NODE_A1.csv    # Forearm IMU data
│       ├── imu_NODE_L1.csv    # Shin IMU data
│       ├── vision.csv         # Camera angle data
│       └── landmarks.csv      # 33-point skeleton data
├── tests/                     # pytest test suite
├── task.md                    # Task tracker
├── docs/plans/                # Design documents
└── requirements.txt           # Python dependencies
```

## How to Use Cursor for Development

### Getting Started with Cursor
1. Open Cursor and open the project folder
2. Read `task.md` first — it tells you what's built and what needs to be done
3. Read the design doc in `docs/plans/` to understand architecture decisions

### Development Workflow
```
1. Pick a task from task.md
2. Write a test first (in tests/ directory)
3. Run the test to see it fail: python -m pytest tests/test_xxx.py -v
4. Ask Cursor to help implement the code
5. Run the test again to see it pass
6. Run ALL tests: python -m pytest tests/ -v
7. Commit and push
8. Update task.md
```

### Useful Cursor Prompts

**Understanding Code:**
- "Explain what dashboard/core/scoring.py does"
- "How does the IMU tilt angle get calculated?"
- "What does the phase detection algorithm do?"

**Adding Features:**
- "Help me add a new Plotly chart that shows [description]"
- "Add a new metric to the scoring engine that measures [description]"
- "Create a new Streamlit page for [description]"

**Debugging:**
- Paste the error message directly, Cursor will understand the context
- "This test is failing, help me fix it: [paste test output]"

**Data Questions:**
- "What columns does the IMU CSV have?"
- "How do I load landmarks data for frame 50?"

### Key Concepts

**IMU Data:**
- 6-axis sensor (accelerometer + gyroscope)
- Accelerometer (ax, ay, az): measures gravity direction → calculates tilt angle
- Gyroscope (gx, gy, gz): measures rotation speed → calculates smoothness

**MediaPipe Pose:**
- Detects 33 body landmarks from video
- Each landmark has x, y, z (normalized 0-1) and visibility score
- Key indices: shoulder(11/12), hip(23/24), knee(25/26), ankle(27/28)

**FINA Scoring:**
- International swimming federation scoring rules
- Deductions based on angle deviations: <15° clean, 15-30° minor, >30° major
- Per-metric thresholds in config.toml

## Hardware Setup (for data collection)

- M5StickC Plus2 x2: one on forearm (NODE_A1), one on shin (NODE_L1)
- iPhone with DroidCam app as IP camera
- Run `python sync_recorder.py` to collect synchronized data

## Git Workflow

```bash
# Create a feature branch for each task
git checkout -b feature/my-new-chart

# Work on it, commit frequently
git add <files>
git commit -m "feat: add radar comparison chart"

# Push to your fork
git push origin feature/my-new-chart

# When done, merge to your main
git checkout main
git merge feature/my-new-chart
```
