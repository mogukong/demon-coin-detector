#!/usr/bin/env python3
"""
Demon Coin Pattern Analyzer
============================
Analyzes demon coin (aggressive pump) patterns using 1h kline and OI data.
Identifies phases (Accumulation, Markup, Distribution) and builds a common
fingerprint for early detection of similar patterns.

Uses only Python standard library.
"""

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                        "Documents", "Codex", "2026-05-20",
                        "hermes-gptboykf-tg", "data", "backtest")

# Try to resolve DATA_DIR relative to various bases
_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "..", "..",
                 "Documents", "Codex", "2026-05-20",
                 "hermes-gptboykf-tg", "data", "backtest"),
    os.path.expanduser("~/Documents/Codex/2026-05-20/"
                       "hermes-gptboykf-tg/data/backtest"),
]

# Phase detection parameters (tuned iteratively)
SMOOTH_WINDOW = 6          # hours for rolling average
PHASE2_MIN_DURATION = 4    # minimum hours in markup phase to count
PRICE_UP_THRESHOLD = 0.005 # 0.5% per hour average = markup
OI_UP_THRESHOLD = 0.003    # 0.3% per hour average OI increase
VOL_SURGE_RATIO = 1.5      # volume 1.5x above baseline
OI_DECLINE_THRESHOLD = -0.001  # OI declining per hour

# ──────────────────────────────────────────────────────────────────────
# Data Loading
# ──────────────────────────────────────────────────────────────────────

def find_data_dir():
    """Find the backtest data directory."""
    for candidate in _CANDIDATES:
        resolved = os.path.normpath(candidate)
        if os.path.isdir(resolved):
            return resolved
    # Fallback: assume cwd
    cwd = os.getcwd()
    for candidate in [os.path.join(cwd, "data", "backtest"),
                      os.path.join(cwd, "backtest")]:
        if os.path.isdir(candidate):
            return candidate
    print(f"[ERROR] Cannot find backtest data directory")
    print(f"  Tried: {[os.path.normpath(c) for c in _CANDIDATES]}")
    sys.exit(1)


def load_json(filepath):
    """Load a JSON file."""
    with open(filepath, "r") as f:
        return json.load(f)


def load_klines(symbol, data_dir):
    """
    Load 1h kline data.
    Binance format: [open_time, open, high, low, close, volume,
                     close_time, quote_volume, trades,
                     taker_buy_volume, taker_buy_quote_volume, ignore]
    Returns list of dicts with parsed fields.
    """
    path = os.path.join(data_dir, f"{symbol}_1h_klines.json")
    if not os.path.exists(path):
        return []
    raw = load_json(path)
    candles = []
    for r in raw:
        candles.append({
            "ts": r[0],  # open time in ms
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),       # base asset volume
            "quote_volume": float(r[7]), # quote asset volume
            "trades": int(r[8]),
            "taker_buy_vol": float(r[9]),
            "taker_buy_qvol": float(r[10]),
        })
    candles.sort(key=lambda c: c["ts"])
    return candles


def load_oi(symbol, data_dir):
    """
    Load 1h OI data.
    Format: {symbol, sumOpenInterest, sumOpenInterestValue,
             CMCCirculatingSupply, timestamp}
    Returns list of dicts sorted by timestamp.
    """
    path = os.path.join(data_dir, f"{symbol}_oi_1h.json")
    if not os.path.exists(path):
        return []
    raw = load_json(path)
    entries = []
    for r in raw:
        entries.append({
            "ts": r["timestamp"],
            "oi": float(r["sumOpenInterest"]),
            "oi_value": float(r["sumOpenInterestValue"]),
        })
    entries.sort(key=lambda e: e["ts"])
    return entries


def merge_kline_oi(klines, oi_data):
    """Merge kline and OI data by timestamp (nearest match within 5min)."""
    if not klines or not oi_data:
        return []

    oi_map = {}
    for o in oi_data:
        oi_map[o["ts"]] = o

    merged = []
    for k in klines:
        ts = k["ts"]
        oi_entry = oi_map.get(ts)
        if not oi_entry:
            # Try +/- 1 hour
            for offset in [0, 3600000, -3600000]:
                if (ts + offset) in oi_map:
                    oi_entry = oi_map[ts + offset]
                    break
        if oi_entry:
            merged.append({**k, "oi": oi_entry["oi"], "oi_value": oi_entry["oi_value"]})
    return merged


# ──────────────────────────────────────────────────────────────────────
# Metric Computation
# ──────────────────────────────────────────────────────────────────────

