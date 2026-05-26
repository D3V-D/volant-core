"""Volant - Streamlit dashboard for multi-fly speed analysis."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from scipy.signal import welch

ROOT = Path(__file__).parent
ICON_PATH = ROOT / "static" / "fly.ico"

st.set_page_config(
    page_title="Volant",
    page_icon=str(ICON_PATH) if ICON_PATH.exists() else None,
    layout="wide",
)

EXPECTED_COLUMNS = [
    "frame", "time_s", "x_px", "y_px", "x_mm", "y_mm",
    "zone", "speed_mm_s", "dist_from_centre_mm", "confidence", "detected",
]


@st.cache_data(show_spinner=False)
def load_csv(file_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(BytesIO(file_bytes))


def make_demo_fly(seed: int, fly_id: str, n: int = 9_000, fps: int = 50) -> pd.DataFrame:
    """Synthesize one demo fly stream that matches expected tracking columns."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fps

    theta = np.cumsum(rng.normal(0, 0.18, size=n))
    step = np.clip(rng.normal(0.22, 0.12, size=n), 0.01, None)
    x = np.cumsum(step * np.cos(theta))
    y = np.cumsum(step * np.sin(theta))
    x = np.clip(x, -15.0, 15.0)
    y = np.clip(y, -15.0, 15.0)

    speed = np.sqrt(np.diff(x, prepend=x[0]) ** 2 + np.diff(y, prepend=y[0]) ** 2) * fps
    dist = np.sqrt(x ** 2 + y ** 2)

    return pd.DataFrame(
        {
            "fly_id": fly_id,
            "frame": np.arange(n),
            "time_s": t,
            "x_mm": x,
            "y_mm": y,
            "speed_mm_s": speed,
            "dist_from_centre_mm": dist,
            "zone": np.where(dist < 7.5, "Centre", "Periphery"),
            "confidence": rng.uniform(0.75, 0.99, size=n),
            "detected": True,
        }
    )


def coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required analysis columns exist."""
    out = df.copy()
    if "time_s" not in out and "frame" in out:
        out["time_s"] = out["frame"] / 50.0
    if "speed_mm_s" not in out and {"x_mm", "y_mm"}.issubset(out.columns):
        dx = out["x_mm"].diff().fillna(0.0)
        dy = out["y_mm"].diff().fillna(0.0)
        dt = out["time_s"].diff().replace(0, np.nan).fillna(0.02)
        out["speed_mm_s"] = np.sqrt(dx**2 + dy**2) / dt
    if "dist_from_centre_mm" not in out and {"x_mm", "y_mm"}.issubset(out.columns):
        out["dist_from_centre_mm"] = np.sqrt(out["x_mm"] ** 2 + out["y_mm"] ** 2)
    if "zone" not in out and "dist_from_centre_mm" in out:
        radius = float(out["dist_from_centre_mm"].max() or 1.0)
        out["zone"] = np.where(out["dist_from_centre_mm"] < radius * 0.5, "Centre", "Periphery")
    return out


def prepare_fly_df(df: pd.DataFrame, fly_id: str, confidence_min: float) -> pd.DataFrame:
    out = coerce_schema(df)
    if "time_s" not in out or "speed_mm_s" not in out:
        raise ValueError("CSV missing required columns: need time_s/frame and speed_mm_s or x_mm/y_mm")
    out = out.sort_values("time_s").reset_index(drop=True)
    if "confidence" in out:
        out = out[out["confidence"] >= confidence_min]
    out = out[np.isfinite(out["time_s"]) & np.isfinite(out["speed_mm_s"])]
    out = out.assign(fly_id=fly_id)
    return out


def as_second_resolution(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["second"] = np.floor(out["time_s"]).astype(int)
    group_cols = ["fly_id", "second"]
    if "group" in out.columns:
        group_cols = ["group", "fly_id", "second"]
    return (
        out.groupby(group_cols, as_index=False)
        .agg(speed_mm_s=("speed_mm_s", "mean"))
        .sort_values(group_cols)
    )


def downsample_per_group(df: pd.DataFrame, group_col: str, max_points: int) -> pd.DataFrame:
    """Keep rendering responsive by capping points per group."""
    if max_points <= 0 or len(df) <= max_points:
        return df
    pieces: list[pd.DataFrame] = []
    for _, part in df.groupby(group_col, sort=False):
        if len(part) <= max_points:
            pieces.append(part)
            continue
        idx = np.linspace(0, len(part) - 1, num=max_points, dtype=int)
        pieces.append(part.iloc[idx])
    return pd.concat(pieces, ignore_index=True)


def add_moving_average(one_sec: pd.DataFrame) -> pd.DataFrame:
    out = one_sec.copy()
    out["speed_ma_5s"] = (
        out.groupby("fly_id")["speed_mm_s"]
        .transform(lambda s: s.rolling(5, min_periods=1).mean())
    )
    return out


def cumulative_average_speed_df(df: pd.DataFrame, mode: Literal["seconds", "frames"]) -> tuple[pd.DataFrame, str, str]:
    """Return per-fly cumulative mean speed using either second or frame axis."""
    if mode == "frames" and "frame" in df.columns:
        out = (
            df[["group", "fly_id", "frame", "speed_mm_s"]]
            .dropna(subset=["group", "frame", "speed_mm_s"])
            .sort_values(["group", "fly_id", "frame"])
            .copy()
        )
        out["cum_avg_speed_mm_s"] = out.groupby("fly_id")["speed_mm_s"].transform(lambda s: s.expanding().mean())
        return out, "frame", "Frame"

    one_sec = as_second_resolution(df)
    out = one_sec.sort_values(["fly_id", "second"]).copy()
    out["cum_avg_speed_mm_s"] = out.groupby("fly_id")["speed_mm_s"].transform(lambda s: s.expanding().mean())
    return out, "second", "Time (s)"


def sixty_second_stats(one_sec: pd.DataFrame) -> pd.DataFrame:
    out = one_sec.copy()
    out["window_60s"] = (out["second"] // 60) * 60
    grouped = out.groupby(["fly_id", "window_60s"])["speed_mm_s"]
    stats = grouped.agg(
        peak_speed_mm_s="max",
        rms_speed_mm_s=lambda s: float(np.sqrt(np.mean(np.square(s)))),
        mean_speed_mm_s="mean",
        std_speed_mm_s="std",
    ).reset_index()
    stats["cv_60s"] = stats["std_speed_mm_s"] / stats["mean_speed_mm_s"].replace(0, np.nan)
    return stats


def average_speed_series(one_sec: pd.DataFrame) -> pd.Series:
    series = one_sec.groupby("second")["speed_mm_s"].mean().sort_index()
    full_idx = np.arange(int(series.index.min()), int(series.index.max()) + 1)
    return series.reindex(full_idx).interpolate().bfill().ffill()


def welch_psd_df(avg_speed: pd.Series) -> pd.DataFrame:
    values = avg_speed.to_numpy()
    if len(values) < 8:
        return pd.DataFrame({"frequency_hz": [], "power": []})
    nperseg = min(256, len(values))
    freq, power = welch(values, fs=1.0, nperseg=nperseg)
    return pd.DataFrame({"frequency_hz": freq, "power": power})


def autocorrelation_df(avg_speed: pd.Series, max_lag: int = 300) -> pd.DataFrame:
    values = avg_speed.to_numpy()
    values = values - values.mean()
    if len(values) < 3:
        return pd.DataFrame({"lag_s": [], "autocorrelation": []})
    full = np.correlate(values, values, mode="full")
    acf = full[full.size // 2:]
    acf = acf / acf[0]
    limit = min(max_lag, len(acf) - 1)
    lags = np.arange(limit + 1)
    return pd.DataFrame({"lag_s": lags, "autocorrelation": acf[: limit + 1]})


def _series_from_seconds(df: pd.DataFrame) -> pd.Series:
    """Build a 1Hz time series of mean speed across the provided rows."""
    series = df.groupby("second")["speed_mm_s"].mean().sort_index()
    if series.empty:
        return series
    full_idx = np.arange(int(series.index.min()), int(series.index.max()) + 1)
    return series.reindex(full_idx).interpolate().bfill().ffill()


def psd_by_key_df(one_sec_df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Welch PSD computed per `key` (e.g. 'fly_id' or 'group')."""
    pieces: list[pd.DataFrame] = []
    for key_value, part in one_sec_df.groupby(key):
        series = _series_from_seconds(part)
        psd_part = welch_psd_df(series)
        if psd_part.empty:
            continue
        psd_part[key] = key_value
        pieces.append(psd_part)
    if not pieces:
        return pd.DataFrame({"frequency_hz": [], "power": [], key: []})
    return pd.concat(pieces, ignore_index=True)


def autocorrelation_by_key_df(one_sec_df: pd.DataFrame, key: str, max_lag: int = 300) -> pd.DataFrame:
    """Autocorrelation of average speed computed per `key`."""
    pieces: list[pd.DataFrame] = []
    for key_value, part in one_sec_df.groupby(key):
        series = _series_from_seconds(part)
        acf_part = autocorrelation_df(series, max_lag=max_lag)
        if acf_part.empty:
            continue
        acf_part[key] = key_value
        pieces.append(acf_part)
    if not pieces:
        return pd.DataFrame({"lag_s": [], "autocorrelation": [], key: []})
    return pd.concat(pieces, ignore_index=True)


def filter_window_df(
    df: pd.DataFrame,
    use_full_window: bool,
    window_unit: Literal["seconds", "frames"],
    window_start: float | int | None,
    window_end: float | int | None,
) -> pd.DataFrame:
    if use_full_window or window_start is None or window_end is None:
        return df
    if window_unit == "frames" and "frame" in df.columns:
        return df[(df["frame"] >= window_start) & (df["frame"] <= window_end)].copy()
    return df[(df["time_s"] >= float(window_start)) & (df["time_s"] <= float(window_end))].copy()


def sync_frame_from_slider() -> None:
    start, end = st.session_state["frame_range_slider"]
    st.session_state["frame_start"] = int(start)
    st.session_state["frame_end"] = int(end)


def sync_frame_from_inputs() -> None:
    start = int(st.session_state["frame_start"])
    end = int(st.session_state["frame_end"])
    if start > end:
        start, end = end, start
    st.session_state["frame_start"] = start
    st.session_state["frame_end"] = end
    st.session_state["frame_range_slider"] = (start, end)


