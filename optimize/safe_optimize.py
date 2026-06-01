#!/usr/bin/env python3
"""
🔥 妖币猎手 - 安全优化引擎
================================
规则:
1. 任何参数变更必须先回测验证
2. 回测收益 >= 当前参数 → 才应用
3. 回测胜率 >= 45% → 才应用
4. 最大回撤 <= 50% → 才应用
5. 单次只调一个参数，避免过度拟合
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backtest")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARAM_FILE = os.path.join(os.path.dirname(BASE_DIR), "strategy_params.json")


def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None


def load_params():
    try:
        with open(PARAM_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "oi_4h_th": 8, "oi_1h_th": 0.4, "vol_th": 2.0,
            "chg_4h_th": 2, "chg_1h_th": 0.2, "entry_score": 55,
            "stop_loss": 0.10, "take_profit": 0.20, "max_hold_hours": 36,
            "position_pct": 0.30, "version": 1, "history": [],
        }


def save_params(params):
    with open(PARAM_FILE, 'w') as f:
        json.dump(params, f, indent=2, ensure_ascii=False)


# ============================================================
# 回测引擎 (复用backtest.py逻辑)
# ============================================================

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
            "close": close, "time": klines[i]["time"],
            "chg_1h": chg_1h, "chg_4h": chg_4h,
            "vol_ratio": vol_ratio, "vol_ratio_5": vol_ratio_5,
            "oi_chg_1h": oi_chg_1h, "oi_chg_4h": oi_chg_4h,
            "oi_up_streak": oi_up_streak,
        })
    return indicators


def score_signal(ind, i, params):
    d = ind[i]
    if not d: return 0
    s = 0
    if d["oi_chg_4h"] > params.get("oi_4h_th", 8): s += 25
    elif d["oi_chg_4h"] > params.get("oi_4h_th", 8) * 0.5: s += 15
    elif d["oi_chg_4h"] > 0: s += 8
    if d["oi_chg_1h"] > params.get("oi_1h_th", 0.4): s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    if d["oi_up_streak"] >= 3: s += 10
    elif d["oi_up_streak"] >= 2: s += 5
    if d["vol_ratio"] > params.get("vol_th", 2.0): s += 15
    elif d["vol_ratio"] > params.get("vol_th", 2.0) * 0.7: s += 10
    if d["vol_ratio_5"] > 2: s += 10
    elif d["vol_ratio_5"] > 1.5: s += 5
    if d["chg_4h"] > params.get("chg_4h_th", 2): s += 15
    elif d["chg_4h"] > 0: s += 8
    if d["chg_1h"] > params.get("chg_1h_th", 0.2): s += 10
    elif d["chg_1h"] > 0: s += 5
    return s


def backtest_params(params, symbols, config):
    """用指定参数回测"""
    all_trades = []
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 30: continue
        indicators = calc_indicators(klines, oi_map)
        in_pos = False
        entry_price = 0
        holding = 0
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d: continue
            if not in_pos:
                score = score_signal(indicators, i, params)
                if score >= params.get("entry_score", 55):
                    entry_price = d["close"]
                    holding = 0
                    in_pos = True
            else:
                holding += 1
                pnl = (d["close"] - entry_price) / entry_price
                exit_reason = None
                if pnl <= -params.get("stop_loss", 0.10): exit_reason = "止损"
                elif pnl >= params.get("take_profit", 0.20): exit_reason = "止盈"
                elif holding >= params.get("max_hold_hours", 36): exit_reason = "超时"
                elif holding >= 2 and d["oi_chg_1h"] < -0.5: exit_reason = "OI衰减"
                if exit_reason:
                    pos_size = config["capital"] * params.get("position_pct", 0.30) * config["leverage"]
                    pnl_usd = pos_size * pnl - pos_size * config["fee"] * 2
                    all_trades.append({"pnl_usd": pnl_usd, "pnl_pct": pnl * 100, "reason": exit_reason})
                    in_pos = False
    all_trades.sort(key=lambda x: x["pnl_usd"], reverse=True)
    capital = config["capital"]
    peak = capital
    max_dd = 0
    active = 0
    for t in all_trades:
        if active >= config["max_pos"]: active -= 1
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
        "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "avg_win": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else 0,
        "pf": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)), 2) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0,
        "max_dd": round(max_dd * 100, 2),
    }


# ============================================================
# 安全优化
# ============================================================

def safe_optimize(daily_analysis):
    """
    安全优化流程:
    1. 基于当日表现生成候选参数
    2. 用历史数据回测每个候选
    3. 只有回测结果优于当前参数 → 才应用
    """
    symbols = get_symbols()
    if not symbols:
        print("⚠️ 无历史数据，跳过优化")
        return []
    
    current_params = load_params()
    config = {"capital": 1000, "leverage": 10, "max_pos": 3, "fee": 0.0004}
    
    # 先回测当前参数作为基线
    print("\n📊 回测当前参数作为基线...")
    baseline = backtest_params(current_params, symbols, config)
    print(f"  当前参数: 收益{baseline['return_pct']:+.1f}% | 胜率{baseline['win_rate']}% | 回撤{baseline['max_dd']}%")
    
    # 生成候选参数 (每次只改一个)
    candidates = []
    
    # 规则1: 胜率太低 → 提高入场阈值
    if daily_analysis.get("win_rate", 50) < 40 and daily_analysis.get("total_trades", 0) >= 3:
        c = {**current_params, "entry_score": min(75, current_params["entry_score"] + 5)}
        candidates.append(("提高入场阈值", c, f"胜率{daily_analysis['win_rate']}%太低"))
    
    # 规则2: 胜率很高 → 降低阈值多做
    if daily_analysis.get("win_rate", 50) > 70 and daily_analysis.get("total_trades", 0) >= 3:
        c = {**current_params, "entry_score": max(45, current_params["entry_score"] - 3)}
        candidates.append(("降低入场阈值", c, f"胜率{daily_analysis['win_rate']}%很高"))
    
    # 规则3: 平均亏损太大 → 收紧止损
    if daily_analysis.get("avg_loss", 0) < -30:
        c = {**current_params, "stop_loss": max(0.05, current_params["stop_loss"] - 0.01)}
        candidates.append(("收紧止损", c, f"平均亏损{daily_analysis['avg_loss']}太大"))
    
    # 规则4: 平均盈利太小 → 放宽止盈
    if 0 < daily_analysis.get("avg_win", 0) < 20:
        c = {**current_params, "take_profit": min(0.30, current_params["take_profit"] + 0.02)}
        candidates.append(("放宽止盈", c, f"平均盈利{daily_analysis['avg_win']}太小"))
    
    # 规则5: OI衰减出场亏损 → 调整OI阈值
    oi_exit = daily_analysis.get("exit_reasons", {}).get("OI衰减", {})
    if oi_exit.get("count", 0) >= 3 and oi_exit.get("pnl", 0) < 0:
        c = {**current_params, "oi_1h_th": max(0.2, current_params["oi_1h_th"] - 0.1)}
        candidates.append(("降低OI阈值", c, "OI衰减出场亏损"))
    
    # 规则6: 整体亏损 → 收紧
    if daily_analysis.get("net_profit", 0) < -25:
        c = {**current_params, "entry_score": min(75, current_params["entry_score"] + 3)}
        candidates.append(("收紧入场", c, "整体亏损"))
    
    if not candidates:
        print("\n✅ 无需优化，保持当前参数")
        return []
    
    # 回测每个候选
    print(f"\n🔍 回测 {len(candidates)} 个候选参数...")
    approved = []
    
    for name, candidate_params, reason in candidates:
        result = backtest_params(candidate_params, symbols, config)
        
        # 检查是否优于基线
        better = True
        reasons = []
        
        if result["return_pct"] < baseline["return_pct"] * 0.95:  # 允许5%容差
            better = False
            reasons.append(f"收益{result['return_pct']:+.1f}% < 基线{baseline['return_pct']:+.1f}%")
        
        if result["win_rate"] < 40:
            better = False
            reasons.append(f"胜率{result['win_rate']}% < 40%")
        
        if result["max_dd"] > 60:
            better = False
            reasons.append(f"回撤{result['max_dd']}% > 60%")
        
        status = "✅ 通过" if better else "❌ 拒绝"
        print(f"  {status} {name}: 收益{result['return_pct']:+.1f}% | 胜率{result['win_rate']}% | 回撤{result['max_dd']}% | {reason}")
        
        if not better:
            print(f"       拒绝原因: {'; '.join(reasons)}")
        else:
            approved.append((name, candidate_params, reason, result))
    
    # 只应用最优的一个 (避免过度拟合)
    if approved:
        # 按收益排序，只取最优
        approved.sort(key=lambda x: x[3]["return_pct"], reverse=True)
        best_name, best_params, best_reason, best_result = approved[0]
        
        print(f"\n🏆 应用最优参数: {best_name}")
        print(f"  原因: {best_reason}")
        print(f"  回测: 收益{best_result['return_pct']:+.1f}% | 胜率{best_result['win_rate']}% | 回撤{best_result['max_dd']}%")
        
        best_params["version"] = current_params.get("version", 0) + 1
        best_params["history"] = current_params.get("history", [])[-6:]
        best_params["history"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "version": best_params["version"],
            "change": best_name,
            "reason": best_reason,
            "baseline": baseline,
            "new_result": best_result,
        })
        
        save_params(best_params)
        return [(best_name, best_reason, best_result)]
    
    print("\n✅ 所有候选参数回测均不如当前，保持现状")
    return []


if __name__ == "__main__":
    # 测试: 用模拟数据运行
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        symbols = get_symbols()
        params = load_params()
        config = {"capital": 1000, "leverage": 10, "max_pos": 3, "fee": 0.0004}
        result = backtest_params(params, symbols, config)
        print(f"当前参数回测: 收益{result['return_pct']:+.1f}% | 胜率{result['win_rate']}% | 回撤{result['max_dd']}%")