def compute_metrics(data):
    """
    For each candle compute:
    - price_pct: hourly price change %
    - oi_pct: hourly OI change %
    - vol_ratio: volume / rolling average volume
    - price_cum: cumulative price change from start %
    """
    if len(data) < 2:
        return data

    # Baseline volume (median of first 24 hours or all available)
    baseline_n = min(24, len(data))
    sorted_vols = sorted(d["volume"] for d in data[:baseline_n])
    baseline_vol = sorted_vols[len(sorted_vols) // 2] if sorted_vols else 1.0
    if baseline_vol == 0:
        baseline_vol = 1.0

    metrics = []
    for i, d in enumerate(data):
        entry = dict(d)

        # Hourly price change
        if i > 0 and data[i - 1]["close"] != 0:
            entry["price_pct"] = (d["close"] - data[i - 1]["close"]) / data[i - 1]["close"]
        else:
            entry["price_pct"] = 0.0

        # Hourly OI change
        if i > 0 and data[i - 1]["oi"] != 0:
            entry["oi_pct"] = (d["oi"] - data[i - 1]["oi"]) / data[i - 1]["oi"]
        else:
            entry["oi_pct"] = 0.0

        # Volume ratio vs baseline
        entry["vol_ratio"] = d["volume"] / baseline_vol if baseline_vol else 0

        # Cumulative price change from first candle
        if data[0]["close"] != 0:
            entry["price_cum"] = (d["close"] - data[0]["close"]) / data[0]["close"]
        else:
            entry["price_cum"] = 0.0

        metrics.append(entry)

    return metrics


def rolling_avg(values, window):
    """Compute rolling average."""
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i + 1]
        result.append(sum(chunk) / len(chunk))
    return result


def add_smoothed_metrics(data, window=SMOOTH_WINDOW):
    """Add smoothed (rolling average) metrics to each entry."""
    if not data:
        return data

    price_pcts = [d["price_pct"] for d in data]
    oi_pcts = [d["oi_pct"] for d in data]
    vol_ratios = [d["vol_ratio"] for d in data]

    smooth_price = rolling_avg(price_pcts, window)
    smooth_oi = rolling_avg(oi_pcts, window)
    smooth_vol = rolling_avg(vol_ratios, window)

    for i, d in enumerate(data):
        d["smooth_price_pct"] = smooth_price[i]
        d["smooth_oi_pct"] = smooth_oi[i]
        d["smooth_vol_ratio"] = smooth_vol[i]

    return data


# ──────────────────────────────────────────────────────────────────────
# Phase Detection
# ──────────────────────────────────────────────────────────────────────

def detect_phases(data):
    """
    Detect phases using a state machine approach.

    Phase 1 (Accumulation): Price flat/down, OI neutral/slightly rising
    Phase 2 (Markup):       Price rising, OI rising, Volume surging
    Phase 3 (Distribution): Price at highs, OI declining, Volume declining

    Returns list with phase label for each candle.
    """
    if len(data) < 10:
        return [1] * len(data)

    n = len(data)
    phases = [1] * n  # default to Phase 1

    # Find the peak price index
    peak_idx = max(range(n), key=lambda i: data[i]["close"])

    # --- Phase 2 detection ---
    # Scan forward from start: mark Phase 2 when sustained markup conditions met
    phase2_start = None
    phase2_end = None

    # Use a scoring approach: for each window of SMOOTH_WINDOW hours,
    # count how many indicators are "bullish"
    for i in range(SMOOTH_WINDOW, n - SMOOTH_WINDOW):
        window = data[i:i + SMOOTH_WINDOW]
        avg_price_pct = sum(d["smooth_price_pct"] for d in window) / len(window)
        avg_oi_pct = sum(d["smooth_oi_pct"] for d in window) / len(window)
        avg_vol_ratio = sum(d["smooth_vol_ratio"] for d in window) / len(window)

        is_markup = (avg_price_pct > PRICE_UP_THRESHOLD and
                     avg_oi_pct > OI_UP_THRESHOLD and
                     avg_vol_ratio > VOL_SURGE_RATIO)

        if is_markup and phase2_start is None:
            phase2_start = i
            break

    # --- Phase 3 detection ---
    # After Phase 2: mark Phase 3 when OI starts declining and price stalls
    if phase2_start is not None:
        for i in range(phase2_start + PHASE2_MIN_DURATION, n):
            window_data = data[max(0, i - SMOOTH_WINDOW + 1):i + 1]
            avg_oi_pct = sum(d["smooth_oi_pct"] for d in window_data) / len(window_data)
            avg_price_pct = sum(d["smooth_price_pct"] for d in window_data) / len(window_data)

            # Phase 3 starts when OI declines while price is flat/declining
            if avg_oi_pct < OI_DECLINE_THRESHOLD and avg_price_pct < PRICE_UP_THRESHOLD:
                phase2_end = i
                break

        # If no Phase 3 found, use peak as boundary
        if phase2_end is None:
            phase2_end = min(peak_idx + 1, n)

        # Assign phases
        for i in range(n):
            if i < phase2_start:
                phases[i] = 1
            elif i < phase2_end:
                phases[i] = 2
            else:
                phases[i] = 3
    else:
        # No clear Phase 2 detected - use simpler approach
        # Phase 1 = before peak, Phase 3 = after peak
        for i in range(n):
            if i <= peak_idx:
                phases[i] = 1
            else:
                phases[i] = 3

    return phases, phase2_start, phase2_end


