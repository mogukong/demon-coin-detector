#!/usr/bin/env python3
"""
v2.3 vs 优化策略 回测对比
用60天真实1h K线数据，对比两个策略的开仓/平仓/收益
"""
import json, time, os
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_URL = "https://fapi.binance.com"

# 90天妖币样本 + 高流动性币种
COINS = [
    "RAVEUSDT", "LABUSDT", "STOUSDT", "SKYAIUSDT", "BSBUSDT",
    "SIRENUSDT", "PLAYUSDT", "GUAUSDT", "ESPORTSUSDT",
    "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "MATICUSDT", "NEARUSDT", "ARBUSDT",
    "WIFUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "ORDIUSDT",
    "1000SHIBUSDT", "1000PEPEUSDT", "JUPUSDT", "TIAUSDT", "SUIUSDT",
]

def fetch_klines(symbol, interval="1h", limit=1500):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return []

def calc_oi_proxy(closes, volumes):
    if len(closes) < 5:
        return []
    oi_changes = [0]
    for i in range(1, len(closes)):
        price_chg = (closes[i] - closes[i-1]) / closes[i-1] * 100
        vol_slice = volumes[max(0,i-24):i]
        vol_median = sorted(vol_slice)[len(vol_slice)//2] if vol_slice else volumes[i]
        vol_ratio = volumes[i] / max(vol_median, 0.001)
        oi_proxy = price_chg * min(vol_ratio, 5)
        oi_changes.append(oi_proxy)
    return oi_changes

def calc_supertrend(klines_data, period=10, multiplier=3.0):
    if len(klines_data) < period + 1:
        return [0] * len(klines_data)
    highs = [float(k[2]) for k in klines_data]
    lows = [float(k[3]) for k in klines_data]
    closes = [float(k[4]) for k in klines_data]
    directions = [0] * len(klines_data)
    atrs = [0.0] * len(klines_data)
    upperbands = [0.0] * len(klines_data)
    lowerbands = [0.0] * len(klines_data)
    for i in range(1, len(klines_data)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        atrs[i] = tr if i < period else (atrs[i-1] * (period - 1) + tr) / period
    for i in range(period, len(klines_data)):
        hl2 = (highs[i] + lows[i]) / 2
        ub = hl2 + multiplier * atrs[i]
        lb = hl2 - multiplier * atrs[i]
        if i > period:
            lowerbands[i] = lb if (lowerbands[i-1] > lb or closes[i-1] < lowerbands[i-1]) else lowerbands[i-1]
            upperbands[i] = ub if (upperbands[i-1] < ub or closes[i-1] > upperbands[i-1]) else upperbands[i-1]
        else:
            upperbands[i] = ub
            lowerbands[i] = lb
        if i > period:
            if closes[i] > upperbands[i-1]:
                directions[i] = 1
            elif closes[i] < lowerbands[i-1]:
                directions[i] = -1
            else:
                directions[i] = directions[i-1]
    return directions

def score_v23(d, supertrend_dir):
    s = 0
    if d["oi_chg_4h"] > 8: s += 25
    elif d["oi_chg_4h"] > 4: s += 15
    elif d["oi_chg_4h"] > 0: s += 8
    if d["oi_chg_1h"] > 0.4: s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    if d["oi_up_streak"] >= 3: s += 10
    elif d["oi_up_streak"] >= 2: s += 5
    if d["vol_ratio"] > 2.0: s += 15
    elif d["vol_ratio"] > 1.4: s += 10
    if d["vol_ratio_5"] > 2: s += 10
    elif d["vol_ratio_5"] > 1.5: s += 5
    if d["chg_4h"] > 2: s += 15
    elif d["chg_4h"] > 0: s += 8
    if d["chg_1h"] > 0.2: s += 10
    elif d["chg_1h"] > 0: s += 5
    if supertrend_dir > 0: s += 15
    elif supertrend_dir < 0: s -= 10
    return s

def score_optimized(d, closes, volumes, i, supertrend_dir):
    s = 0
    # 启动分 35
    if d["vol_ratio"] > 3.0: s += 8
    elif d["vol_ratio"] > 2.0: s += 5
    if d["vol_ratio_5"] > 3.0: s += 8
    elif d["vol_ratio_5"] > 2.0: s += 5
    if d["oi_chg_1h"] > 3.0: s += 7
    elif d["oi_chg_1h"] > 1.0: s += 4
    if d["oi_chg_4h"] > 8.0: s += 7
    elif d["oi_chg_4h"] > 4.0: s += 4
    if d["chg_1h"] > 0.5: s += 5
    elif d["chg_1h"] > 0: s += 2
    # 结构分 30
    high_24h = max(closes[max(0,i-24):i]) if i >= 24 else closes[i]
    if closes[i] > high_24h: s += 8
    high_72h = max(closes[max(0,i-72):i]) if i >= 72 else closes[i]
    if closes[i] > high_72h: s += 8
    if i >= 20:
        ema20 = sum(closes[i-20:i]) / 20
        if closes[i] > ema20 and (closes[i] - ema20) / ema20 <= 0.12: s += 6
    if supertrend_dir > 0: s += 5
    if i >= 20:
        ema20 = sum(closes[i-20:i]) / 20
        low_last = min(closes[max(0,i-4):i])
        if low_last >= ema20 * 0.98: s += 3
    # 妖币潜力分 20
    if i >= 72:
        low_72h = min(closes[max(0,i-72):i])
        pct_from_low = (closes[i] - low_72h) / max(low_72h, 0.001) * 100
        if pct_from_low < 120: s += 8
        elif pct_from_low < 300: s += 4
    if closes[i] < 1.0: s += 5
    elif closes[i] < 5.0: s += 3
    if d["chg_4h"] > 5: s += 4
    elif d["chg_4h"] > 2: s += 2
    if d["oi_up_streak"] >= 3: s += 3
    elif d["oi_up_streak"] >= 2: s += 2
    # 执行分 15
    if d["vol_ratio"] > 2: s += 5
    elif d["vol_ratio"] > 1: s += 3
    if i >= 20:
        ema20 = sum(closes[i-20:i]) / 20
        sl_dist = (closes[i] - ema20 * 0.9) / max(closes[i], 0.001) * 100
        if 6 <= sl_dist <= 12: s += 5
        elif sl_dist < 6: s += 3
    s += 5  # funding默认
    # 强制扣分
    if i >= 168:
        low_7d = min(closes[max(0,i-168):i])
        if low_7d > 0 and (closes[i] - low_7d) / low_7d > 3.0: s -= 15
    if i >= 720:
        low_30d = min(closes[max(0,i-720):i])
        if low_30d > 0 and (closes[i] - low_30d) / low_30d > 6.0: s -= 30
    if i >= 25:
        peak = max(closes[max(0,i-24):i])
        ema20 = sum(closes[i-20:i]) / 20
        if peak > ema20 * 1.1 and closes[i] < ema20: s -= 20
    if i >= 2:
        if d["vol_ratio"] > 2 and d.get("high", closes[i]) > closes[i] * 1.05: s -= 15
    if d["oi_chg_1h"] > 5 and d["chg_1h"] < 0: s -= 20
    if i >= 24:
        chg_24h = (closes[i] - closes[i-24]) / max(closes[i-24], 0.001) * 100
        if chg_24h > 80: s -= 50
    return max(s, 0)

def calc_indicators(klines):
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    highs = [float(k[2]) for k in klines]
    st_dir = calc_supertrend(klines)
    oi_proxy = calc_oi_proxy(closes, volumes)
    indicators = []
    for i in range(len(klines)):
        if i < 72:
            indicators.append(None)
            continue
        oi_1h = oi_proxy[i] if i < len(oi_proxy) else 0
        oi_4h = sum(oi_proxy[max(0,i-4):i]) if i >= 4 else 0
        streak = 0
        for j in range(i, max(0, i-5), -1):
            if j < len(oi_proxy) and oi_proxy[j] > 0: streak += 1
            else: break
        vol_24h = volumes[max(0,i-24):i]
        vol_median = sorted(vol_24h)[len(vol_24h)//2] if vol_24h else 1
        vol_ratio = volumes[i] / max(vol_median, 1)
        vol_120h = volumes[max(0,i-120):i]
        vol_median_5 = sorted(vol_120h)[len(vol_120h)//2] if vol_120h else 1
        vol_ratio_5 = volumes[i] / max(vol_median_5, 1)
        chg_1h = (closes[i] - closes[i-1]) / max(closes[i-1], 0.001) * 100 if i >= 1 else 0
        chg_4h = (closes[i] - closes[i-4]) / max(closes[i-4], 0.001) * 100 if i >= 4 else 0
        indicators.append({
            "oi_chg_1h": oi_1h, "oi_chg_4h": oi_4h, "oi_up_streak": streak,
            "vol_ratio": vol_ratio, "vol_ratio_5": vol_ratio_5,
            "chg_1h": chg_1h, "chg_4h": chg_4h,
            "high": highs[i], "close": closes[i],
        })
    return indicators, closes, volumes, st_dir

def simulate_trades(symbol, klines, strategy="v23", entry_threshold=55):
    if len(klines) < 100:
        return {"symbol": symbol, "trades": [], "error": "insufficient data"}
    indicators, closes, volumes, st_dir = calc_indicators(klines)
    trades = []
    position = None
    peak_pnl = 0
    for i in range(72, len(klines)):
        if indicators[i] is None: continue
        d = indicators[i]
        if strategy == "v23":
            score = score_v23(d, st_dir[i])
        else:
            score = score_optimized(d, closes, volumes, i, st_dir[i])
        if position is None:
            can_open = False
            if strategy == "v23":
                if st_dir[i] >= 0 and score >= entry_threshold: can_open = True
            else:
                if i >= 24:
                    high_24h = max(closes[max(0,i-24):i])
                    if closes[i] < high_24h * 0.8: can_open = False
                    elif score >= entry_threshold:
                        chg_24h = (closes[i] - closes[i-24]) / max(closes[i-24], 0.001) * 100
                        if chg_24h > 80: can_open = False
                        else: can_open = True
            if can_open:
                position = {"entry_price": closes[i], "entry_bar": i, "entry_time": klines[i][0], "entry_score": score, "strategy": strategy}
                peak_pnl = 0
        if position is not None:
            pnl_pct = (closes[i] - position["entry_price"]) / max(position["entry_price"], 0.001)
            peak_pnl = max(peak_pnl, pnl_pct)
            if pnl_pct <= -0.10:
                trades.append({**position, "exit_price": closes[i], "exit_bar": i, "exit_time": klines[i][0], "exit_reason": "stop_loss", "pnl_pct": pnl_pct * 100, "hold_hours": i - position["entry_bar"]})
                position = None
                continue
            if strategy == "v23":
                if peak_pnl >= 0.10 and (peak_pnl - pnl_pct) >= 0.15:
                    trades.append({**position, "exit_price": closes[i], "exit_bar": i, "exit_time": klines[i][0], "exit_reason": f"trail_stop(peak{peak_pnl*100:.0f}%)", "pnl_pct": pnl_pct * 100, "hold_hours": i - position["entry_bar"]})
                    position = None
                    continue
            else:
                if peak_pnl >= 0.08 and (peak_pnl - pnl_pct) >= 0.12:
                    trades.append({**position, "exit_price": closes[i], "exit_bar": i, "exit_time": klines[i][0], "exit_reason": f"trail_stop(peak{peak_pnl*100:.0f}%)", "pnl_pct": pnl_pct * 100, "hold_hours": i - position["entry_bar"]})
                    position = None
                    continue
            if i - position["entry_bar"] >= 72:
                trades.append({**position, "exit_price": closes[i], "exit_bar": i, "exit_time": klines[i][0], "exit_reason": "timeout", "pnl_pct": pnl_pct * 100, "hold_hours": i - position["entry_bar"]})
                position = None
    return {"symbol": symbol, "trades": trades}

def main():
    print("=" * 70)
    print("v2.3 vs 优化策略 - 60天真实数据回测对比")
    print("=" * 70)
    results_v23 = []
    results_opt = []
    errors = []
    for coin in COINS:
        print(f"  {coin}...", end=" ", flush=True)
        klines = fetch_klines(coin, "1h", 1500)
        if not klines or len(klines) < 100:
            print(f"SKIP ({len(klines) if klines else 0})")
            errors.append(f"{coin}: insufficient")
            continue
        print(f"OK ({len(klines)//24}d)")
        results_v23.append(simulate_trades(coin, klines, "v23", 55))
        results_opt.append(simulate_trades(coin, klines, "optimized", 70))
        time.sleep(0.1)
    
    print("\n" + "=" * 70)
    print("STATS COMPARISON")
    print("=" * 70)
    
    def calc_stats(results):
        all_t = []
        for r in results: all_t.extend(r["trades"])
        if not all_t: return {"n":0,"wr":0,"avg":0,"tot":0,"mxw":0,"mxl":0,"avg_h":0,"sl":0,"trail":0}
        wins = [t for t in all_t if t["pnl_pct"] > 0]
        return {
            "n": len(all_t),
            "wr": len(wins)/len(all_t)*100,
            "avg": sum(t["pnl_pct"] for t in all_t)/len(all_t),
            "tot": sum(t["pnl_pct"] for t in all_t),
            "mxw": max(t["pnl_pct"] for t in all_t),
            "mxl": min(t["pnl_pct"] for t in all_t),
            "avg_h": sum(t["hold_hours"] for t in all_t)/len(all_t),
            "sl": sum(1 for t in all_t if "stop_loss" in t["exit_reason"]),
            "trail": sum(1 for t in all_t if "trail" in t["exit_reason"]),
        }
    
    sv = calc_stats(results_v23)
    so = calc_stats(results_opt)
    
    print(f"\n{'Metric':<20} {'v2.3':<15} {'Optimized':<15} {'Diff':<10}")
    print("-" * 60)
    for label, key, fmt in [
        ("Total Trades", "n", "d"), ("Win Rate", "wr", ".1f"), ("Avg PnL", "avg", ".1f"),
        ("Total PnL", "tot", ".1f"), ("Max Win", "mxw", ".1f"), ("Max Loss", "mxl", ".1f"),
        ("Avg Hold(h)", "avg_h", ".1f"), ("Stop Loss", "sl", "d"), ("Trail Stop", "trail", "d"),
    ]:
        v, o = sv[key], so[key]
        d = o - v
        if fmt == "d":
            print(f"{label:<20} {v:<15} {o:<15} {d:+d}")
        else:
            print(f"{label:<20} {v:<15.1f} {o:<15.1f} {d:+.1f}")
    
    print(f"\n\n{'='*70}")
    print("PER-COIN COMPARISON")
    print("=" * 70)
    print(f"{'Coin':<12} {'v2.3#':<6} {'v2.3PnL':<10} {'Opt#':<6} {'OptPnL':<10} {'Diff':<8}")
    print("-" * 55)
    for rv, ro in zip(results_v23, results_opt):
        sym = rv["symbol"].replace("USDT","")
        vn = len(rv["trades"])
        vp = sum(t["pnl_pct"] for t in rv["trades"])
        on = len(ro["trades"])
        op = sum(t["pnl_pct"] for t in ro["trades"])
        diff = op - vp
        m = "+" if diff > 0 else "-" if diff < 0 else "="
        print(f"{sym:<12} {vn:<6} {vp:<10.1f} {on:<6} {op:<10.1f} {m} {abs(diff):.1f}")
    
    # Top trades
    for label, results in [("v2.3 TOP5", results_v23), ("Optimized TOP5", results_opt)]:
        all_t = []
        for r in results: all_t.extend(r["trades"])
        all_t.sort(key=lambda x: x["pnl_pct"], reverse=True)
        print(f"\n{'='*70}")
        print(f"  {label}")
        print("=" * 70)
        for t in all_t[:5]:
            sym = t["symbol"].replace("USDT","")
            print(f"  {sym}: {t['pnl_pct']:+.1f}% | score={t['entry_score']} | {t['exit_reason']} | {t['hold_hours']}h")
    
    # Key conclusions
    print(f"\n{'='*70}")
    print("CONCLUSIONS")
    print("=" * 70)
    if sv["n"] > 0 and so["n"] > 0:
        wr_d = so["wr"] - sv["wr"]
        pnl_d = so["tot"] - sv["tot"]
        ml_d = so["mxl"] - sv["mxl"]
        print(f"  Win Rate: v2.3={sv['wr']:.1f}% vs Opt={so['wr']:.1f}% ({wr_d:+.1f}%)")
        print(f"  Total PnL: v2.3={sv['tot']:.1f}% vs Opt={so['tot']:.1f}% ({pnl_d:+.1f}%)")
        print(f"  Max Loss: v2.3={sv['mxl']:.1f}% vs Opt={so['mxl']:.1f}% ({ml_d:+.1f}%)")
        print(f"  Trade Count: v2.3={sv['n']} vs Opt={so['n']}")
        if pnl_d > 20:
            print("  >>> OPTIMIZED STRATEGY SIGNIFICANTLY BETTER <<<")
        elif pnl_d < -20:
            print("  >>> V2.3 CURRENT STRATEGY BETTER <<<")
        else:
            print("  >>> SIMILAR PERFORMANCE <<<")

if __name__ == "__main__":
    main()
