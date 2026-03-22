"""Tests for Task 1: Environment setup, directory scaffold, and requirements.txt."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_requirements_txt_exists():
    assert (PROJECT_ROOT / "requirements.txt").exists()


def test_requirements_contains_streamlit():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "streamlit==1.55.0" in content


def test_requirements_contains_numpy():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "numpy==2.2.6" in content


def test_requirements_contains_scipy():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "scipy==1.15.3" in content


def test_requirements_contains_opencv_contrib():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "opencv-contrib-python==4.10.0.84" in content


def test_requirements_no_opencv_python_standalone():
    """Ensure opencv-python (without -contrib) is not listed as a dep."""
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Lines starting with opencv-python but NOT opencv-contrib-python
        if stripped.startswith("opencv-python") and "contrib" not in stripped:
            raise AssertionError(
                f"Found 'opencv-python' without -contrib: {stripped}"
            )


def test_requirements_contains_tomli_w():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "tomli-w==1.2.0" in content


def test_requirements_contains_pytest():
    content = (PROJECT_ROOT / "requirements.txt").read_text()
    assert "pytest>=8.0" in content


def test_streamlit_config_exists():
    assert (PROJECT_ROOT / ".streamlit" / "config.toml").exists()


def test_streamlit_config_primary_color():
    content = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text()
    assert 'primaryColor = "#0068C9"' in content


def test_streamlit_config_secondary_bg():
    content = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text()
    assert 'secondaryBackgroundColor = "#F0F2F6"' in content


def test_dashboard_init_exists():
    assert (PROJECT_ROOT / "dashboard" / "__init__.py").exists()


def test_dashboard_core_init_exists():
    assert (PROJECT_ROOT / "dashboard" / "core" / "__init__.py").exists()


def test_dashboard_components_init_exists():
    assert (PROJECT_ROOT / "dashboard" / "components" / "__init__.py").exists()


def test_chart_theme_constant():
    from dashboard.components import CHART_THEME
    assert isinstance(CHART_THEME, dict)
    assert CHART_THEME["template"] == "plotly_white"


def test_chart_theme_colorway():
    from dashboard.components import CHART_THEME
    assert "#0068C9" in CHART_THEME["colorway"]


def test_imports_streamlit():
    import streamlit
    assert hasattr(streamlit, "navigation")


def test_imports_plotly():
    import plotly
    assert plotly.__version__ == "6.6.0"


def test_imports_numpy():
    import numpy
    assert numpy.__version__ == "2.2.6"


def test_imports_scipy():
    import scipy
    assert scipy.__version__ == "1.15.3"


def test_imports_mediapipe():
    import mediapipe
    assert mediapipe.__version__ == "0.10.33"


def test_imports_pandas():
    import pandas
    assert pandas.__version__ == "2.2.3"


def test_imports_tomli_w():
    import tomli_w
    assert tomli_w.__version__ == "1.2.0"