def sync_time_from_slider() -> None:
    start, end = st.session_state["time_range_slider"]
    st.session_state["time_start"] = float(start)
    st.session_state["time_end"] = float(end)


def sync_time_from_inputs() -> None:
    start = float(st.session_state["time_start"])
    end = float(st.session_state["time_end"])
    if start > end:
        start, end = end, start
    st.session_state["time_start"] = start
    st.session_state["time_end"] = end
    st.session_state["time_range_slider"] = (start, end)


def cumulative_distance_df(df: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for fly_id, part in df.groupby("fly_id"):
        p = part.sort_values("time_s").copy()
        if {"x_mm", "y_mm"}.issubset(p.columns):
            step = np.sqrt(p["x_mm"].diff().fillna(0.0) ** 2 + p["y_mm"].diff().fillna(0.0) ** 2)
        else:
            dt = p["time_s"].diff().fillna(0.0).clip(lower=0.0)
            step = p["speed_mm_s"] * dt
        p["cum_distance_mm"] = step.cumsum()
        group_name = str(p["group"].iloc[0]) if "group" in p.columns and len(p) else "Ungrouped"
        p["group"] = group_name
        pieces.append(p[["group", "fly_id", "time_s", "cum_distance_mm"]])
    return pd.concat(pieces, ignore_index=True)


def window_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | str | int]] = []
    for fly_id, part in df.groupby("fly_id"):
        p = part.sort_values("time_s").copy()
        dt = p["time_s"].diff().fillna(0.0).clip(lower=0.0)
        if {"x_mm", "y_mm"}.issubset(p.columns):
            step = np.sqrt(p["x_mm"].diff().fillna(0.0) ** 2 + p["y_mm"].diff().fillna(0.0) ** 2)
        else:
            step = p["speed_mm_s"] * dt
        rows.append(
            {
                "group": str(p["group"].iloc[0]) if "group" in p.columns and len(p) else "Ungrouped",
                "fly_id": fly_id,
                "samples": int(len(p)),
                "duration_s": float(p["time_s"].max() - p["time_s"].min()) if len(p) else 0.0,
                "mean_speed_mm_s": float(p["speed_mm_s"].mean()) if len(p) else 0.0,
                "peak_speed_mm_s": float(p["speed_mm_s"].max()) if len(p) else 0.0,
                "total_distance_mm": float(step.sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["group", "fly_id"]).reset_index(drop=True)


_STATS_METRICS: dict[str, str] = {
    "speed": "mean_speed_mm_s",
    "peak_speed": "peak_speed_mm_s",
    "total_distance": "total_distance_mm",
}


def _aggregate_metric_stats(values: pd.Series) -> dict[str, float | int]:
    v = pd.to_numeric(values, errors="coerce").dropna()
    n = int(len(v))
    if n == 0:
        return {"n": 0, "mean": float("nan"), "median": float("nan"), "std": float("nan"),
                "min": float("nan"), "max": float("nan"), "sem": float("nan")}
    std = float(v.std(ddof=1)) if n > 1 else float("nan")
    sem = float(std / np.sqrt(n)) if n > 1 else float("nan")
    return {
        "n": n,
        "mean": float(v.mean()),
        "median": float(v.median()),
        "std": std,
        "min": float(v.min()),
        "max": float(v.max()),
        "sem": sem,
    }


def summary_stats_df(per_fly_df: pd.DataFrame, group_col: str | None = None) -> pd.DataFrame:
    """Aggregate per-fly metrics into mean/median/std/min/max/SEM rows."""
    rows: list[dict[str, float | int | str]] = []
    if group_col is None:
        for metric_name, col in _STATS_METRICS.items():
            rows.append({"metric": metric_name, **_aggregate_metric_stats(per_fly_df[col])})
    else:
        for group_val, part in per_fly_df.groupby(group_col):
            for metric_name, col in _STATS_METRICS.items():
                rows.append({group_col: str(group_val), "metric": metric_name, **_aggregate_metric_stats(part[col])})
    return pd.DataFrame(rows)


def activity_fraction_df(one_sec: pd.DataFrame, threshold_mm_s: float = 1.0) -> pd.DataFrame:
    out = (
        one_sec.assign(active=one_sec["speed_mm_s"] > threshold_mm_s)
        .groupby("fly_id", as_index=False)["active"]
        .mean()
        .rename(columns={"active": "activity_fraction"})
    )
    return out


def upload_label(file_name: str, existing_ids: Iterable[str]) -> str:
    stem = Path(file_name).stem.strip() or "fly"
    fly_id = stem
    i = 2
    existing = set(existing_ids)
    while fly_id in existing:
        fly_id = f"{stem}_{i}"
        i += 1
    return fly_id


# ---------------------------------------------------------------------------
# Per-fly spatial / trajectory plots (original dashboard)
# ---------------------------------------------------------------------------

def render_fly_summary(df: pd.DataFrame, fly_id: str) -> None:
    cols = st.columns(4)
    duration = float(df["time_s"].max() - df["time_s"].min()) if len(df) else 0.0
    mean_speed = float(df["speed_mm_s"].mean()) if len(df) else 0.0
    centre_frac = float((df["zone"] == "Centre").mean()) if "zone" in df.columns and len(df) else 0.0
    cols[0].metric("Frames", f"{len(df):,}")
    cols[1].metric("Duration (s)", f"{duration:,.1f}")
    cols[2].metric("Mean speed (mm/s)", f"{mean_speed:.2f}")
    cols[3].metric("Time in centre", f"{centre_frac * 100:.1f}%")
    if len(df):
        dt = df["time_s"].diff().fillna(0.0).clip(lower=0.0)
        path_mm = float((df["speed_mm_s"] * dt).sum())
        st.caption(f"**{fly_id}** — estimated total path length: {path_mm:,.1f} mm")


def trajectory_plot(df: pd.DataFrame, fly_id: str) -> go.Figure:
    sub = df if len(df) <= 8000 else df.iloc[:: len(df) // 8000 + 1]
    fig = px.scatter(
        sub, x="x_mm", y="y_mm", color="time_s",
        color_continuous_scale="Viridis",
        title=f"Trajectory — {fly_id} (x vs y, coloured by time)",
        labels={"x_mm": "x (mm)", "y_mm": "y (mm)", "time_s": "Time (s)"},
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_traces(marker=dict(size=3, opacity=0.6))
    fig.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def raw_speed_plot(df: pd.DataFrame, fly_id: str) -> go.Figure:
    sub = downsample_per_group(df, group_col="fly_id", max_points=4_000)
    fig = px.line(
        sub, x="time_s", y="speed_mm_s",
        title=f"Speed over time (raw) — {fly_id}",
        render_mode="webgl",
    )
    fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Time (s)", yaxis_title="Speed (mm/s)",
    )
    return fig


def dist_plot(df: pd.DataFrame, fly_id: str) -> go.Figure:
    sub = downsample_per_group(df, group_col="fly_id", max_points=4_000)
    fig = px.line(
        sub, x="time_s", y="dist_from_centre_mm",
        title=f"Distance from centre over time — {fly_id}",
        render_mode="webgl",
    )
    fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Time (s)", yaxis_title="Distance (mm)",
    )
    return fig


def heatmap_plot(df: pd.DataFrame, fly_id: str) -> go.Figure:
    fig = px.density_heatmap(
        df, x="x_mm", y="y_mm", nbinsx=40, nbinsy=40,
        color_continuous_scale="Magma",
        title=f"Position density — {fly_id}",
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def zone_plot(df: pd.DataFrame, fly_id: str) -> go.Figure:
    counts = df["zone"].value_counts().reset_index()
    counts.columns = ["zone", "frames"]
    fig = px.bar(counts, x="zone", y="frames", title=f"Zone occupancy — {fly_id}", color="zone")
    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=40, b=20), showlegend=False,
    )
    return fig


CHART_REGISTRY: "dict[str, go.Figure]" = {}


def plot_chart(name: str, fig: go.Figure) -> go.Figure:
    """Render a Plotly chart and remember it for the chart download section."""
    CHART_REGISTRY[name] = fig
    st.plotly_chart(fig, use_container_width=True)
    return fig


def _slugify(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    return safe.strip("_") or "chart"


with st.sidebar:
    if ICON_PATH.exists():
        st.image(str(ICON_PATH), width=64)
    st.title("Volant")
    st.caption("Fly tracking analysis")
    if "group_ids" not in st.session_state:
        st.session_state["group_ids"] = [1]
    if "next_group_id" not in st.session_state:
        st.session_state["next_group_id"] = 2

    if st.button("+ Add group"):
        st.session_state["group_ids"].append(st.session_state["next_group_id"])
        st.session_state["next_group_id"] += 1

    group_upload_specs: list[tuple[str, list[BytesIO]]] = []
    group_to_delete: int | None = None
    for ui_idx, group_id in enumerate(st.session_state["group_ids"], start=1):
        default_group_name = f"Group {ui_idx}"
        with st.container(border=True):
            head_col, delete_col = st.columns([5, 1])
            with head_col:
                st.markdown(f"**:blue[Group {ui_idx}]**")
            with delete_col:
                can_delete = len(st.session_state["group_ids"]) > 1
                if st.button(
                    "🗑",
                    key=f"group_delete_{group_id}",
                    help="Delete this group" if can_delete else "At least one group is required",
                    disabled=not can_delete,
                ):
                    group_to_delete = group_id
            raw_name = st.text_input(
                "Name",
                value=st.session_state.get(f"group_name_{group_id}", default_group_name),
                key=f"group_name_{group_id}",
            )
            group_name = raw_name.strip() or default_group_name
            uploads = st.file_uploader(
                f"Upload CSVs for {group_name}",
                type=["csv"],
                accept_multiple_files=True,
                key=f"group_upload_{group_id}",
                help="Expected columns include: " + ", ".join(EXPECTED_COLUMNS),
            )
            group_upload_specs.append((group_name, uploads))

    if group_to_delete is not None:
        st.session_state["group_ids"] = [gid for gid in st.session_state["group_ids"] if gid != group_to_delete]
        for session_key in (f"group_name_{group_to_delete}", f"group_upload_{group_to_delete}", f"group_delete_{group_to_delete}"):
            st.session_state.pop(session_key, None)
        st.rerun()

    confidence_min = st.slider("Min confidence", 0.0, 1.0, 0.5, 0.05)
    activity_threshold = st.number_input("Activity threshold (mm/s)", 0.0, 1000.0, 1.0, 0.1)
    preview_rows = st.slider("Rows shown in previews", 25, 500, 150, 25)

    st.divider()
    st.caption("Demo flies are generated so all charts still render. Upload your own flies to compare groups.")


fly_frames: list[pd.DataFrame] = []
upload_errors: list[str] = []
uploaded_any = False

used_ids: list[str] = []
for group_name, files in group_upload_specs:
    for file in files or []:
        uploaded_any = True
        fly_id = upload_label(file.name, used_ids)
        used_ids.append(fly_id)
        try:
            raw = load_csv(file.getvalue())
            prepared = prepare_fly_df(raw, fly_id=fly_id, confidence_min=confidence_min)
            prepared["group"] = group_name
            fly_frames.append(prepared)
        except Exception as exc:  # noqa: BLE001
            upload_errors.append(f"{group_name} / {file.name}: {exc}")

if not uploaded_any:
    fly_frames = [
        make_demo_fly(seed=7, fly_id="demo_fly_1"),
        make_demo_fly(seed=17, fly_id="demo_fly_2"),
        make_demo_fly(seed=27, fly_id="demo_fly_3"),
    ]
    fly_frames = [prepare_fly_df(df, fly_id=df["fly_id"].iloc[0], confidence_min=confidence_min) for df in fly_frames]
    for df in fly_frames:
        df["group"] = "Demo Group"

if upload_errors:
    st.error("Some files could not be parsed:")
    for msg in upload_errors:
        st.write(f"- {msg}")

if not fly_frames:
    st.stop()

all_df = pd.concat(fly_frames, ignore_index=True)

has_frame_axis = "frame" in all_df.columns and all_df["frame"].notna().any()

with st.sidebar:
    st.divider()
    st.subheader("Windowed analysis")
    use_full_window = st.checkbox("Use full recording", value=True)
    allowed_window_units = ["seconds"] + (["frames"] if has_frame_axis else [])
    selected_window_unit = st.radio(
        "Window units",
        options=allowed_window_units,
        horizontal=True,
        disabled=use_full_window,
    )
    if not use_full_window and selected_window_unit == "frames":
        frame_min = int(all_df["frame"].min())
        frame_max = int(all_df["frame"].max())
        frame_start = int(np.clip(int(st.session_state.get("frame_start", frame_min)), frame_min, frame_max))
        frame_end = int(np.clip(int(st.session_state.get("frame_end", frame_max)), frame_min, frame_max))
        if frame_start > frame_end:
            frame_start, frame_end = frame_end, frame_start
        st.session_state["frame_start"] = frame_start
        st.session_state["frame_end"] = frame_end
        st.session_state["frame_range_slider"] = (frame_start, frame_end)

        st.slider(
            "Frame range",
            min_value=frame_min,
            max_value=frame_max,
            step=1,
            key="frame_range_slider",
            on_change=sync_frame_from_slider,
        )
        num_col1, num_col2 = st.columns(2)
        with num_col1:
            st.number_input(
                "Frame start",
                min_value=frame_min,
                max_value=frame_max,
                step=1,
                key="frame_start",
                on_change=sync_frame_from_inputs,
            )
        with num_col2:
            st.number_input(
                "Frame end",
                min_value=frame_min,
                max_value=frame_max,
                step=1,
                key="frame_end",
                on_change=sync_frame_from_inputs,
            )
        window_start = int(st.session_state["frame_start"])
        window_end = int(st.session_state["frame_end"])
    elif not use_full_window:
        time_min = float(all_df["time_s"].min())
        time_max = float(all_df["time_s"].max())
        step = max((time_max - time_min) / 500, 0.001)
        time_start = float(np.clip(float(st.session_state.get("time_start", time_min)), time_min, time_max))
        time_end = float(np.clip(float(st.session_state.get("time_end", time_max)), time_min, time_max))
        if time_start > time_end:
            time_start, time_end = time_end, time_start
        st.session_state["time_start"] = time_start
        st.session_state["time_end"] = time_end
        st.session_state["time_range_slider"] = (time_start, time_end)

        st.slider(
            "Time range (s)",
            min_value=time_min,
            max_value=time_max,
            step=float(step),
            key="time_range_slider",
            on_change=sync_time_from_slider,
        )
        num_col1, num_col2 = st.columns(2)
        with num_col1:
            st.number_input(
                "Time start (s)",
                min_value=time_min,
                max_value=time_max,
                step=float(step),
                format="%.3f",
                key="time_start",
                on_change=sync_time_from_inputs,
            )
        with num_col2:
            st.number_input(
                "Time end (s)",
                min_value=time_min,
                max_value=time_max,
                step=float(step),
                format="%.3f",
                key="time_end",
                on_change=sync_time_from_inputs,
            )
        window_start = float(st.session_state["time_start"])
        window_end = float(st.session_state["time_end"])
    else:
        window_start, window_end = None, None

analysis_df = filter_window_df(
    all_df,
    use_full_window=use_full_window,
    window_unit=selected_window_unit,
    window_start=window_start,
    window_end=window_end,
)

if analysis_df.empty:
    st.warning("No rows fall inside the selected window. Expand the range and try again.")
    st.stop()

group_ids = sorted(analysis_df["group"].astype(str).unique())
fly_ids = sorted(analysis_df["fly_id"].unique())

one_sec = as_second_resolution(analysis_df)
one_sec_ma = add_moving_average(one_sec)
stats_60 = sixty_second_stats(one_sec)
avg_speed = average_speed_series(one_sec)
psd = welch_psd_df(avg_speed)
acf = autocorrelation_df(avg_speed)
psd_by_fly = psd_by_key_df(one_sec, key="fly_id")
acf_by_fly = autocorrelation_by_key_df(one_sec, key="fly_id")
psd_by_group = psd_by_key_df(one_sec, key="group")
acf_by_group = autocorrelation_by_key_df(one_sec, key="group")
cumdist = cumulative_distance_df(analysis_df)
activity = activity_fraction_df(one_sec, threshold_mm_s=float(activity_threshold))
cumavg, cumavg_x, cumavg_label = cumulative_average_speed_df(analysis_df, mode=selected_window_unit)
window_summary = window_summary_df(analysis_df)
group_one_sec = (
    one_sec.groupby(["group", "second"], as_index=False)
    .agg(speed_mm_s=("speed_mm_s", "mean"))
    .sort_values(["group", "second"])
)
group_one_sec_ma = (
    group_one_sec.assign(
        speed_ma_5s=group_one_sec.groupby("group")["speed_mm_s"]
        .transform(lambda s: s.rolling(5, min_periods=1).mean())
    )
)
group_cumavg = (
    cumavg.groupby(["group", cumavg_x], as_index=False)
    .agg(cum_avg_speed_mm_s=("cum_avg_speed_mm_s", "mean"))
    .sort_values(["group", cumavg_x])
)
group_cumdist = (
    cumdist.groupby(["group", "time_s"], as_index=False)
    .agg(cum_distance_mm=("cum_distance_mm", "mean"))
    .sort_values(["group", "time_s"])
)
activity_with_group = activity.merge(
    analysis_df[["fly_id", "group"]].drop_duplicates(),
    on="fly_id",
    how="left",
)
group_activity = (
    activity_with_group.groupby("group", as_index=False)
    .agg(activity_fraction=("activity_fraction", "mean"))
    .sort_values("group")
)
group_window_summary = (
    window_summary.groupby("group", as_index=False)
    .agg(
        flies=("fly_id", "nunique"),
        samples=("samples", "sum"),
        mean_speed_mm_s=("mean_speed_mm_s", "mean"),
        total_distance_mm=("total_distance_mm", "sum"),
    )
    .sort_values("group")
)

st.title("Volant - Fly Tracking Dashboard")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Flies", f"{analysis_df['fly_id'].nunique():,}")
k2.metric("Groups", f"{analysis_df['group'].nunique():,}")
k3.metric("Total samples", f"{len(analysis_df):,}")
k4.metric("Avg activity fraction", f"{activity['activity_fraction'].mean() * 100:.1f}%")

tab_charts, tab_exports = st.tabs(["Charts", "Tables & exports"])

with tab_charts:
    view_individual, view_multi_fly, view_group = st.tabs(
        ["Individual fly", "Multi-fly", "Group comparison"]
    )

with view_individual:
    selected_group = st.selectbox("Select group", group_ids)
    group_fly_ids = sorted(analysis_df.loc[analysis_df["group"] == selected_group, "fly_id"].unique())
    selected_fly = st.selectbox("Select fly", group_fly_ids)
    fly_df = analysis_df[(analysis_df["group"] == selected_group) & (analysis_df["fly_id"] == selected_fly)].copy()
    render_fly_summary(fly_df, f"{selected_group} / {selected_fly}")

    if {"x_mm", "y_mm"}.issubset(fly_df.columns):
        plot_chart("Individual — trajectory", trajectory_plot(fly_df, selected_fly))

    col_ind_a, col_ind_b = st.columns(2)
    with col_ind_a:
        plot_chart("Individual — raw speed over time", raw_speed_plot(fly_df, selected_fly))
    with col_ind_b:
        if "dist_from_centre_mm" in fly_df.columns:
            plot_chart("Individual — distance from centre over time", dist_plot(fly_df, selected_fly))

    col_ind_c, col_ind_d = st.columns(2)
    with col_ind_c:
        if {"x_mm", "y_mm"}.issubset(fly_df.columns):
            plot_chart("Individual — position density heatmap", heatmap_plot(fly_df, selected_fly))
    with col_ind_d:
        if "zone" in fly_df.columns:
            plot_chart("Individual — zone occupancy", zone_plot(fly_df, selected_fly))

    with st.expander(f"Raw data preview — {selected_fly}"):
        st.dataframe(fly_df.head(preview_rows), use_container_width=True)

with view_multi_fly:
    plot_chart(
        "Multi-fly — speed over time (1s resolution)",
        px.line(
            one_sec,
            x="second",
            y="speed_mm_s",
            color="fly_id",
            title="Speed over time for all flies (1-second resolution)",
            labels={"second": "Time (s)", "speed_mm_s": "Speed (mm/s)", "fly_id": "Fly"},
            render_mode="webgl",
        ),
    )

    plot_chart(
        "Multi-fly — cumulative average speed",
        px.line(
            downsample_per_group(cumavg, "fly_id", max_points=4_000),
            x=cumavg_x,
            y="cum_avg_speed_mm_s",
            color="fly_id",
            title="Cumulative average speed over time",
            labels={cumavg_x: cumavg_label, "cum_avg_speed_mm_s": "Cumulative average speed (mm/s)", "fly_id": "Fly"},
            render_mode="webgl",
        ),
    )

    plot_chart(
        "Multi-fly — 5s moving average speed",
        px.line(
            one_sec_ma,
            x="second",
            y="speed_ma_5s",
            color="fly_id",
            title="5-second moving average speed (all flies)",
            labels={"second": "Time (s)", "speed_ma_5s": "5s moving average speed (mm/s)"},
            render_mode="webgl",
        ),
    )

    col1, col2 = st.columns(2)
    with col1:
        plot_chart(
            "Multi-fly — PSD per fly",
            px.line(
                psd_by_fly,
                x="frequency_hz",
                y="power",
                color="fly_id",
                title="Power spectral density (Welch method) - per fly",
                labels={"frequency_hz": "Frequency (Hz)", "power": "Power", "fly_id": "Fly"},
                render_mode="webgl",
            ),
        )
    with col2:
        plot_chart(
            "Multi-fly — autocorrelation per fly",
            px.line(
                acf_by_fly,
                x="lag_s",
                y="autocorrelation",
                color="fly_id",
                title="Autocorrelation of speed - per fly",
                labels={"lag_s": "Lag (s)", "autocorrelation": "Autocorrelation", "fly_id": "Fly"},
                render_mode="webgl",
            ),
        )

    col3, col4 = st.columns(2)
    with col3:
        plot_chart(
            "Multi-fly — peak speed per 60s window",
            px.line(
                stats_60,
                x="window_60s",
                y="peak_speed_mm_s",
                color="fly_id",
                title="Peak speed per 60s window - amplitude over time",
                labels={"window_60s": "Window start (s)", "peak_speed_mm_s": "Peak speed (mm/s)"},
            ),
        )
    with col4:
        plot_chart(
            "Multi-fly — RMS speed per 60s window",
            px.line(
                stats_60,
                x="window_60s",
                y="rms_speed_mm_s",
                color="fly_id",
                title="RMS speed per 60s window - intensity over time",
                labels={"window_60s": "Window start (s)", "rms_speed_mm_s": "RMS speed (mm/s)"},
            ),
        )

    col5, col6 = st.columns(2)
    with col5:
        plot_chart(
            "Multi-fly — coefficient of variation (60s)",
            px.line(
                stats_60,
                x="window_60s",
                y="cv_60s",
                color="fly_id",
                title="Coefficient of variation (60s windows) - speed variability",
                labels={"window_60s": "Window start (s)", "cv_60s": "Coefficient of variation"},
            ),
        )
    with col6:
        plot_chart(
            "Multi-fly — speed distribution",
            px.histogram(
                one_sec,
                x="speed_mm_s",
                color="fly_id",
                nbins=80,
                barmode="overlay",
                opacity=0.55,
                title="Speed distribution - all flies",
                labels={"speed_mm_s": "Speed (mm/s)", "fly_id": "Fly"},
            ),
        )

    col7, col8 = st.columns(2)
    with col7:
        cumdist_plot = downsample_per_group(cumdist, "fly_id", max_points=4_000)
        plot_chart(
            "Multi-fly — cumulative distance",
            px.line(
                cumdist_plot,
                x="time_s",
                y="cum_distance_mm",
                color="fly_id",
                title="Total distance traveled cumulatively (per fly)",
                labels={"time_s": "Time (s)", "cum_distance_mm": "Cumulative distance (mm)"},
                render_mode="webgl",
            ),
        )
    with col8:
        plot_chart(
            "Multi-fly — activity fraction per fly",
            px.bar(
                activity,
                x="fly_id",
                y="activity_fraction",
                title=f"Activity fraction (proportion of time active > {activity_threshold:g} mm/s for each fly)",
                labels={"fly_id": "Fly", "activity_fraction": "Activity fraction"},
            ),
        )

with view_group:
    plot_chart(
        "Group — average speed over time",
        px.line(
            downsample_per_group(group_one_sec, "group", max_points=4_000),
            x="second",
            y="speed_mm_s",
            color="group",
            title="Average speed over time by group (1-second resolution)",
            labels={"second": "Time (s)", "speed_mm_s": "Speed (mm/s)", "group": "Group"},
            render_mode="webgl",
        ),
    )

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        plot_chart(
            "Group — cumulative average speed",
            px.line(
                downsample_per_group(group_cumavg, "group", max_points=4_000),
                x=cumavg_x,
                y="cum_avg_speed_mm_s",
                color="group",
                title="Cumulative average speed by group",
                labels={cumavg_x: cumavg_label, "cum_avg_speed_mm_s": "Cumulative average speed (mm/s)", "group": "Group"},
                render_mode="webgl",
            ),
        )
    with col_g2:
        plot_chart(
            "Group — cumulative distance",
            px.line(
                downsample_per_group(group_cumdist, "group", max_points=4_000),
                x="time_s",
                y="cum_distance_mm",
                color="group",
                title="Cumulative distance by group",
                labels={"time_s": "Time (s)", "cum_distance_mm": "Cumulative distance (mm)", "group": "Group"},
                render_mode="webgl",
            ),
        )

    col_g3, col_g4 = st.columns(2)
    with col_g3:
        plot_chart(
            "Group — 5s moving average speed",
            px.line(
                downsample_per_group(group_one_sec_ma, "group", max_points=4_000),
                x="second",
                y="speed_ma_5s",
                color="group",
                title="5-second moving average speed by group",
                labels={"second": "Time (s)", "speed_ma_5s": "5s moving average speed (mm/s)", "group": "Group"},
                render_mode="webgl",
            ),
        )
    with col_g4:
        plot_chart(
            "Group — activity fraction",
            px.bar(
                group_activity,
                x="group",
                y="activity_fraction",
                title=f"Activity fraction by group (> {activity_threshold:g} mm/s)",
                labels={"group": "Group", "activity_fraction": "Activity fraction"},
            ),
        )

    col_g5, col_g6 = st.columns(2)
    with col_g5:
        plot_chart(
            "Group — PSD by group",
            px.line(
                psd_by_group,
                x="frequency_hz",
                y="power",
                color="group",
                title="Power spectral density by group (Welch method)",
                labels={"frequency_hz": "Frequency (Hz)", "power": "Power", "group": "Group"},
                render_mode="webgl",
            ),
        )
    with col_g6:
        plot_chart(
            "Group — autocorrelation by group",
            px.line(
                acf_by_group,
                x="lag_s",
                y="autocorrelation",
                color="group",
                title="Autocorrelation of speed by group",
                labels={"lag_s": "Lag (s)", "autocorrelation": "Autocorrelation", "group": "Group"},
                render_mode="webgl",
            ),
        )

with tab_exports:
    with st.expander("Data preview (1-second aggregation)"):
        st.dataframe(one_sec.head(preview_rows), use_container_width=True)

    st.subheader("Window summary table")
    st.caption("For the selected window, this table reports mean speed and total distance per fly. You can select window in the sidebar.")
    st.dataframe(window_summary, use_container_width=True)

    st.subheader("Group summary table")
    st.caption("Group-level rollup for the selected analysis window.")
    st.dataframe(group_window_summary, use_container_width=True)

    st.subheader("Summary statistics export")
    st.caption(
        "Aggregate stats (mean, median, std, min, max, SEM) over all input files "
        "for speed, peak_speed, and total_distance — computed inside the selected window."
    )
    stats_overall = summary_stats_df(window_summary, group_col=None)
    stats_by_group = summary_stats_df(window_summary, group_col="group")

    stats_tab_overall, stats_tab_by_group = st.tabs(["All flies", "Per group"])
    with stats_tab_overall:
        st.dataframe(stats_overall, use_container_width=True)
        st.download_button(
            "Download summary stats (all flies)",
            data=stats_overall.to_csv(index=False).encode("utf-8"),
            file_name="volant_summary_stats_all.csv",
            mime="text/csv",
        )
    with stats_tab_by_group:
        st.dataframe(stats_by_group, use_container_width=True)
        st.download_button(
            "Download summary stats (per group)",
            data=stats_by_group.to_csv(index=False).encode("utf-8"),
            file_name="volant_summary_stats_per_group.csv",
            mime="text/csv",
        )

    st.subheader("Download charts as images")
    st.caption(
        "Pick which charts to export. Selected charts are bundled into a single ZIP. "
        "The per-chart camera icon in each plot's toolbar can be used for one-off PNG downloads."
    )
    chart_format = st.radio(
        "Image format",
        options=["png", "svg", "pdf"],
        horizontal=True,
        key="chart_export_format",
    )
    chart_names = list(CHART_REGISTRY.keys())
    select_col_a, select_col_b = st.columns([1, 1])
    with select_col_a:
        if st.button("Select all charts"):
            for n in chart_names:
                st.session_state[f"chart_pick_{n}"] = True
            st.rerun()
    with select_col_b:
        if st.button("Clear selection"):
            for n in chart_names:
                st.session_state[f"chart_pick_{n}"] = False
            st.rerun()

    picker_cols = st.columns(2)
    selected_chart_names: list[str] = []
    for i, name in enumerate(chart_names):
        with picker_cols[i % 2]:
            if st.checkbox(name, key=f"chart_pick_{name}"):
                selected_chart_names.append(name)

    if not selected_chart_names:
        st.info("Tick one or more charts to enable the bundle download.")
    else:
        try:
            zip_buffer = BytesIO()
            export_errors: list[str] = []
            with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for name in selected_chart_names:
                    fig = CHART_REGISTRY[name]
                    try:
                        image_bytes = fig.to_image(format=chart_format, scale=2)
                    except Exception as exc:  # noqa: BLE001
                        export_errors.append(f"{name}: {exc}")
                        continue
                    zf.writestr(f"{_slugify(name)}.{chart_format}", image_bytes)
            if export_errors:
                st.warning(
                    "Some charts could not be exported (the `kaleido` package is required for image export):\n- "
                    + "\n- ".join(export_errors)
                )
            zip_buffer.seek(0)
            st.download_button(
                f"Download {len(selected_chart_names)} chart(s) as ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"volant_charts.{chart_format}.zip",
                mime="application/zip",
                disabled=zip_buffer.getbuffer().nbytes == 0,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not prepare chart bundle: {exc}")