# ──────────────────────────────────────────────────────────────────────
# Phase Statistics
# ──────────────────────────────────────────────────────────────────────

def calc_correlation(xs, ys):
    """Pearson correlation coefficient."""
    n = len(xs)
    if n < 3:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n)
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def phase_stats(data, phases, phase_num):
    """Calculate statistics for a specific phase."""
    indices = [i for i, p in enumerate(phases) if p == phase_num]
    if not indices:
        return None

    phase_data = [data[i] for i in indices]

    price_pcts = [d["price_pct"] for d in phase_data]
    oi_pcts = [d["oi_pct"] for d in phase_data]
    vol_ratios = [d["vol_ratio"] for d in phase_data]
    smooth_oi = [d["smooth_oi_pct"] for d in phase_data]

    avg_price_pct = sum(price_pcts) / len(price_pcts)
    avg_oi_pct = sum(oi_pcts) / len(oi_pcts)
    avg_vol_ratio = sum(vol_ratios) / len(vol_ratios)
    avg_smooth_oi = sum(smooth_oi) / len(smooth_oi)

    # Total price change in phase
    total_price_change = (phase_data[-1]["close"] - phase_data[0]["open"]) / phase_data[0]["open"] if phase_data[0]["open"] != 0 else 0

    # OI/Volume correlation
    oi_vol_corr = calc_correlation(oi_pcts, vol_ratios)

    # Peak OI in this phase
    peak_oi = max(d["oi"] for d in phase_data)
    start_oi = phase_data[0]["oi"]

    # OI surge ratio (peak vs start of phase)
    oi_surge = peak_oi / start_oi if start_oi > 0 else 1.0

    # Max volume ratio in phase
    max_vol_ratio = max(vol_ratios)

    # Price change rate per hour (bps)
    price_rate_bps = avg_price_pct * 10000

    return {
        "duration_hours": len(indices),
        "avg_price_pct_per_hour": avg_price_pct,
        "price_rate_bps": price_rate_bps,
        "total_price_change_pct": total_price_change,
        "avg_oi_pct_per_hour": avg_oi_pct,
        "avg_smooth_oi_pct": avg_smooth_oi,
        "oi_surge_ratio": oi_surge,
        "avg_vol_ratio": avg_vol_ratio,
        "max_vol_ratio": max_vol_ratio,
        "oi_vol_correlation": oi_vol_corr,
        "peak_oi": peak_oi,
        "start_idx": indices[0],
        "end_idx": indices[-1],
    }


# ──────────────────────────────────────────────────────────────────────
# Entry/Exit Signal Analysis
# ──────────────────────────────────────────────────────────────────────

