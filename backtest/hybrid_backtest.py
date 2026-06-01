#!/usr/bin/env python3
"""
🔥 S3_OI驱动 × DNA激进 混合策略
=================================
结合两个最佳策略的优点:
  S3_OI驱动: OI 4h暴增 + 价格涨 + 成交量放大 (高胜率+高盈亏比)
  DNA激进: OI小时级加速 + 成交量暴增 + 快进快出 (高频率+高收益)

测试多种组合参数
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


def calc_indicators(klines, oi_map):
    """计算完整指标集"""
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    
    # 成交量基线 (48h)
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
        
        # 多周期价格变化
        chg_1h = (closes[i] / closes[i-1] - 1) * 100 if i >= 1 else 0
        chg_2h = (closes[i] / closes[i-2] - 1) * 100 if i >= 2 else 0
        chg_4h = (closes[i] / closes[i-4] - 1) * 100 if i >= 4 else 0
        chg_8h = (closes[i] / closes[i-8] - 1) * 100 if i >= 8 else 0
        chg_24h = (closes[i] / closes[i-24] - 1) * 100 if i >= 24 else 0
        
        # 多周期成交量
        vol_ratio = volumes[i] / baselines[i] if baselines[i] > 0 else 1
        vol_avg_5 = sum(volumes[max(0,i-5):i]) / min(5, i) if i > 0 else volumes[i]
        vol_ratio_5 = volumes[i] / vol_avg_5 if vol_avg_5 > 0 else 1
        
        # 多周期OI
        oi_now = oi_map.get(klines[i]["time"], 0)
        oi_1h = oi_map.get(klines[i-1]["time"], 0) if i >= 1 else oi_now
        oi_2h = oi_map.get(klines[i-2]["time"], 0) if i >= 2 else oi_now
        oi_4h = oi_map.get(klines[i-4]["time"], 0) if i >= 4 else oi_now
        oi_8h = oi_map.get(klines[i-8]["time"], 0) if i >= 8 else oi_now
        
        oi_chg_1h = (oi_now / oi_1h - 1) * 100 if oi_1h > 0 else 0
        oi_chg_2h = (oi_now / oi_2h - 1) * 100 if oi_2h > 0 else 0
        oi_chg_4h = (oi_now / oi_4h - 1) * 100 if oi_4h > 0 else 0
        oi_chg_8h = (oi_now / oi_8h - 1) * 100 if oi_8h > 0 else 0
        
        # OI加速 (1h vs 2h对比)
        oi_accel = oi_chg_1h - (oi_chg_2h / 2) if oi_chg_2h != 0 else oi_chg_1h
        
        # 连续OI上涨
        oi_up_streak = 0
        for j in range(i, max(0, i-10), -1):
            prev_oi = oi_map.get(klines[j-1]["time"], 0) if j >= 1 else 0
            curr_oi = oi_map.get(klines[j]["time"], 0)
            if prev_oi > 0 and curr_oi > prev_oi:
                oi_up_streak += 1
            else:
                break
        
        # EMA
        ema_10 = ema(closes[max(0,i-10):i+1], 10)
        ema_20 = ema(closes[max(0,i-20):i+1], 20)
        
        # RSI
        if i >= 14:
            gains = [max(0, closes[j] - closes[j-1]) for j in range(i-13, i+1)]
            losses = [max(0, closes[j-1] - closes[j]) for j in range(i-13, i+1)]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
        else:
            rsi = 50
        
        indicators.append({
            "close": close, "high": klines[i]["high"], "low": klines[i]["low"],
            "time": klines[i]["time"],
            "chg_1h": chg_1h, "chg_2h": chg_2h, "chg_4h": chg_4h,
            "chg_8h": chg_8h, "chg_24h": chg_24h,
            "vol_ratio": vol_ratio, "vol_ratio_5": vol_ratio_5,
            "oi_chg_1h": oi_chg_1h, "oi_chg_2h": oi_chg_2h,
            "oi_chg_4h": oi_chg_4h, "oi_chg_8h": oi_chg_8h,
            "oi_accel": oi_accel, "oi_up_streak": oi_up_streak,
            "ema_10": ema_10, "ema_20": ema_20, "rsi": rsi,
        })
    
    return indicators


# ============================================================
# 策略定义
# ============================================================

def score_s3_oi_dna(ind, i, params):
    """
    S3_OI驱动 × DNA激进 混合评分
    
    核心逻辑:
    - OI 4h暴增 (S3核心) + OI小时级加速 (DNA核心)
    - 成交量放大 (两者共同)
    - 价格动量确认
    """
    d = ind[i]
    if not d: return 0
    
    s = 0
    
    # === OI维度 (50分) ===
    
    # OI 4h变化 (S3核心)
    if d["oi_chg_4h"] > params.get("oi_4h_th", 10):
        s += 25
    elif d["oi_chg_4h"] > params.get("oi_4h_th", 10) * 0.5:
        s += 15
    elif d["oi_chg_4h"] > 0:
        s += 8
    
    # OI 1h加速 (DNA核心)
    if d["oi_chg_1h"] > params.get("oi_1h_th", 0.5):
        s += 15
    elif d["oi_chg_1h"] > 0:
        s += 8
    
    # OI连续上涨
    if d["oi_up_streak"] >= 3:
        s += 10
    elif d["oi_up_streak"] >= 2:
        s += 5
    
    # === 成交量维度 (25分) ===
    
    if d["vol_ratio"] > params.get("vol_th", 2.5):
        s += 15
    elif d["vol_ratio"] > params.get("vol_th", 2.5) * 0.7:
        s += 10
    
    if d["vol_ratio_5"] > 2:
        s += 10
    elif d["vol_ratio_5"] > 1.5:
        s += 5
    
    # === 价格维度 (25分) ===
    
    # 4h价格变化 (S3)
    if d["chg_4h"] > params.get("chg_4h_th", 3):
        s += 15
    elif d["chg_4h"] > 0:
        s += 8
    
    # 1h价格变化 (DNA)
    if d["chg_1h"] > params.get("chg_1h_th", 0.3):
        s += 10
    elif d["chg_1h"] > 0:
        s += 5
    
    return s


def score_s3_oi_conservative(ind, i, params):
    """S3保守版: 更严格的OI条件"""
    d = ind[i]
    if not d: return 0
    
    s = 0
    
    # OI 4h必须暴增
    if d["oi_chg_4h"] > 15: s += 35
    elif d["oi_chg_4h"] > 10: s += 25
    else: return 0  # 不满足直接返回0
    
    # OI 1h必须为正
    if d["oi_chg_1h"] > 0.8: s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    
    # 成交量
    if d["vol_ratio"] > 3: s += 20
    elif d["vol_ratio"] > 2: s += 10
    
    # 价格
    if d["chg_4h"] > 5: s += 20
    elif d["chg_4h"] > 2: s += 10
    
    if d["chg_1h"] > 0: s += 10
    
    return s


def score_oi_momentum_fast(ind, i, params):
    """OI快动量: 专注OI小时级加速"""
    d = ind[i]
    if not d: return 0
    
    s = 0
    
    # OI小时级加速 (核心)
    if d["oi_chg_1h"] > 1.5: s += 30
    elif d["oi_chg_1h"] > 0.8: s += 20
    elif d["oi_chg_1h"] > 0.3: s += 10
    
    # OI 2h确认
    if d["oi_chg_2h"] > 2: s += 15
    elif d["oi_chg_2h"] > 1: s += 8
    
    # 成交量
    if d["vol_ratio"] > 4: s += 25
    elif d["vol_ratio"] > 2.5: s += 15
    
    # 价格
    if d["chg_1h"] > 0.5: s += 15
    elif d["chg_1h"] > 0: s += 8
    
    # EMA趋势
    if d["close"] > d["ema_20"]: s += 15
    
    return s


def score_oi_volume_resonance(ind, i, params):
    """OI+Vol共振: OI和成交量同步爆发"""
    d = ind[i]
    if not d: return 0
    
    s = 0
    
    # OI+Vol共振 (核心: 两者同时爆发)
    oi_rising = d["oi_chg_1h"] > 0.3
    vol_surge = d["vol_ratio"] > 2.5
    
    if oi_rising and vol_surge:
        s += 40  # 共振信号
    elif oi_rising or vol_surge:
        s += 15
    
    # OI 4h趋势
    if d["oi_chg_4h"] > 10: s += 20
    elif d["oi_chg_4h"] > 5: s += 10
    
    # 价格配合
    if d["chg_1h"] > 0.3: s += 20
    elif d["chg_1h"] > 0: s += 10
    
    # 连续性
    if d["oi_up_streak"] >= 3: s += 20
    elif d["oi_up_streak"] >= 2: s += 10
    
    return min(100, s)


STRATEGIES = {
    "S3×DNA混合": score_s3_oi_dna,
    "S3保守版": score_s3_oi_conservative,
    "OI快动量": score_oi_momentum_fast,
    "OI+Vol共振": score_oi_volume_resonance,
}


# ============================================================
# 回测引擎
# ============================================================

def backtest(symbols, strategy_fn, params, config):
    all_trades = []
    
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
        
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d: continue
            
            if not in_pos:
                score = strategy_fn(indicators, i, params)
                if score >= config["entry_th"]:
                    entry_price = d["close"]
                    entry_time = d["time"]
                    entry_score = score
                    holding = 0
                    peak_price = d["close"]
                    in_pos = True
            else:
                holding += 1
                peak_price = max(peak_price, d["close"])
                pnl = (d["close"] - entry_price) / entry_price
                
                exit_reason = None
                exit_price = d["close"]
                
                # 止损
                if pnl <= -config["sl"]:
                    exit_reason = "止损"
                    exit_price = entry_price * (1 - config["sl"])
                # 止盈
                elif pnl >= config["tp"]:
                    exit_reason = "止盈"
                    exit_price = entry_price * (1 + config["tp"])
                # OI衰减 (核心出场信号)
                elif holding >= 2 and d["oi_chg_1h"] < -0.3:
                    exit_reason = "OI衰减"
                # 成交量萎缩
                elif holding >= 2 and d["vol_ratio"] < params.get("vol_th", 2.5) * 0.3:
                    exit_reason = "量缩"
                # 从高点回撤
                elif peak_price > entry_price * 1.03:
                    dd = (peak_price - d["close"]) / peak_price
                    if dd > 0.04:
                        exit_reason = "回撤"
                # 超时
                elif holding >= config["max_hold"]:
                    exit_reason = "超时"
                
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
        "trades_detail": all_trades,
    }


def main():
    symbols = get_symbols()
    
    base_config = {
        "capital": 1000, "leverage": 10, "pos_pct": 0.5,
        "max_pos": 3, "fee": 0.0004,
    }
    
    # 测试矩阵
    test_matrix = [
        # S3×DNA混合 (多种参数)
        {"name": "混合A-标准", "fn": "S3×DNA混合",
         "params": {"oi_4h_th": 10, "oi_1h_th": 0.5, "vol_th": 2.5, "chg_4h_th": 3, "chg_1h_th": 0.3},
         "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24, "entry_th": 60}},
        
        {"name": "混合B-低阈", "fn": "S3×DNA混合",
         "params": {"oi_4h_th": 5, "oi_1h_th": 0.3, "vol_th": 2.0, "chg_4h_th": 2, "chg_1h_th": 0.2},
         "exit": {"sl": 0.06, "tp": 0.12, "max_hold": 18, "entry_th": 55}},
        
        {"name": "混合C-高阈", "fn": "S3×DNA混合",
         "params": {"oi_4h_th": 15, "oi_1h_th": 0.8, "vol_th": 3.0, "chg_4h_th": 5, "chg_1h_th": 0.5},
         "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 36, "entry_th": 70}},
        
        {"name": "混合D-快出", "fn": "S3×DNA混合",
         "params": {"oi_4h_th": 8, "oi_1h_th": 0.4, "vol_th": 2.0, "chg_4h_th": 2, "chg_1h_th": 0.2},
         "exit": {"sl": 0.05, "tp": 0.10, "max_hold": 12, "entry_th": 50}},
        
        {"name": "混合E-大盈", "fn": "S3×DNA混合",
         "params": {"oi_4h_th": 8, "oi_1h_th": 0.4, "vol_th": 2.0, "chg_4h_th": 2, "chg_1h_th": 0.2},
         "exit": {"sl": 0.08, "tp": 0.25, "max_hold": 48, "entry_th": 55}},
        
        # S3保守版
        {"name": "S3保守-标准", "fn": "S3保守版",
         "params": {},
         "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24, "entry_th": 60}},
        
        {"name": "S3保守-大盈", "fn": "S3保守版",
         "params": {},
         "exit": {"sl": 0.10, "tp": 0.25, "max_hold": 48, "entry_th": 60}},
        
        # OI快动量
        {"name": "快动量-标准", "fn": "OI快动量",
         "params": {},
         "exit": {"sl": 0.06, "tp": 0.12, "max_hold": 18, "entry_th": 55}},
        
        {"name": "快动量-激进", "fn": "OI快动量",
         "params": {},
         "exit": {"sl": 0.05, "tp": 0.10, "max_hold": 12, "entry_th": 50}},
        
        # OI+Vol共振
        {"name": "共振-标准", "fn": "OI+Vol共振",
         "params": {"vol_th": 2.5},
         "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24, "entry_th": 60}},
        
        {"name": "共振-激进", "fn": "OI+Vol共振",
         "params": {"vol_th": 2.0},
         "exit": {"sl": 0.06, "tp": 0.12, "max_hold": 18, "entry_th": 50}},
    ]
    
    print(f"\n{'='*150}")
    print("🔥 S3_OI驱动 × DNA激进 混合策略回测")
    print(f"{'='*150}")
    print("核心逻辑: OI 4h暴增 (S3) + OI小时级加速 (DNA) + 快进快出")
    print(f"  • 本金: 1000U | 杠杆: 10x | 仓位: 50% | 最大持仓: 3")
    print(f"  • 币种: {len(symbols)} 个 | 回测: 10天")
    print(f"{'='*150}")
    
    results = []
    for tm in test_matrix:
        config = {**base_config, **tm["exit"]}
        fn = STRATEGIES[tm["fn"]]
        result = backtest(symbols, fn, tm["params"], config)
        result["name"] = tm["name"]
        result["params"] = tm["params"]
        result["exit_cfg"] = tm["exit"]
        result["fn_name"] = tm["fn"]
        results.append(result)
    
    # 排序
    results.sort(key=lambda x: x["return_pct"], reverse=True)
    
    print(f"\n🏆 全部策略对比 ({len(results)}种)")
    print(f"{'='*150}")
    print(f"{'#':<3} {'策略':<14} {'最终资金':>10} {'收益%':>8} {'交易':>5} {'胜率':>6} {'均赢':>8} {'均亏':>8} {'盈亏比':>6} {'回撤%':>7} {'均持仓h':>7} {'峰值%':>7}")
    print("-" * 150)
    
    for i, r in enumerate(results, 1):
        c = "🟢" if r["return_pct"] > 200 else "🔵" if r["return_pct"] > 100 else "🟡" if r["return_pct"] > 0 else "🔴"
        print(f"{c}{i:<2} {r['name']:<14} {r['final']:>10.2f} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['avg_win']:>+8.2f} {r['avg_loss']:>+8.2f} {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {r['avg_hold']:>7.1f} {r['avg_peak']:>+6.2f}%")
    
    # TOP 3 详情
    for rank, best in enumerate(results[:3], 1):
        emoji = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉"
        print(f"\n{'='*120}")
        print(f"{emoji} #{rank} {best['name']} ({best['fn_name']})")
        print(f"{'='*120}")
        print(f"  入场参数: {best['params']}")
        print(f"  出场参数: SL{best['exit_cfg']['sl']*100}% | TP{best['exit_cfg']['tp']*100}% | Max{best['exit_cfg']['max_hold']}h | 阈值{best['exit_cfg']['entry_th']}")
        print(f"  ---")
        print(f"  1000U → {best['final']}U ({best['return_pct']:+.2f}%)")
        print(f"  {best['trades']}笔 | 胜率{best['win_rate']}% | 盈亏比{best['pf']} | 回撤{best['max_dd']}%")
        print(f"  平均持仓{best['avg_hold']}h | 平均峰值{best['avg_peak']:+.2f}%")
        
        # 出场原因
        reason_stats = {}
        for t in best["trades_detail"]:
            r = t["reason"]
            if r not in reason_stats:
                reason_stats[r] = {"count": 0, "pnl": 0, "wins": 0}
            reason_stats[r]["count"] += 1
            reason_stats[r]["pnl"] += t["pnl_usd"]
            if t["pnl_usd"] > 0: reason_stats[r]["wins"] += 1
        
        print(f"\n  出场原因:")
        for reason, stats in sorted(reason_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            c = "🟢" if stats["pnl"] > 0 else "🔴"
            print(f"    {c} {reason:<8} {stats['count']:>3}笔 | 胜率{wr:>5.1f}% | 总PnL {stats['pnl']:>+10.2f}U")
        
        # 交易记录 (前10笔盈利最大的)
        print(f"\n  TOP 10 盈利交易:")
        print(f"  {'币种':<14} {'入场':>12} {'出场':>12} {'PnL%':>7} {'PnL USD':>10} {'原因':>8} {'持仓h':>5} {'峰值%':>7}")
        for t in sorted(best["trades_detail"], key=lambda x: x["pnl_usd"], reverse=True)[:10]:
            et = datetime.fromtimestamp(t["entry_time"]/1000).strftime("%m-%d %H:%M")
            xt = datetime.fromtimestamp(t["exit_time"]/1000).strftime("%m-%d %H:%M")
            print(f"  🟢 {t['symbol']:<13} {et:>12} {xt:>12} {t['pnl_pct']:>+6.2f}% {t['pnl_usd']:>+10.2f} {t['reason']:>8} {t['holding']:>5} {t['peak_gain']:>+6.2f}%")
    
    # 最优出场参数分析
    print(f"\n{'='*120}")
    print("📊 出场参数对收益的影响")
    print(f"{'='*120}")
    
    exit_analysis = {}
    for r in results:
        key = f"SL{r['exit_cfg']['sl']*100:.0f}_TP{r['exit_cfg']['tp']*100:.0f}_H{r['exit_cfg']['max_hold']}"
        if key not in exit_analysis:
            exit_analysis[key] = []
        exit_analysis[key].append(r["return_pct"])
    
    print(f"{'出场参数':<20} {'平均收益':>10} {'最高收益':>10} {'最低收益':>10}")
    print("-" * 55)
    for key, returns in sorted(exit_analysis.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
        avg = sum(returns) / len(returns)
        print(f"  {key:<18} {avg:>+9.2f}% {max(returns):>+9.2f}% {min(returns):>+9.2f}%")
    
    print(f"\n{'='*120}")
    print("⚠️ 回测结果仅供参考，不代表未来收益。合约交易具有高风险。")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
