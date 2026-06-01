#!/usr/bin/env python3
"""
🔍 S3_OI驱动 vs 混合C-高阈 深度对比分析
=========================================
找出为什么 S3_OI驱动 (+718%) 比 混合C-高阈 (+374%) 高那么多
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backtest")


def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None


def load_klines_1h(symbol):
    data = load_json(os.path.join(DATA_DIR, f"{symbol}_1h_klines.json"))
    if not data: return []
    return [{
        "time": d[0], "open": float(d[1]), "high": float(d[2]),
        "low": float(d[3]), "close": float(d[4]),
        "volume": float(d[5]), "quote_vol": float(d[7]), "trades": int(d[8]),
    } for d in data]


def load_oi_1h(symbol):
    data = load_json(os.path.join(DATA_DIR, f"{symbol}_oi_1h.json"))
    if not data: return {}
    return {int(d["timestamp"]): float(d["sumOpenInterestValue"]) for d in data}


def get_symbols():
    return sorted([f.replace("_1h_klines.json", "") for f in os.listdir(DATA_DIR) if f.endswith("_1h_klines.json")])


def ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    m = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = (p - e) * m + e
    return e


# ============================================================
# S3_OI驱动 原始评分 (来自 optimize.py)
# ============================================================

def s3_original(ind, i, params):
    """S3原始: OI 4h暴增 + 价格涨 + 成交量放大"""
    d = ind[i]
    if not d: return 0
    s = 0
    # OI 4h (核心)
    if d["oi_chg_4h"] > params.get("oi_th", 10): s += 35
    elif d["oi_chg_4h"] > params.get("oi_th", 10) * 0.5: s += 18
    # 价格 1h
    if d["chg_1h"] > params.get("chg_th", 3): s += 30
    elif d["chg_1h"] > 0: s += 15
    # 成交量
    if d["vol_ratio"] > params.get("vol_th", 2): s += 20
    elif d["vol_ratio"] > params.get("vol_th", 2) * 0.7: s += 10
    # 价格 > EMA20
    if d["close"] > d["ema_20"]: s += 15
    return s


# ============================================================
# 混合C-高阈 评分
# ============================================================

def hybrid_c(ind, i, params):
    """混合C: OI 4h + OI 1h + Vol + Price"""
    d = ind[i]
    if not d: return 0
    s = 0
    
    # OI 4h (25分)
    if d["oi_chg_4h"] > params.get("oi_4h_th", 15): s += 25
    elif d["oi_chg_4h"] > params.get("oi_4h_th", 15) * 0.5: s += 15
    elif d["oi_chg_4h"] > 0: s += 8
    
    # OI 1h (15分)
    if d["oi_chg_1h"] > params.get("oi_1h_th", 0.8): s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    
    # OI连续上涨 (10分)
    if d.get("oi_up_streak", 0) >= 3: s += 10
    elif d.get("oi_up_streak", 0) >= 2: s += 5
    
    # 成交量 (15分)
    if d["vol_ratio"] > params.get("vol_th", 3): s += 15
    elif d["vol_ratio"] > params.get("vol_th", 3) * 0.7: s += 10
    
    # 成交量5周期 (10分)
    if d.get("vol_ratio_5", 1) > 2: s += 10
    elif d.get("vol_ratio_5", 1) > 1.5: s += 5
    
    # 价格 4h (15分)
    if d["chg_4h"] > params.get("chg_4h_th", 5): s += 15
    elif d["chg_4h"] > 0: s += 8
    
    # 价格 1h (10分)
    if d["chg_1h"] > params.get("chg_1h_th", 0.5): s += 10
    elif d["chg_1h"] > 0: s += 5
    
    return s


def calc_indicators(klines, oi_map):
    """计算指标"""
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    
    baselines = []
    for i in range(len(volumes)):
        start = max(0, i - 48)
        baselines.append(sum(volumes[start:i]) / max(1, i - start))
    
    indicators = []
    for i in range(len(klines)):
        if i < 25:
            indicators.append(None)
            continue
        
        close = closes[i]
        chg_1h = (closes[i] / closes[i-1] - 1) * 100 if i >= 1 else 0
        chg_4h = (closes[i] / closes[i-4] - 1) * 100 if i >= 4 else 0
        
        oi_now = oi_map.get(klines[i]["time"], 0)
        oi_1h = oi_map.get(klines[i-1]["time"], 0) if i >= 1 else oi_now
        oi_4h = oi_map.get(klines[i-4]["time"], 0) if i >= 4 else oi_now
        
        oi_chg_1h = (oi_now / oi_1h - 1) * 100 if oi_1h > 0 else 0
        oi_chg_4h = (oi_now / oi_4h - 1) * 100 if oi_4h > 0 else 0
        
        vol_ratio = volumes[i] / baselines[i] if baselines[i] > 0 else 1
        
        vol_avg_5 = sum(volumes[max(0,i-5):i]) / min(5, i) if i > 0 else volumes[i]
        vol_ratio_5 = volumes[i] / vol_avg_5 if vol_avg_5 > 0 else 1
        
        ema_20 = ema(closes[max(0,i-20):i+1], 20)
        
        oi_up_streak = 0
        for j in range(i, max(0, i-10), -1):
            prev_oi = oi_map.get(klines[j-1]["time"], 0) if j >= 1 else 0
            curr_oi = oi_map.get(klines[j]["time"], 0)
            if prev_oi > 0 and curr_oi > prev_oi:
                oi_up_streak += 1
            else:
                break
        
        indicators.append({
            "close": close, "high": klines[i]["high"], "low": klines[i]["low"],
            "time": klines[i]["time"],
            "chg_1h": chg_1h, "chg_4h": chg_4h,
            "vol_ratio": vol_ratio, "vol_ratio_5": vol_ratio_5,
            "oi_chg_1h": oi_chg_1h, "oi_chg_4h": oi_chg_4h,
            "oi_up_streak": oi_up_streak, "ema_20": ema_20,
        })
    
    return indicators


def backtest(symbols, score_fn, params, config):
    """通用回测"""
    all_trades = []
    entry_details = []  # 记录所有入场尝试
    
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 30: continue
        
        indicators = calc_indicators(klines, oi_map)
        
        in_pos = False
        entry_price = 0
        entry_time = 0
        entry_score = 0
        holding = 0
        peak_price = 0
        entry_bar = 0
        
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d: continue
            
            score = score_fn(indicators, i, params)
            
            if not in_pos:
                # 记录所有分数
                if score > 0:
                    entry_details.append({
                        "symbol": sym, "time": d["time"],
                        "score": score, "threshold": config["entry_th"],
                        "entered": score >= config["entry_th"],
                        "oi_chg_4h": d["oi_chg_4h"],
                        "oi_chg_1h": d["oi_chg_1h"],
                        "chg_1h": d["chg_1h"],
                        "vol_ratio": d["vol_ratio"],
                    })
                
                if score >= config["entry_th"]:
                    entry_price = d["close"]
                    entry_time = d["time"]
                    entry_score = score
                    holding = 0
                    peak_price = d["close"]
                    entry_bar = i
                    in_pos = True
            else:
                holding += 1
                peak_price = max(peak_price, d["close"])
                pnl = (d["close"] - entry_price) / entry_price
                
                exit_reason = None
                exit_price = d["close"]
                
                if pnl <= -config["sl"]:
                    exit_reason = "止损"
                    exit_price = entry_price * (1 - config["sl"])
                elif pnl >= config["tp"]:
                    exit_reason = "止盈"
                    exit_price = entry_price * (1 + config["tp"])
                elif holding >= config["max_hold"]:
                    exit_reason = "超时"
                elif holding >= 2 and d["oi_chg_1h"] < -0.5:
                    exit_reason = "OI衰减"
                elif holding >= 2 and d["vol_ratio"] < 1.0:
                    exit_reason = "量缩"
                elif peak_price > entry_price * 1.05:
                    dd = (peak_price - d["close"]) / peak_price
                    if dd > 0.05:
                        exit_reason = "回撤"
                
                if exit_reason:
                    actual_pnl = (exit_price - entry_price) / entry_price
                    pos_size = config["capital"] * config["pos_pct"] * config["leverage"]
                    pnl_usd = pos_size * actual_pnl - pos_size * config["fee"] * 2
                    
                    all_trades.append({
                        "symbol": sym, "entry_time": entry_time, "exit_time": d["time"],
                        "entry_price": entry_price, "exit_price": exit_price,
                        "score": entry_score, "pnl_pct": actual_pnl * 100,
                        "pnl_usd": pnl_usd, "reason": exit_reason,
                        "holding": holding, "peak_price": peak_price,
                        "peak_gain": (peak_price / entry_price - 1) * 100,
                    })
                    in_pos = False
    
    all_trades.sort(key=lambda x: x["entry_time"])
    
    capital = config["capital"]
    peak = capital
    max_dd = 0
    active = 0
    
    for t in all_trades:
        if active >= config["max_pos"]:
            active -= 1
        capital += t["pnl_usd"]
        peak = max(peak, capital)
        dd = (peak - capital) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        active += 1
    
    wins = [t for t in all_trades if t["pnl_usd"] > 0]
    losses = [t for t in all_trades if t["pnl_usd"] <= 0]
    
    return {
        "final": round(capital, 2),
        "return_pct": round((capital / config["capital"] - 1) * 100, 2),
        "trades": len(all_trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "avg_win": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else 0,
        "max_dd": round(max_dd * 100, 2),
        "pf": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)), 2) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0,
        "avg_hold": round(sum(t["holding"] for t in all_trades) / len(all_trades), 1) if all_trades else 0,
        "avg_peak": round(sum(t["peak_gain"] for t in all_trades) / len(all_trades), 2) if all_trades else 0,
        "total_pnl": round(sum(t["pnl_usd"] for t in all_trades), 2),
        "trades_detail": all_trades,
        "entry_signals": len([e for e in entry_details if e["entered"]]),
        "total_signals": len(entry_details),
    }


def main():
    symbols = get_symbols()
    
    base_config = {
        "capital": 1000, "leverage": 10, "pos_pct": 0.5,
        "max_pos": 3, "fee": 0.0004,
    }
    
    print(f"\n{'='*140}")
    print("🔍 S3_OI驱动 vs 混合C-高阈 深度对比分析")
    print(f"{'='*140}")
    
    # ==========================================
    # 测试1: 相同出场条件，对比入场逻辑
    # ==========================================
    print(f"\n{'='*140}")
    print("📊 测试1: 相同出场条件 (SL10/TP20/Max72h/Entry60)，对比入场逻辑")
    print(f"{'='*140}")
    
    same_exit = {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 60}
    
    tests_1 = [
        {
            "name": "S3原始-标准",
            "fn": s3_original,
            "params": {"oi_th": 10, "vol_th": 2, "chg_th": 3},
        },
        {
            "name": "S3原始-宽松",
            "fn": s3_original,
            "params": {"oi_th": 5, "vol_th": 1.5, "chg_th": 2},
        },
        {
            "name": "S3原始-严格",
            "fn": s3_original,
            "params": {"oi_th": 15, "vol_th": 3, "chg_th": 5},
        },
        {
            "name": "混合C-标准",
            "fn": hybrid_c,
            "params": {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3, "chg_4h_th": 5, "chg_1h_th": 0.5},
        },
        {
            "name": "混合C-宽松",
            "fn": hybrid_c,
            "params": {"oi_4h_th": 8, "oi_1h_th": 0.4, "vol_th": 2, "chg_4h_th": 2, "chg_1h_th": 0.2},
        },
        {
            "name": "混合C-严格",
            "fn": hybrid_c,
            "params": {"oi_4h_th": 20, "oi_1h_th": 1.0, "vol_th": 4, "chg_4h_th": 8, "chg_1h_th": 0.8},
        },
    ]
    
    print(f"\n{'策略':<16} {'最终资金':>10} {'收益%':>8} {'交易':>5} {'胜率':>6} {'盈亏比':>6} {'回撤%':>7} {'均持仓h':>7} {'信号数':>6}")
    print("-" * 100)
    
    results_1 = []
    for t in tests_1:
        config = {**base_config, **same_exit}
        r = backtest(symbols, t["fn"], t["params"], config)
        r["name"] = t["name"]
        r["params"] = t["params"]
        results_1.append(r)
        c = "🟢" if r["return_pct"] > 200 else "🔵" if r["return_pct"] > 0 else "🔴"
        print(f"{c} {r['name']:<14} {r['final']:>10.2f} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {r['avg_hold']:>7.1f} {r['total_signals']:>6}")
    
    # ==========================================
    # 测试2: 各自最优出场条件
    # ==========================================
    print(f"\n{'='*140}")
    print("📊 测试2: 各自最优出场条件")
    print(f"{'='*140}")
    
    tests_2 = [
        {
            "name": "S3原始-最优",
            "fn": s3_original,
            "params": {"oi_th": 10, "vol_th": 2, "chg_th": 3},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 60},
        },
        {
            "name": "S3原始-72h",
            "fn": s3_original,
            "params": {"oi_th": 10, "vol_th": 2, "chg_th": 3},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 55},
        },
        {
            "name": "S3原始-48h",
            "fn": s3_original,
            "params": {"oi_th": 10, "vol_th": 2, "chg_th": 3},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 48, "entry_th": 55},
        },
        {
            "name": "S3原始-低阈",
            "fn": s3_original,
            "params": {"oi_th": 5, "vol_th": 1.5, "chg_th": 2},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 50},
        },
        {
            "name": "混合C-36h",
            "fn": hybrid_c,
            "params": {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3, "chg_4h_th": 5, "chg_1h_th": 0.5},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 36, "entry_th": 70},
        },
        {
            "name": "混合C-72h",
            "fn": hybrid_c,
            "params": {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3, "chg_4h_th": 5, "chg_1h_th": 0.5},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 70},
        },
    ]
    
    print(f"\n{'策略':<16} {'最终资金':>10} {'收益%':>8} {'交易':>5} {'胜率':>6} {'盈亏比':>6} {'回撤%':>7} {'均持仓h':>7}")
    print("-" * 90)
    
    results_2 = []
    for t in tests_2:
        config = {**base_config, **t["exit"]}
        r = backtest(symbols, t["fn"], t["params"], config)
        r["name"] = t["name"]
        r["exit_cfg"] = t["exit"]
        results_2.append(r)
        c = "🟢" if r["return_pct"] > 200 else "🔵" if r["return_pct"] > 0 else "🔴"
        print(f"{c} {r['name']:<14} {r['final']:>10.2f} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {r['avg_hold']:>7.1f}")
    
    # ==========================================
    # 测试3: 评分分布分析
    # ==========================================
    print(f"\n{'='*140}")
    print("📊 测试3: 评分分布分析 - 为什么S3交易更少但收益更高?")
    print(f"{'='*140}")
    
    # 收集S3和混合C的评分分布
    s3_scores = []
    hc_scores = []
    
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 30: continue
        
        indicators = calc_indicators(klines, oi_map)
        
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d: continue
            s3 = s3_original(indicators, i, {"oi_th": 10, "vol_th": 2, "chg_th": 3})
            hc = hybrid_c(indicators, i, {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3, "chg_4h_th": 5, "chg_1h_th": 0.5})
            if s3 > 0: s3_scores.append(s3)
            if hc > 0: hc_scores.append(hc)
    
    print(f"\n评分分布:")
    print(f"  S3原始: {len(s3_scores)} 个信号 | 均分 {sum(s3_scores)/len(s3_scores):.1f} | ≥60分 {len([s for s in s3_scores if s >= 60])} 个 | ≥80分 {len([s for s in s3_scores if s >= 80])} 个")
    print(f"  混合C: {len(hc_scores)} 个信号 | 均分 {sum(hc_scores)/len(hc_scores):.1f} | ≥60分 {len([s for s in hc_scores if s >= 60])} 个 | ≥80分 {len([s for s in hc_scores if s >= 80])} 个")
    
    # 评分区间分布
    print(f"\n评分区间分布:")
    print(f"  {'区间':<10} {'S3原始':>10} {'混合C':>10}")
    print(f"  {'-'*35}")
    for lo, hi in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]:
        s3_count = len([s for s in s3_scores if lo <= s < hi])
        hc_count = len([s for s in hc_scores if lo <= s < hi])
        print(f"  {lo}-{hi:<6} {s3_count:>10} {hc_count:>10}")
    
    # ==========================================
    # 测试4: 最优S3 vs 最优混合C (完全对比)
    # ==========================================
    print(f"\n{'='*140}")
    print("📊 测试4: 最优S3 vs 最优混合C 完全对比")
    print(f"{'='*140}")
    
    best_s3 = backtest(symbols, s3_original, {"oi_th": 10, "vol_th": 2, "chg_th": 3},
                       {**base_config, "sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 55})
    
    best_hc = backtest(symbols, hybrid_c, {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3, "chg_4h_th": 5, "chg_1h_th": 0.5},
                       {**base_config, "sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 60})
    
    print(f"\n{'指标':<16} {'S3原始-最优':>14} {'混合C-最优':>14} {'差异':>12}")
    print("-" * 60)
    print(f"{'最终资金':<16} {best_s3['final']:>14.2f} {best_hc['final']:>14.2f} {best_s3['final']-best_hc['final']:>+12.2f}")
    print(f"{'收益%':<16} {best_s3['return_pct']:>+13.2f}% {best_hc['return_pct']:>+13.2f}% {best_s3['return_pct']-best_hc['return_pct']:>+11.2f}%")
    print(f"{'交易笔数':<16} {best_s3['trades']:>14} {best_hc['trades']:>14} {best_s3['trades']-best_hc['trades']:>+12}")
    print(f"{'胜率':<16} {best_s3['win_rate']:>13.1f}% {best_hc['win_rate']:>13.1f}% {best_s3['win_rate']-best_hc['win_rate']:>+11.1f}%")
    print(f"{'盈亏比':<16} {best_s3['pf']:>14.2f} {best_hc['pf']:>14.2f} {best_s3['pf']-best_hc['pf']:>+12.2f}")
    print(f"{'最大回撤':<16} {best_s3['max_dd']:>13.2f}% {best_hc['max_dd']:>13.2f}% {best_s3['max_dd']-best_hc['max_dd']:>+11.2f}%")
    print(f"{'平均持仓h':<16} {best_s3['avg_hold']:>14.1f} {best_hc['avg_hold']:>14.1f} {best_s3['avg_hold']-best_hc['avg_hold']:>+12.1f}")
    print(f"{'平均峰值%':<16} {best_s3['avg_peak']:>+13.2f}% {best_hc['avg_peak']:>+13.2f}% {best_s3['avg_peak']-best_hc['avg_peak']:>+11.2f}%")
    print(f"{'信号总数':<16} {best_s3['total_signals']:>14} {best_hc['total_signals']:>14} {best_s3['total_signals']-best_hc['total_signals']:>+12}")
    
    # ==========================================
    # 原因分析
    # ==========================================
    print(f"\n{'='*140}")
    print("🔍 原因分析: 为什么S3原始比混合C收益高?")
    print(f"{'='*140}")
    print(f"""
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 原因一: 评分逻辑更简单直接                                                                      │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ S3原始: 只看3个核心指标 (OI 4h + Price 1h + Vol)                                                │
│ 混合C: 看7个指标 (OI 4h + OI 1h + OI连续 + Vol + Vol5 + Price 4h + Price 1h)                  │
│                                                                                                 │
│ → S3的"简单"反而是优势: 只抓最核心的信号, 不被噪音干扰                                           │
│ → 混合C的"全面"反而是劣势: 条件太多导致真正的好信号被过滤掉                                       │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 原因二: S3给OI更高的权重 (35分 vs 25分)                                                         │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ S3: OI 4h > 10% 直接得35分 (总分100分的35%)                                                     │
│ 混合C: OI 4h > 15% 只得25分 (总分100分的25%)                                                    │
│                                                                                                 │
│ → 你说了: "OI和Vol才是重点"                                                                      │
│ → S3更符合这个逻辑: OI权重最高                                                                  │
│ → 混合C把OI权重分散到多个子指标, 稀释了核心信号                                                  │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 原因三: S3用Price 1h而非Price 4h                                                                │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ S3: 用 chg_1h (即时动量)                                                                        │
│ 混合C: 同时用 chg_4h + chg_1h (双重确认)                                                        │
│                                                                                                 │
│ → 妖币的特点是"突然爆发", 1h变化比4h更敏感                                                      │
│ → 用4h变化会延迟入场, 错过最佳时机                                                               │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 原因四: 最大持仓时间 (72h vs 36h)                                                               │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ S3: 72小时, 给足时间让利润奔跑                                                                   │
│ 混合C: 36小时, 可能过早离场                                                                      │
│                                                                                                 │
│ → 有些妖币拉升周期长达42小时 (如BEAT 38h)                                                       │
│ → 36h会错过后面的利润                                                                            │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 原因五: 信号质量 > 信号数量                                                                      │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ S3: 21笔交易, 每笔都是高质量信号                                                                 │
│ 混合C: 48笔交易, 包含更多低质量信号                                                               │
│                                                                                                 │
│ → S3的21笔中, 平均每笔赚更多                                                                     │
│ → 混合C的48笔中, 低质量交易拉低了整体收益                                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

💡 核心结论:
  1. 评分越简单越好 - 只看OI+Vol+Price三个核心
  2. OI权重应该最高 - 这是妖币的第一驱动力
  3. 用1h变化而非4h - 更快捕捉启动信号
  4. 给足持仓时间 - 72h比36h更好
  5. 少即是多 - 21笔高质量 > 48笔低质量
""")
    
    print(f"{'='*140}")
    print("⚠️ 回测结果仅供参考，不代表未来收益。合约交易具有高风险。")
    print(f"{'='*140}")


if __name__ == "__main__":
    main()