def analyze_entry_exit(data, phases, phase2_start, phase2_end):
    """Find optimal entry and exit signals within Phase 2."""
    if phase2_start is None:
        return None

    p2_data = [(i, data[i]) for i in range(len(data)) if phases[i] == 2]
    if not p2_data:
        return None

    # Best entry: earliest point in Phase 2 with good risk/reward
    # Entry signal: OI rising + volume picking up + price starting to move
    best_entry_idx = p2_data[0][0]
    for idx, d in p2_data[:min(6, len(p2_data))]:
        if d["smooth_oi_pct"] > OI_UP_THRESHOLD and d["smooth_vol_ratio"] > 1.2:
            best_entry_idx = idx
            break

    # Best exit: peak price in Phase 2 or just before Phase 3
    peak_price_idx = max(p2_data, key=lambda x: x[1]["close"])[0]

    # Entry price and exit price
    entry_price = data[best_entry_idx]["close"]
    peak_price = data[peak_price_idx]["close"]
    exit_price = data[min(phase2_end, len(data) - 1)]["close"] if phase2_end else peak_price

    potential_gain = (peak_price - entry_price) / entry_price if entry_price > 0 else 0
    realized_gain = (exit_price - entry_price) / entry_price if entry_price > 0 else 0

    # How many hours into Phase 2 is the optimal entry
    entry_offset_hours = best_entry_idx - phase2_start
    peak_offset_hours = peak_price_idx - phase2_start

    return {
        "entry_hour_offset": entry_offset_hours,
        "entry_price": entry_price,
        "peak_hour_offset": peak_offset_hours,
        "peak_price": peak_price,
        "exit_price": exit_price,
        "potential_gain_pct": potential_gain * 100,
        "realized_gain_pct": realized_gain * 100,
        "phase2_duration": (phase2_end - phase2_start) if phase2_end else 0,
    }


# ──────────────────────────────────────────────────────────────────────
# Main Analysis
# ──────────────────────────────────────────────────────────────────────

