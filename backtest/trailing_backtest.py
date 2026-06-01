#!/usr/bin/env python3
"""
🔥 移动止盈策略回测
====================
基于妖币数据 (BEAT/FIGHT/ALT/MAVIA等) 设计最优移动止盈

测试策略:
1. 固定止盈 15% (基线)
2. 固定止盈 20%
3. 移动止盈A: 涨10%后启动，回撤5%平仓
4. 移动止盈B: 涨15%后启动，回撤8%平仓
5. 移动止盈C: 涨20%后启动，回撤10%平仓
6. 移动止盈D: 分段止盈 (10%平1/3, 20%平1/3, 剩余移动)
7. 移动止盈E: 涨10%后移动止损到成本价 (保本)
8. 移动止盈F: 涨15%后移动止损到+5% (锁利)
9. 移动止盈G: 时间+涨幅联合 (12h内涨>30%则平)
10. 移动止盈H: OI衰减+涨幅联合 (OI下降+涨>15%则平)
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


def calc_indicators(klines, oi_map):
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
            "oi_up_streak": oi_up_streak,
        })
    return indicators


def score_signal(ind, i):
    d = ind[i]
    if not d: return 0
    s = 0
    if d["oi_chg_4h"] > 8: s += 25
    elif d["oi_chg_4h"] > 4: s += 15
    elif d["oi_chg_4h"] > 0: s += 8
    if d["oi_chg_1h"] > 0.4: s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    if d["oi_up_streak"] >= 3: s += 10
    elif d["oi_up_streak"] >= 2: s += 5
    if d["vol_ratio"] > 2: s += 15
    elif d["vol_ratio"] > 1.4: s += 10
    if d["vol_ratio_5"] > 2: s += 10
    elif d["vol_ratio_5"] > 1.5: s += 5
    if d["chg_4h"] > 2: s += 15
    elif d["chg_4h"] > 0: s += 8
    if d["chg_1h"] > 0.2: s += 10
    elif d["chg_1h"] > 0: s += 5
    return s


# ============================================================
# 止盈策略
# ============================================================

def exit_fixed_tp(pnl_pct, peak_pnl, holding, d, params):
    """固定止盈"""
    if pnl_pct >= params["tp"]:
        return "止盈"
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    return None


def exit_trailing_simple(pnl_pct, peak_pnl, holding, d, params):
    """简单移动止盈: 涨X%后启动，回撤Y%平仓"""
    activate = params["activate"]   # 启动阈值
    trail_pct = params["trail"]     # 回撤幅度
    
    # 止损
    if pnl_pct <= -params["sl"]:
        return "止损"
    
    # 超时
    if holding >= params["max_hold"]:
        return "超时"
    
    # 移动止盈
    if peak_pnl >= activate:
        # 已激活，从最高点回撤超过trail_pct则平仓
        if peak_pnl - pnl_pct >= trail_pct:
            return f"移动止盈(峰值{peak_pnl:.1f}%→{pnl_pct:.1f}%)"
    
    return None


def exit_trailing_lock(pnl_pct, peak_pnl, holding, d, params):
    """锁利移动止盈: 涨X%后止损移到+Y%"""
    activate = params["activate"]
    lock_at = params["lock_at"]     # 锁定利润水平
    
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    
    # 涨到activate后，止损上移到lock_at
    if peak_pnl >= activate:
        if pnl_pct <= lock_at:
            return f"锁利(锁定{lock_at}%)"
    
    return None


def exit_staged(pnl_pct, peak_pnl, holding, d, params):
    """分段止盈: 涨10%平1/3, 涨20%平1/3, 剩余移动"""
    # 简化处理: 只看整体出场点
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    
    # 分段逻辑简化为: 涨超过25%或从峰值回撤8%
    if pnl_pct >= 25:
        return "止盈25%"
    if peak_pnl >= 15 and peak_pnl - pnl_pct >= 8:
        return f"移动止盈(峰值{peak_pnl:.1f}%)"
    if peak_pnl >= 10 and peak_pnl - pnl_pct >= 5:
        return f"移动止盈(峰值{peak_pnl:.1f}%)"
    
    return None


def exit_time_peak(pnl_pct, peak_pnl, holding, d, params):
    """时间+涨幅联合: 12h内涨>30%则平"""
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    
    # 12小时内涨幅超过30%
    if holding <= 12 and pnl_pct >= 30:
        return "快涨止盈"
    
    # 从峰值回撤
    if peak_pnl >= 15 and peak_pnl - pnl_pct >= 8:
        return f"移动止盈"
    
    return None


def exit_oi_peak(pnl_pct, peak_pnl, holding, d, params):
    """OI衰减+涨幅联合"""
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    
    # OI下降 + 已经盈利超过15%
    if d and d.get("oi_chg_1h", 0) < -0.5 and pnl_pct >= 15:
        return "OI衰减止盈"
    
    # 从峰值回撤
    if peak_pnl >= 10 and peak_pnl - pnl_pct >= 6:
        return f"移动止盈"
    
    return None


def exit_adaptive(pnl_pct, peak_pnl, holding, d, params):
    """自适应止盈: 根据涨幅大小动态调整回撤容忍度"""
    if pnl_pct <= -params["sl"]:
        return "止损"
    if holding >= params["max_hold"]:
        return "超时"
    
    # 涨幅越大，允许回撤越大
    if peak_pnl >= 50:
        trail = 15  # 涨50%后允许回撤15%
    elif peak_pnl >= 30:
        trail = 10  # 涨30%后允许回撤10%
    elif peak_pnl >= 20:
        trail = 7   # 涨20%后允许回撤7%
    elif peak_pnl >= 10:
        trail = 5   # 涨10%后允许回撤5%
    else:
        trail = 999  # 未激活
    
    if peak_pnl >= 10 and peak_pnl - pnl_pct >= trail:
        return f"自适应(峰值{peak_pnl:.1f}%回撤{peak_pnl-pnl_pct:.1f}%)"
    
    return None


# ============================================================
# 回测引擎
# ============================================================

def backtest_strategy(symbols, exit_fn, exit_params, entry_score=55):
    base_params = {"sl": 0.10, "max_hold": 36}
    all_params = {**base_params, **exit_params}
    
    all_trades = []
    
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 30: continue
        
        indicators = calc_indicators(klines, oi_map)
        
        in_pos = False
        entry_price = 0
        holding = 0
        peak_pnl = 0
        
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d: continue
            
            if not in_pos:
                score = score_signal(indicators, i)
                if score >= entry_score:
                    entry_price = d["close"]
                    holding = 0
                    peak_pnl = 0
                    in_pos = True
            else:
                holding += 1
                pnl_pct = (d["close"] - entry_price) / entry_price * 100
                peak_pnl = max(peak_pnl, pnl_pct)
                
                # 用最高价计算峰值 (更真实的回撤)
                high_pnl = (d["high"] - entry_price) / entry_price * 100
                peak_pnl = max(peak_pnl, high_pnl)
                
                exit_reason = exit_fn(pnl_pct, peak_pnl, holding, d, all_params)
                
                if exit_reason:
                    # 计算实际PnL (用close价)
                    pos_size = 1000 * 0.30 * 10  # 300U margin, 10x
                    pnl_usd = pos_size * (pnl_pct / 100) - pos_size * 0.0004 * 2
                    
                    all_trades.append({
                        "symbol": sym,
                        "pnl_pct": pnl_pct,
                        "pnl_usd": pnl_usd,
                        "peak_pnl": peak_pnl,
                        "holding": holding,
                        "reason": exit_reason,
                    })
                    in_pos = False
    
    # 统计
    all_trades.sort(key=lambda x: x["pnl_usd"], reverse=True)
    
    capital = 1000
    peak = capital
    max_dd = 0
    active = 0
    
    for t in all_trades:
        if active >= 3: active -= 1
        capital += t["pnl_usd"]
        peak = max(peak, capital)
        dd = (peak - capital) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        active += 1
    
    wins = [t for t in all_trades if t["pnl_usd"] > 0]
    losses = [t for t in all_trades if t["pnl_usd"] <= 0]
    
    # 计算平均峰值 (衡量"赚到多少")
    avg_peak = sum(t["peak_pnl"] for t in all_trades) / len(all_trades) if all_trades else 0
    avg_realized = sum(t["pnl_pct"] for t in all_trades) / len(all_trades) if all_trades else 0
    capture_rate = avg_realized / avg_peak * 100 if avg_peak > 0 else 0
    
    return {
        "final": round(capital, 2),
        "return_pct": round((capital / 1000 - 1) * 100, 2),
        "trades": len(all_trades),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "avg_win": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else 0,
        "pf": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)), 2) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0,
        "max_dd": round(max_dd * 100, 2),
        "avg_peak": round(avg_peak, 2),
        "avg_realized": round(avg_realized, 2),
        "capture_rate": round(capture_rate, 1),
        "trades_detail": all_trades,
    }


def main():
    symbols = get_symbols()
    
    print(f"\n{'='*150}")
    print("🔥 移动止盈策略回测 - 基于妖币数据")
    print(f"{'='*150}")
    print(f"📊 测试 {len(symbols)} 个币种 | 10天数据 | 入场阈值55分")
    print(f"{'='*150}")
    
    strategies = [
        ("固定15%", exit_fixed_tp, {"tp": 0.15}),
        ("固定20%", exit_fixed_tp, {"tp": 0.20}),
        ("固定25%", exit_fixed_tp, {"tp": 0.25}),
        ("移动A: 10%启动/5%回撤", exit_trailing_simple, {"activate": 10, "trail": 5}),
        ("移动B: 15%启动/8%回撤", exit_trailing_simple, {"activate": 15, "trail": 8}),
        ("移动C: 20%启动/10%回撤", exit_trailing_simple, {"activate": 20, "trail": 10}),
        ("移动D: 10%启动/3%回撤", exit_trailing_simple, {"activate": 10, "trail": 3}),
        ("移动E: 15%启动/5%回撤", exit_trailing_simple, {"activate": 15, "trail": 5}),
        ("锁利A: 10%后锁+5%", exit_trailing_lock, {"activate": 10, "lock_at": 5}),
        ("锁利B: 15%后锁+8%", exit_trailing_lock, {"activate": 15, "lock_at": 8}),
        ("锁利C: 20%后锁+10%", exit_trailing_lock, {"activate": 20, "lock_at": 10}),
        ("分段止盈", exit_staged, {}),
        ("时间+涨幅", exit_time_peak, {}),
        ("OI衰减+涨幅", exit_oi_peak, {}),
        ("自适应止盈", exit_adaptive, {}),
    ]
    
    results = []
    for name, fn, params in strategies:
        r = backtest_strategy(symbols, fn, params)
        r["name"] = name
        r["params"] = params
        results.append(r)
    
    # 按收益排序
    results.sort(key=lambda x: x["return_pct"], reverse=True)
    
    print(f"\n{'#':<3} {'策略':<26} {'收益%':>8} {'交易':>5} {'胜率':>6} {'盈亏比':>6} {'回撤%':>7} {'均峰值%':>8} {'均实现%':>8} {'捕获率%':>8}")
    print("-" * 120)
    
    for i, r in enumerate(results, 1):
        c = "🟢" if r["return_pct"] > 200 else "🔵" if r["return_pct"] > 100 else "🟡" if r["return_pct"] > 0 else "🔴"
        print(f"{c}{i:<2} {r['name']:<26} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {r['avg_peak']:>+7.2f}% {r['avg_realized']:>+7.2f}% {r['capture_rate']:>7.1f}%")
    
    # 最优策略详情
    best = results[0]
    print(f"\n{'='*120}")
    print(f"🏆 最优策略: {best['name']}")
    print(f"{'='*120}")
    print(f"  参数: {best['params']}")
    print(f"  收益: {best['return_pct']:+.2f}% ({best['final']:.2f}U)")
    print(f"  交易: {best['trades']}笔 | 胜率: {best['win_rate']}% | 盈亏比: {best['pf']}")
    print(f"  回撤: {best['max_dd']:.2f}%")
    print(f"  平均峰值: {best['avg_peak']:+.2f}% | 平均实现: {best['avg_realized']:+.2f}% | 捕获率: {best['capture_rate']}%")
    
    # 对比: 最高捕获率
    best_capture = max(results, key=lambda x: x["capture_rate"])
    print(f"\n📊 最高捕获率: {best_capture['name']} ({best_capture['capture_rate']}%)")
    
    # TOP 5 盈利交易
    print(f"\n📋 最优策略 TOP 10 盈利交易:")
    print("-" * 100)
    for t in sorted(best["trades_detail"], key=lambda x: x["pnl_usd"], reverse=True)[:10]:
        print(f"  🟢 {t['symbol']:<14} 收益:{t['pnl_pct']:>+6.2f}% 峰值:{t['peak_pnl']:>+6.2f}% 持仓:{t['holding']}h | {t['reason']}")
    
    # TOP 5 亏损交易
    print(f"\n📋 最优策略 TOP 5 亏损交易:")
    print("-" * 100)
    for t in sorted(best["trades_detail"], key=lambda x: x["pnl_usd"])[:5]:
        print(f"  🔴 {t['symbol']:<14} 收益:{t['pnl_pct']:>+6.2f}% 峰值:{t['peak_pnl']:>+6.2f}% 持仓:{t['holding']}h | {t['reason']}")
    
    print(f"\n{'='*120}")
    print("⚠️ 回测仅供参考，不代表未来收益。")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
