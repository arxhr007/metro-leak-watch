"""Builds web/public/data.json for the live dashboard.

Everything here comes from what RapidMiner already wrote:
    extras/results/distance_scores.csv   distance from normal behaviour + alarm flag (process 02)
    data/metropt3_windows_5min.csv       the window features (prep/prepare_windows.py)
    data/failure_reports.csv             the 4 reported air leaks
    extras/event_metrics.json            event-level metrics (extras/event_metrics.py)

No new modelling happens here. The script re-computes the distance from the baseline statistics
and stops if it disagrees with the column RapidMiner produced.

Run:  python build_data.py
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
RES = ROOT / "extras" / "results"
OUT = WEB / "public" / "data.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

STEP_MIN = 5
TEST_FROM = pd.Timestamp("2020-06-01")
REPAIR = {1: None, 2: "2020-05-30 12:00", 3: "2020-06-08 16:00", 4: "2020-07-16 00:00"}

# the 14 signals the distance detector uses (same list as process 02)
DIST_FEATURES = ["TP2_mean", "TP3_mean", "TP3_min", "H1_mean", "DV_pressure_mean", "Reservoirs_mean",
                 "Oil_temperature_mean", "Motor_current_mean", "Motor_current_std",
                 "COMP_duty", "DV_electric_duty", "MPG_duty", "LPS_duty", "Caudal_impulse_duty"]
# what the page draws and names in the alarm reason
DISPLAY = [
    ("TP3_mean", "Panel pressure", "bar", "lower"),
    ("TP2_mean", "Compressor pressure", "bar", "lower"),
    ("Motor_current_mean", "Motor current", "A", "higher"),
    ("DV_electric_duty", "Time under load", "share", "higher"),
    ("Oil_temperature_mean", "Oil temperature", "°C", "higher"),
    ("MPG_duty", "Low-pressure restarts", "share", "higher"),
]

print("reading RapidMiner outputs ...")
dist = pd.read_csv(RES / "distance_scores.csv", parse_dates=["window_start"]).sort_values("window_start")
dist = dist.reset_index(drop=True)
win = pd.read_csv(ROOT / "data" / "metropt3_windows_5min.csv", parse_dates=["window_start"])
fail = pd.read_csv(ROOT / "data" / "failure_reports.csv", parse_dates=["start", "end"])
metrics = json.loads((ROOT / "extras" / "event_metrics.json").read_text())

# distance_scores.csv carries the z-transformed columns (that is what the distance is built from),
# so the raw readings the page displays come from the window table instead.
raw_cols = [x[0] for x in DISPLAY]
d = dist[["window_start", "distance", "distance_alarm", "alarm_threshold", "baseline_mean", "baseline_sd"]].merge(
    win[["window_start", "phase"] + raw_cols], on="window_start", how="left")
print(f"windows: {len(d):,}  from {d.window_start.min()} to {d.window_start.max()}")

# ---------------------------------------------------------------- baseline statistics (Feb-Mar healthy)
base = win[(win.window_start < "2020-04-01") & (win.phase == "healthy")]
mu = base[DIST_FEATURES].mean()
sd = base[DIST_FEATURES].std(ddof=1).replace(0, 1)

# ---------------------------------------------------------------- check against RapidMiner's own column
z = (win.set_index("window_start")[DIST_FEATURES] - mu) / sd
recomputed = np.sqrt((z ** 2).sum(axis=1)).reindex(d.window_start).values
diff = np.nanmax(np.abs(recomputed - d.distance.values))
print(f"max |recomputed distance - RapidMiner distance| = {diff:.4f}")
assert diff < 0.05, ("recomputed distance does not match the RapidMiner output; "
                     "the page would show different numbers than the process")

thr = float(d.alarm_threshold.iloc[0])
base_mean, base_sd = float(d.baseline_mean.iloc[0]), float(d.baseline_sd.iloc[0])
sigma = round((thr - base_mean) / base_sd)
print(f"alarm line {thr:.2f} = baseline mean {base_mean:.2f} + {sigma} x sd {base_sd:.2f}")

# ---------------------------------------------------------------- alarm state (same rule as event_metrics.py)
above = (d.distance_alarm == "yes").astype(int)
d["alarm"] = above.rolling(6, min_periods=6).sum().ge(3).fillna(False)

# ---------------------------------------------------------------- per-window payload
start = d.window_start.iloc[0]
gap = d.window_start.diff().dt.total_seconds().div(60).fillna(STEP_MIN)
print(f"window spacing: {gap.min():.0f}-{gap.max():.0f} min (index is position, timestamps are explicit)")

def num(v, nd):
    """JSON has no NaN: gaps in the record become null."""
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else round(float(v), nd)


before = len(d)
d = d[d.distance.notna()].reset_index(drop=True)
if len(d) != before:
    print(f"dropped {before - len(d)} windows with no distance (gaps in the record)")

payload_series = {
    "distance": [num(v, 2) for v in d.distance],
    "alarm": [int(v) for v in d.alarm],
}
for col, label, unit, worse in DISPLAY:
    payload_series[col] = [num(v, 3) for v in d[col]]

# minutes since the first window, so the page can place points on a real time axis
minutes = ((d.window_start - start).dt.total_seconds() / 60).astype(int).tolist()

events = []
for _, f in fail.iterrows():
    r = int(f.report)
    m = next((e for e in metrics["events"] if e["report"] == r), {})
    seg = d[(d.window_start >= f.start) & (d.window_start <= f.end)]
    hit = seg[seg.alarm]
    events.append({
        "report": r,
        "start": f.start.isoformat(sep=" "),
        "end": f.end.isoformat(sep=" "),
        "repair": REPAIR[r],
        "split": "test" if f.start >= TEST_FROM else "train",
        "alarm_at": hit.window_start.iloc[0].isoformat(sep=" ") if len(hit) else None,
        "minutes_after_onset": m.get("minutes_after_onset"),
        "hours_before_repair": m.get("hours_before_repair"),
        "share_flagged_pct": m.get("share_of_event_flagged_pct"),
    })

data = {
    "meta": {
        "source": "MetroPT-3 (UCI #791), Metro do Porto / INESC TEC, CC BY 4.0",
        "unit": "Air Production Unit of a Porto metro train",
        "raw_readings": 1516948,
        "windows": int(len(d)),
        "window_minutes": STEP_MIN,
        "start": start.isoformat(sep=" "),
        "test_from": TEST_FROM.isoformat(sep=" "),
        "built_by": "RapidMiner process 02 (Leak Detection, two detectors)",
    },
    "alarm": {
        "threshold": round(thr, 2),
        "baseline_mean": round(base_mean, 2),
        "baseline_sd": round(base_sd, 2),
        "sigma": sigma,
        "persistence": {"needed": 3, "of": 6, "minutes": 30},
    },
    "signals": [{"key": k, "label": l, "unit": u, "worse_when": w} for k, l, u, w in DISPLAY],
    "baseline_stats": {k: {"mean": round(float(mu[k]), 4), "sd": round(float(sd[k]), 4)}
                       for k in DIST_FEATURES},
    "minutes": minutes,
    "series": payload_series,
    "events": events,
    "false_alarms": {
        "train": metrics["false_alarms_train"],
        "test": metrics["false_alarms_test"],
    },
    "test_months_cost": metrics["test_months_cost"],
    "supervised": metrics["supervised_on_test"],
}

OUT.write_text(json.dumps(data, separators=(",", ":")))
size_mb = OUT.stat().st_size / 1e6
print(f"\nwritten {OUT}  ({size_mb:.2f} MB)")
print(f"events: " + "; ".join(
    f"#{e['report']} {e['split']} alarm +{e['minutes_after_onset']}min" for e in events))
assert size_mb < 6, "data.json is too large for a snappy page"