def analyze_coin(symbol, data_dir):
    """Full analysis pipeline for a single coin."""
    klines = load_klines(symbol, data_dir)
    oi_data = load_oi(symbol, data_dir)

    if not klines or not oi_data:
        print(f"  [SKIP] {symbol}: missing data (klines={len(klines)}, oi={len(oi_data)})")
        return None

    merged = merge_kline_oi(klines, oi_data)
    if len(merged) < 20:
        print(f"  [SKIP] {symbol}: too few merged points ({len(merged)})")
        return None

    # Compute metrics
    data = compute_metrics(merged)
    data = add_smoothed_metrics(data)

    # Detect phases
    phases, p2_start, p2_end = detect_phases(data)

    # Phase statistics
    stats = {}
    for pn in [1, 2, 3]:
        s = phase_stats(data, phases, pn)
        if s:
            stats[pn] = s

    # Entry/exit analysis
    entry_exit = analyze_entry_exit(data, phases, p2_start, p2_end)

    # Time range
    ts_start = datetime.fromtimestamp(data[0]["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    ts_end = datetime.fromtimestamp(data[-1]["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

    return {
        "symbol": symbol,
        "data_range": f"{ts_start} → {ts_end}",
        "total_candles": len(merged),
        "phases": phases,
        "phase2_start": p2_start,
        "phase2_end": p2_end,
        "stats": stats,
        "entry_exit": entry_exit,
        "data": data,
    }


# ──────────────────────────────────────────────────────────────────────
# Cross-Coin Fingerprint
# ──────────────────────────────────────────────────────────────────────

def build_fingerprint(results):
    """Build a common fingerprint from all analyzed coins."""
    phase2_stats = []
    phase3_stats = []
    entry_exits = []

    for r in results:
        if r is None:
            continue
        if 2 in r["stats"]:
            phase2_stats.append(r["stats"][2])
        if 3 in r["stats"]:
            phase3_stats.append(r["stats"][3])
        if r["entry_exit"]:
            entry_exits.append(r["entry_exit"])

    if not phase2_stats:
        return None

    def median(values):
        s = sorted(values)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2

    def mean(values):
        return sum(values) / len(values) if values else 0

    def fmt_pct(v):
        return f"{v * 100:+.3f}%"

    def fmt_ratio(v):
        return f"{v:.2f}x"

    # Phase 2 (Markup) common characteristics
    fp = {
        "n_coins": len(phase2_stats),
        "phase2": {
            "duration_hours_mean": mean([s["duration_hours"] for s in phase2_stats]),
            "duration_hours_median": median([s["duration_hours"] for s in phase2_stats]),
            "duration_hours_range": (min(s["duration_hours"] for s in phase2_stats),
                                     max(s["duration_hours"] for s in phase2_stats)),
            "price_rate_bps_mean": mean([s["price_rate_bps"] for s in phase2_stats]),
            "price_rate_bps_median": median([s["price_rate_bps"] for s in phase2_stats]),
            "total_price_change_mean": mean([s["total_price_change_pct"] for s in phase2_stats]),
            "total_price_change_median": median([s["total_price_change_pct"] for s in phase2_stats]),
            "oi_rate_mean": mean([s["avg_oi_pct_per_hour"] for s in phase2_stats]),
            "oi_rate_median": median([s["avg_oi_pct_per_hour"] for s in phase2_stats]),
            "oi_surge_mean": mean([s["oi_surge_ratio"] for s in phase2_stats]),
            "oi_surge_median": median([s["oi_surge_ratio"] for s in phase2_stats]),
            "vol_ratio_mean": mean([s["avg_vol_ratio"] for s in phase2_stats]),
            "vol_ratio_median": median([s["avg_vol_ratio"] for s in phase2_stats]),
            "max_vol_ratio_mean": mean([s["max_vol_ratio"] for s in phase2_stats]),
            "oi_vol_corr_mean": mean([s["oi_vol_correlation"] for s in phase2_stats]),
        },
    }

    # Phase 3 (Distribution) characteristics
    if phase3_stats:
        fp["phase3"] = {
            "duration_hours_mean": mean([s["duration_hours"] for s in phase3_stats]),
            "oi_rate_mean": mean([s["avg_oi_pct_per_hour"] for s in phase3_stats]),
            "price_rate_mean": mean([s["avg_price_pct_per_hour"] for s in phase3_stats]),
            "vol_ratio_mean": mean([s["avg_vol_ratio"] for s in phase3_stats]),
        }

    # Entry/exit characteristics
    if entry_exits:
        fp["entry_exit"] = {
            "entry_offset_mean": mean([e["entry_hour_offset"] for e in entry_exits]),
            "entry_offset_median": median([e["entry_hour_offset"] for e in entry_exits]),
            "peak_offset_mean": mean([e["peak_hour_offset"] for e in entry_exits]),
            "peak_offset_median": median([e["peak_hour_offset"] for e in entry_exits]),
            "potential_gain_mean": mean([e["potential_gain_pct"] for e in entry_exits]),
            "potential_gain_median": median([e["potential_gain_pct"] for e in entry_exits]),
            "realized_gain_mean": mean([e["realized_gain_pct"] for e in entry_exits]),
            "realized_gain_median": median([e["realized_gain_pct"] for e in entry_exits]),
        }

    return fp


# ──────────────────────────────────────────────────────────────────────
# Detection Rules
# ──────────────────────────────────────────────────────────────────────

def derive_detection_rules(fingerprint):
    """
    Derive actionable detection rules from the fingerprint.
    Returns a dict of rules with thresholds.
    """
    if not fingerprint or "phase2" not in fingerprint:
        return {}

    p2 = fingerprint["phase2"]
    ee = fingerprint.get("entry_exit", {})

    # Use median values for robust thresholds (slightly relaxed)
    rules = {
        "OI_ACCELERATION_THRESHOLD": {
            "value": p2["oi_rate_median"] * 0.7,  # 70% of median as trigger
            "description": "Hourly OI change rate to trigger alert",
            "display": f"{p2['oi_rate_median'] * 0.7 * 100:.3f}% per hour",
        },
        "OI_ACCELERATION_MIN_HOURS": {
            "value": max(3, int(p2["duration_hours_median"] * 0.2)),
            "description": "Consecutive hours of OI acceleration needed",
        },
        "VOLUME_SURGE_THRESHOLD": {
            "value": max(1.5, p2["vol_ratio_median"] * 0.6),
            "description": "Volume ratio vs baseline to confirm markup",
            "display": f"{max(1.5, p2['vol_ratio_median'] * 0.6):.1f}x baseline",
        },
        "PRICE_RATE_THRESHOLD": {
            "value": p2["price_rate_bps_median"] * 0.5,
            "description": "Minimum hourly price increase in bps",
            "display": f"{p2['price_rate_bps_median'] * 0.5:.0f} bps/hour",
        },
        "PHASE2_DURATION_TYPICAL": {
            "value": p2["duration_hours_median"],
            "description": "Typical markup phase duration in hours",
            "display": f"{p2['duration_hours_median']:.0f} hours",
        },
        "PHASE2_DURATION_RANGE": {
            "value": p2["duration_hours_range"],
            "description": "Min/max observed markup duration",
            "display": f"{p2['duration_hours_range'][0]}-{p2['duration_hours_range'][1]} hours",
        },
        "TOTAL_PUMP_TYPICAL": {
            "value": p2["total_price_change_median"],
            "description": "Typical total price increase during markup",
            "display": f"{p2['total_price_change_median'] * 100:.1f}%",
        },
        "OI_SURGE_RATIO": {
            "value": p2["oi_surge_median"],
            "description": "OI multiplier from start to peak of Phase 2",
            "display": f"{p2['oi_surge_median']:.2f}x",
        },
    }

    if ee:
        rules["ENTRY_TIMING"] = {
            "value": ee["entry_offset_median"],
            "description": "Optimal entry: N hours after Phase 2 starts",
            "display": f"Hour {ee['entry_offset_median']:.0f} of Phase 2",
        }
        rules["PEAK_TIMING"] = {
            "value": ee["peak_offset_median"],
            "description": "Peak price typically at hour N of Phase 2",
            "display": f"Hour {ee['peak_offset_median']:.0f} of Phase 2",
        }
        rules["POTENTIAL_GAIN"] = {
            "value": ee["potential_gain_median"],
            "description": "Median potential gain (entry to peak)",
            "display": f"{ee['potential_gain_median']:.1f}%",
        }

    # Exit signals (Phase 3 triggers)
    if "phase3" in fingerprint:
        p3 = fingerprint["phase3"]
        rules["EXIT_SIGNAL_OI_DECLINE"] = {
            "value": p3["oi_rate_mean"],
            "description": "Exit when OI change drops below this rate",
            "display": f"{p3['oi_rate_mean'] * 100:.3f}% per hour",
        }
        rules["EXIT_SIGNAL_VOL_DECLINE"] = {
            "value": p3["vol_ratio_mean"],
            "description": "Exit when volume drops below this ratio",
            "display": f"{p3['vol_ratio_mean']:.2f}x baseline",
        }

    return rules


# ──────────────────────────────────────────────────────────────────────
# Output Formatting
# ──────────────────────────────────────────────────────────────────────

def hr(char="─", width=78):
    return char * width


def print_per_coin(results):
    """Print per-coin phase analysis."""
    print("\n" + hr("═"))
    print("  PER-COIN PHASE ANALYSIS")
    print(hr("═"))

    for r in results:
        if r is None:
            continue
        print(f"\n{hr('─')}")
        print(f"  {r['symbol']}")
        print(f"  Data: {r['data_range']}  |  Candles: {r['total_candles']}")
        print(hr('─'))

        phase_names = {1: "Accumulation", 2: "Markup (Pump)", 3: "Distribution"}

        for pn in [1, 2, 3]:
            s = r["stats"].get(pn)
            if s is None:
                print(f"  Phase {pn} ({phase_names[pn]}): N/A")
                continue

            print(f"\n  Phase {pn} — {phase_names[pn]}")
            print(f"    Duration:           {s['duration_hours']} hours")
            print(f"    Price rate:         {s['price_rate_bps']:+.0f} bps/hr  "
                  f"({s['avg_price_pct_per_hour'] * 100:+.3f}%/hr)")
            print(f"    Total price Δ:      {s['total_price_change_pct'] * 100:+.1f}%")
            print(f"    OI rate:            {s['avg_oi_pct_per_hour'] * 100:+.4f}%/hr")
            print(f"    OI surge ratio:     {s['oi_surge_ratio']:.2f}x")
            print(f"    Avg volume ratio:   {s['avg_vol_ratio']:.2f}x baseline")
            print(f"    Max volume ratio:   {s['max_vol_ratio']:.2f}x baseline")
            print(f"    OI/Volume corr:     {s['oi_vol_correlation']:+.3f}")

        # Entry/exit
        ee = r.get("entry_exit")
        if ee:
            print(f"\n  Entry/Exit Analysis:")
            print(f"    Optimal entry:      Hour {ee['entry_hour_offset']} of Phase 2  "
                  f"(price: {ee['entry_price']:.6g})")
            print(f"    Peak timing:        Hour {ee['peak_hour_offset']} of Phase 2  "
                  f"(price: {ee['peak_price']:.6g})")
            print(f"    Potential gain:     {ee['potential_gain_pct']:+.1f}%")
            print(f"    Realized gain:      {ee['realized_gain_pct']:+.1f}%")
            print(f"    Phase 2 duration:   {ee['phase2_duration']} hours")


def print_fingerprint(fingerprint, rules):
    """Print the common fingerprint and detection rules."""
    if not fingerprint:
        print("\n[!] No fingerprint could be built (no Phase 2 data found)")
        return

    fp = fingerprint
    p2 = fp["phase2"]

    print("\n" + hr("═"))
    print("  DEMON COIN FINGERPRINT (Cross-Coin Summary)")
    print(hr("═"))
    print(f"\n  Analyzed: {fp['n_coins']} coins with detectable pump patterns\n")

    print("  ┌─────────────────────────────────────────────────────────────┐")
    print("  │  PHASE 2 (MARKUP / PUMP) CHARACTERISTICS                   │")
    print("  ├─────────────────────────────────────────────────────────────┤")
    print(f"  │  Duration:        {p2['duration_hours_median']:5.0f}h median  "
          f"({p2['duration_hours_range'][0]}-{p2['duration_hours_range'][1]}h range)")
    print(f"  │  Price rate:      {p2['price_rate_bps_median']:+6.0f} bps/hr median  "
          f"({p2['price_rate_bps_mean']:+.0f} mean)")
    print(f"  │  Total pump:      {p2['total_price_change_median'] * 100:+6.1f}% median  "
          f"({p2['total_price_change_mean'] * 100:+.1f}% mean)")
    print(f"  │  OI rate:         {p2['oi_rate_median'] * 100:+7.4f}%/hr median")
    print(f"  │  OI surge:        {p2['oi_surge_median']:6.2f}x median  "
          f"({p2['oi_surge_mean']:.2f}x mean)")
    print(f"  │  Volume ratio:    {p2['vol_ratio_median']:6.2f}x median  "
          f"({p2['vol_ratio_mean']:.2f}x mean)")
    print(f"  │  Max volume:      {p2['max_vol_ratio_mean']:6.2f}x average peak")
    print(f"  │  OI/Vol corr:     {p2['oi_vol_corr_mean']:+6.3f}")
    print("  └─────────────────────────────────────────────────────────────┘")

    if "phase3" in fp:
        p3 = fp["phase3"]
        print("\n  ┌─────────────────────────────────────────────────────────────┐")
        print("  │  PHASE 3 (DISTRIBUTION) CHARACTERISTICS                    │")
        print("  ├─────────────────────────────────────────────────────────────┤")
        print(f"  │  Duration:        {p3['duration_hours_mean']:5.0f}h average")
        print(f"  │  OI rate:         {p3['oi_rate_mean'] * 100:+7.4f}%/hr")
        print(f"  │  Price rate:      {p3['price_rate_mean'] * 100:+7.4f}%/hr")
        print(f"  │  Volume ratio:    {p3['vol_ratio_mean']:6.2f}x")
        print("  └─────────────────────────────────────────────────────────────┘")

    if "entry_exit" in fp:
        ee = fp["entry_exit"]
        print("\n  ┌─────────────────────────────────────────────────────────────┐")
        print("  │  OPTIMAL ENTRY / EXIT TIMING                               │")
        print("  ├─────────────────────────────────────────────────────────────┤")
        print(f"  │  Entry at:        Hour {ee['entry_offset_median']:.0f} of Phase 2  "
              f"(mean: {ee['entry_offset_mean']:.1f}h)")
        print(f"  │  Peak at:         Hour {ee['peak_offset_median']:.0f} of Phase 2  "
              f"(mean: {ee['peak_offset_mean']:.1f}h)")
        print(f"  │  Potential gain:  {ee['potential_gain_median']:+.1f}% median  "
              f"({ee['potential_gain_mean']:+.1f}% mean)")
        print(f"  │  Realized gain:   {ee['realized_gain_median']:+.1f}% median  "
              f"({ee['realized_gain_mean']:+.1f}% mean)")
        print("  └─────────────────────────────────────────────────────────────┘")

    # Detection rules
    if rules:
        print("\n" + hr("═"))
        print("  DETECTION RULES (Derived from Fingerprint)")
        print(hr("═"))
        print()
        for name, rule in rules.items():
            display = rule.get("display", str(rule["value"]))
            print(f"  {name}")
            print(f"    → {display}")
            print(f"      {rule['description']}")
            print()

    # Alert template
    print(hr("═"))
    print("  ALERT TEMPLATE — When to Flag a Potential Demon Coin")
    print(hr("═"))
    print("""
  TRIGGER CONDITIONS (all must be true):
  ┌────────────────────────────────────────────────────────────────────┐""")

    for name in ["OI_ACCELERATION_THRESHOLD", "OI_ACCELERATION_MIN_HOURS",
                  "VOLUME_SURGE_THRESHOLD", "PRICE_RATE_THRESHOLD"]:
        if name in rules:
            r = rules[name]
            display = r.get("display", str(r["value"]))
            print(f"  │  ✓ {name:<38} {display:<20} │")
            print(f"  │    {r['description']:<58} │")

    print("""  └────────────────────────────────────────────────────────────────────┘

  ALERT PRIORITY:
    • OI rising + Volume surging + Price starting → STRONG BUY SIGNAL
    • OI rising + Volume flat + Price flat        → WATCH (accumulation)
    • OI declining + Price at highs               → EXIT / Distribution
    • OI declining + Volume declining              → STRONG EXIT SIGNAL
""")


def print_summary_table(results):
    """Print a compact comparison table of all coins."""
    print("\n" + hr("═"))
    print("  COIN COMPARISON TABLE")
    print(hr("═"))

    header = (f"  {'Symbol':<18} {'P2 Dur':>7} {'P2 Price':>9} {'P2 OI/hr':>9} "
              f"{'P2 Vol':>7} {'P3 Dur':>7} {'Gain':>8}")
    print(header)
    print("  " + "─" * 72)

    for r in results:
        if r is None:
            continue
        sym = r["symbol"]
        p2 = r["stats"].get(2)
        p3 = r["stats"].get(3)
        ee = r.get("entry_exit")

        p2_dur = f"{p2['duration_hours']}h" if p2 else "N/A"
        p2_price = f"{p2['total_price_change_pct'] * 100:+.1f}%" if p2 else "N/A"
        p2_oi = f"{p2['avg_oi_pct_per_hour'] * 100:+.3f}%" if p2 else "N/A"
        p2_vol = f"{p2['avg_vol_ratio']:.1f}x" if p2 else "N/A"
        p3_dur = f"{p3['duration_hours']}h" if p3 else "N/A"
        gain = f"{ee['potential_gain_pct']:+.1f}%" if ee else "N/A"

        print(f"  {sym:<18} {p2_dur:>7} {p2_price:>9} {p2_oi:>9} "
              f"{p2_vol:>7} {p3_dur:>7} {gain:>8}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    print(hr("═"))
    print("  DEMON COIN PATTERN ANALYZER v1.0")
    print("  Analyzing pump patterns across multiple coins...")
    print(hr("═"))

    data_dir = find_data_dir()
    print(f"\n  Data directory: {data_dir}")

    # Discover available coins
    summary_path = os.path.join(data_dir, "fetch_summary.json")
    if os.path.exists(summary_path):
        summary = load_json(summary_path)
        symbols = list(summary.keys())
    else:
        # Discover from file names
        symbols = set()
        for f in os.listdir(data_dir):
            if f.endswith("_1h_klines.json"):
                symbols.add(f.replace("_1h_klines.json", ""))
        symbols = sorted(symbols)

    print(f"  Found {len(symbols)} coins: {', '.join(symbols)}")

    # Analyze each coin
    results = []
    for symbol in symbols:
        print(f"\n  Analyzing {symbol}...")
        result = analyze_coin(symbol, data_dir)
        results.append(result)
        if result:
            p2 = result["stats"].get(2)
            if p2:
                print(f"    ✓ Phase 2 detected: {p2['duration_hours']}h, "
                      f"price {p2['total_price_change_pct'] * 100:+.1f}%, "
                      f"OI surge {p2['oi_surge_ratio']:.2f}x")
            else:
                print(f"    ⚠ No clear Phase 2 detected")

    # Filter valid results
    valid_results = [r for r in results if r is not None]
    print(f"\n  {len(valid_results)} coins analyzed successfully")

    # Print per-coin analysis
    print_per_coin(valid_results)

    # Print comparison table
    print_summary_table(valid_results)

    # Build and print fingerprint
    fingerprint = build_fingerprint(valid_results)
    rules = derive_detection_rules(fingerprint)
    print_fingerprint(fingerprint, rules)

    # Save results to JSON
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, "demon_analysis_results.json")

    # Prepare serializable output (exclude raw data)
    output = {
        "coins": [],
        "fingerprint": fingerprint,
        "rules": {k: {kk: vv for kk, vv in v.items() if kk != "value"}
                  for k, v in rules.items()} if rules else {},
    }
    for r in valid_results:
        coin_out = {
            "symbol": r["symbol"],
            "data_range": r["data_range"],
            "total_candles": r["total_candles"],
            "phase2_start": r["phase2_start"],
            "phase2_end": r["phase2_end"],
            "stats": {str(k): v for k, v in r["stats"].items()},
            "entry_exit": r["entry_exit"],
        }
        output["coins"].append(coin_out)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")

    print("\n" + hr("═"))
    print("  ANALYSIS COMPLETE")
    print(hr("═"))


if __name__ == "__main__":
    main()
