#!/usr/bin/env python3
"""
🔥 大行情止盈策略回测
======================
目标: 吃到10倍、50倍的大行情
核心: 没有硬止盈上限，移动止盈随利润放大而放宽

测试策略:
1. 无上限+自适应移动 (利润越大，允许回撤越大)
2. 无上限+固定比例移动
3. 无上限+OI衰减出场
4. 无上限+时间衰减
5. 组合策略
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
    return [{"time": d[0], "open": float(d[1]), "high": float(d[2]),
             "low": float(d[3]), "close": float(d[4]),
             "quote_vol": float(d[7]), "trades": int(d[8])} for d in data]


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
            if prev_oi > 0 and curr_oi > prev_oi: oi_up_streak += 1
            else: break
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
# 大行情止盈策略
# ============================================================

def exit_adaptive_no_cap(pnl_pct, peak_pnl, holding, d, params):
    """自适应移动止盈 (无硬上限) - 利润越大允许回撤越大"""
    sl = params.get("sl", 0.10)
    max_hold = params.get("max_hold", 72)  # 给更长时间
    
    if pnl_pct <= -sl:
        return "止损"
    if holding >= max_hold:
        return "超时"
    
    # 自适应回撤容忍度
    if peak_pnl >= 200:
        trail = 0.20     # 涨200%后允许回撤20%
    elif peak_pnl >= 100:
        trail = 0.15     # 涨100%后允许回撤15%
    elif peak_pnl >= 50:
        trail = 0.10     # 涨50%后允许回撤10%
    elif peak_pnl >= 30:
        trail = 0.07     # 涨30%后允许回撤7%
    elif peak_pnl >= 15:
        trail = 0.05     # 涨15%后允许回撤5%
    elif peak_pnl >= 10:
        trail = 0.03     # 涨10%后允许回撤3%
    else:
        trail = 999      # 未激活
    
    if peak_pnl >= 10 and (peak_pnl - pnl_pct) >= trail:
        return f"自适应(峰{peak_pnl:.0f}%回撤{peak_pnl-pnl_pct:.0f}%)"
    
    return None


def exit_wide_trail(pnl_pct, peak_pnl, holding, d, params):
    """宽移动止盈 (无硬上限) - 固定10%回撤"""
    sl = params.get("sl", 0.10)
    
    if pnl_pct <= -sl:
        return "止损"
    
    # 涨超过15%后，从峰值回撤10%则平
    if peak_pnl >= 15 and (peak_pnl - pnl_pct) >= 10:
        return f"宽移动(峰{peak_pnl:.0f}%→{pnl_pct:.0f}%)"
    
    return None


def exit_oi_driven(pnl_pct, peak_pnl, holding, d, params):
    """OI驱动出场 (无硬上限) - OI下降+已盈利则平"""
    sl = params.get("sl", 0.10)
    
    if pnl_pct <= -sl:
        return "止损"
    
    # OI连续下降2小时 + 已经盈利超过5%
    if d and holding >= 2 and pnl_pct >= 5:
        if d.get("oi_chg_1h", 0) < -0.5:
            return f"OI衰减({pnl_pct:.0f}%)"
    
    # 从峰值大幅回撤 (作为安全网)
    if peak_pnl >= 30 and (peak_pnl - pnl_pct) >= 15:
        return f"大幅回撤(峰{peak_pnl:.0f}%)"
    if peak_pnl >= 10 and (peak_pnl - pnl_pct) >= 8:
        return f"回撤(峰{peak_pnl:.0f}%)"
    
    return None


def exit_hybrid_no_cap(pnl_pct, peak_pnl, holding, d, params):
    """混合策略 (无硬上限) - 自适应+OI+时间"""
    sl = params.get("sl", 0.10)
    max_hold = params.get("max_hold", 72)
    
    if pnl_pct <= -sl:
        return "止损"
    if holding >= max_hold and pnl_pct < 5:
        return "超时(亏损)"
    if holding >= 120:
        return "超时(120h)"
    
    # 自适应回撤
    if peak_pnl >= 100:
        trail = 0.18
    elif peak_pnl >= 50:
        trail = 0.12
    elif peak_pnl >= 30:
        trail = 0.08
    elif peak_pnl >= 15:
        trail = 0.05
    elif peak_pnl >= 10:
        trail = 0.03
    else:
        trail = 999
    
    # OI衰减 (只有在盈利时才触发)
    if d and holding >= 3 and pnl_pct >= 10:
        if d.get("oi_chg_1h", 0) < -0.8:
            return f"OI衰减({pnl_pct:.0f}%)"
    
    # 自适应回撤
    if peak_pnl >= 10 and (peak_pnl - pnl_pct) >= trail:
        return f"自适应(峰{peak_pnl:.0f}%回撤{peak_pnl-pnl_pct:.0f}%)"
    
    return None


def exit_momentum_break(pnl_pct, peak_pnl, holding, d, params):
    """动量衰竭出场 - 价格上涨动力消失"""
    sl = params.get("sl", 0.10)
    
    if pnl_pct <= -sl:
        return "止损"
    
    # 涨超过20%后，连续2小时价格下跌
    if peak_pnl >= 20 and d:
        if d.get("chg_1h", 0) < -2 and holding >= 3:
            return f"动量衰竭({pnl_pct:.0f}%)"
    
    # 自适应回撤
    if peak_pnl >= 50:
        trail = 0.15
    elif peak_pnl >= 20:
        trail = 0.08
    elif peak_pnl >= 10:
        trail = 0.04
    else:
        trail = 999
    
    if peak_pnl >= 10 and (peak_pnl - pnl_pct) >= trail:
        return f"动量回撤(峰{peak_pnl:.0f}%)"
    
    return None


# ============================================================
# 回测引擎
# ============================================================

def backtest(symbols, exit_fn, exit_params, entry_score=55):
    base_params = {"sl": 0.10, "max_hold": 72}
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
                high_pnl = (d["high"] - entry_price) / entry_price * 100
                peak_pnl = max(peak_pnl, pnl_pct, high_pnl)
                
                exit_reason = exit_fn(pnl_pct, peak_pnl, holding, d, all_params)
                
                if exit_reason:
                    pos_size = 1000 * 0.30 * 10
                    pnl_usd = pos_size * (pnl_pct / 100) - pos_size * 0.0004 * 2
                    all_trades.append({
                        "symbol": sym, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
                        "peak_pnl": peak_pnl, "holding": holding, "reason": exit_reason,
                    })
                    in_pos = False
    
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
    avg_peak = sum(t["peak_pnl"] for t in all_trades) / len(all_trades) if all_trades else 0
    avg_realized = sum(t["pnl_pct"] for t in all_trades) / len(all_trades) if all_trades else 0
    capture = avg_realized / avg_peak * 100 if avg_peak > 0 else 0
    
    # 找最大单笔盈利
    max_trade = max(all_trades, key=lambda x: x["pnl_usd"]) if all_trades else {"pnl_usd": 0, "symbol": "N/A", "pnl_pct": 0}
    
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
        "capture_rate": round(capture, 1),
        "max_trade_pnl": round(max_trade["pnl_usd"], 2),
        "max_trade_sym": max_trade["symbol"],
        "max_trade_pct": round(max_trade["pnl_pct"], 1),
        "trades_detail": all_trades,
    }


def main():
    symbols = get_symbols()
    
    print(f"\n{'='*150}")
    print("🔥 大行情止盈策略回测 - 目标: 吃到10倍、50倍")
    print(f"{'='*150}")
    print(f"📊 测试 {len(symbols)} 个币种 | 10天数据 | 无硬止盈上限")
    print(f"{'='*150}")
    
    strategies = [
        ("基线: 固定20%止盈", exit_adaptive_no_cap, {"sl": 0.10}),  # 用自适应但调参数
        ("A: 宽移动10%回撤", exit_wide_trail, {"sl": 0.10}),
        ("B: OI驱动出场", exit_oi_driven, {"sl": 0.10}),
        ("C: 自适应(无上限)", exit_adaptive_no_cap, {"sl": 0.10}),
        ("D: 混合(自适应+OI)", exit_hybrid_no_cap, {"sl": 0.10}),
        ("E: 动量衰竭", exit_momentum_break, {"sl": 0.10}),
        ("F: 自适应+宽松SL8%", exit_adaptive_no_cap, {"sl": 0.08}),
        ("G: 混合+长时间", exit_hybrid_no_cap, {"sl": 0.10, "max_hold": 120}),
    ]
    
    results = []
    for name, fn, params in strategies:
        r = backtest(symbols, fn, params)
        r["name"] = name
        r["params"] = params
        results.append(r)
    
    results.sort(key=lambda x: x["return_pct"], reverse=True)
    
    print(f"\n{'#':<3} {'策略':<28} {'收益%':>8} {'交易':>5} {'胜率':>6} {'盈亏比':>6} {'回撤%':>7} {'最大单笔':>10} {'捕获率':>7}")
    print("-" * 120)
    
    for i, r in enumerate(results, 1):
        c = "🟢" if r["return_pct"] > 200 else "🔵" if r["return_pct"] > 100 else "🟡" if r["return_pct"] > 0 else "🔴"
        max_str = f"{r['max_trade_sym'][:6]}{r['max_trade_pct']:+.0f}%"
        print(f"{c}{i:<2} {r['name']:<28} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {max_str:>10} {r['capture_rate']:>6.1f}%")
    
    # 最优策略详情
    best = results[0]
    print(f"\n{'='*120}")
    print(f"🏆 最优策略: {best['name']}")
    print(f"{'='*120}")
    print(f"  收益: {best['return_pct']:+.2f}% | 交易: {best['trades']}笔 | 胜率: {best['win_rate']}%")
    print(f"  最大单笔: {best['max_trade_sym']} {best['max_trade_pct']:+.1f}% ({best['max_trade_pnl']:+.2f}U)")
    print(f"  捕获率: {best['capture_rate']}% (实现了峰值利润的{best['capture_rate']}%)")
    
    # TOP 5 大行情
    print(f"\n📋 TOP 5 大行情:")
    for t in sorted(best["trades_detail"], key=lambda x: x["pnl_pct"], reverse=True)[:5]:
        print(f"  🚀 {t['symbol']:<14} 收益:{t['pnl_pct']:>+7.1f}% 峰值:{t['peak_pnl']:>+7.1f}% PnL:{t['pnl_usd']:>+8.2f}U 持仓:{t['holding']}h | {t['reason']}")
    
    print(f"\n{'='*120}")
    print("⚠️ 回测仅供参考。")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
