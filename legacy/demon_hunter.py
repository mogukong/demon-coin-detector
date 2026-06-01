#!/usr/bin/env python3
"""
🔥 妖币猎手策略 - Demon Coin Hunter
=====================================
基于 RIVER/RAVE/BSB/LAB/BEAT/FIGHT 等妖币DNA提取的核心规律:

核心洞察:
  前中期: OI + Vol 才是重点 (交易兴趣 + 换手)
  后半段: Price + MCap 才重要 (派发阶段，风险倍增)

Phase 2 (拉升期) 特征:
  - OI 增速: ≥0.66%/h 持续 3+h
  - 成交量: ≥3.6x 基线
  - 价格增速: ≥37 bps/h
  - 持续时间: 中位16h (7-42h)
  - 总涨幅: 中位12.4%

入场时机: Phase 2 第2小时
出场时机: Phase 3 开始 (OI下降 + 成交量萎缩)
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


def calc_baseline_volumes(klines, window=48):
    """计算成交量基线 (48小时滑动平均)"""
    volumes = [k["quote_vol"] for k in klines]
    baselines = []
    for i in range(len(volumes)):
        start = max(0, i - window)
        baselines.append(sum(volumes[start:i]) / max(1, i - start))
    return baselines


def detect_phase(indicators, baselines, i, params):
    """
    检测当前所处阶段:
    - Phase 1 (蓄力): OI平/降, 成交量正常, 价格平
    - Phase 2 (拉升): OI加速↑, 成交量暴增, 价格涨
    - Phase 3 (派发): OI降, 成交量萎缩, 价格见顶
    """
    if i < 6:
        return "unknown", 0
    
    d = indicators[i]
    if not d:
        return "unknown", 0
    
    # 计算滚动指标
    oi_changes = []
    vol_ratios = []
    price_changes = []
    
    lookback = min(6, i)
    for j in range(i - lookback, i + 1):
        if indicators[j]:
            oi_changes.append(indicators[j]["oi_chg_1h"])
            vol_ratios.append(indicators[j]["vol_ratio"])
            price_changes.append(indicators[j]["chg_1h"])
    
    if not oi_changes:
        return "unknown", 0
    
    avg_oi_chg = sum(oi_changes) / len(oi_changes)
    avg_vol_ratio = sum(vol_ratios) / len(vol_ratios)
    avg_price_chg = sum(price_changes) / len(price_changes)
    
    # 连续OI上涨小时数
    oi_up_streak = 0
    for j in range(i, max(0, i - 10), -1):
        if indicators[j] and indicators[j]["oi_chg_1h"] > 0:
            oi_up_streak += 1
        else:
            break
    
    # Phase 2 检测
    phase2_score = 0
    
    # OI加速 (核心信号)
    if avg_oi_chg >= params["oi_th"]:
        phase2_score += 40
    elif avg_oi_chg >= params["oi_th"] * 0.7:
        phase2_score += 25
    
    # OI连续上涨
    if oi_up_streak >= 3:
        phase2_score += 20
    elif oi_up_streak >= 2:
        phase2_score += 10
    
    # 成交量放大
    if avg_vol_ratio >= params["vol_th"]:
        phase2_score += 25
    elif avg_vol_ratio >= params["vol_th"] * 0.7:
        phase2_score += 15
    
    # 价格配合
    if avg_price_chg >= params["price_th"]:
        phase2_score += 15
    elif avg_price_chg > 0:
        phase2_score += 8
    
    # Phase 3 检测 (派发)
    is_phase3 = False
    # OI开始下降 + 价格在高位
    if i >= 12:
        recent_oi_chg = sum(indicators[j]["oi_chg_1h"] for j in range(i-2, i+1) if indicators[j]) / 3
        earlier_oi_chg = sum(indicators[j]["oi_chg_1h"] for j in range(i-6, i-3) if indicators[j]) / 3
        
        if recent_oi_chg < earlier_oi_chg * 0.3 and avg_vol_ratio < params["vol_th"] * 0.6:
            is_phase3 = True
    
    if is_phase3:
        return "phase3", 0
    elif phase2_score >= params["entry_score"]:
        return "phase2", phase2_score
    else:
        return "phase1", 0


def run_demon_hunter(symbols, params, config):
    """妖币猎手回测"""
    all_trades = []
    
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 50:
            continue
        
        baselines = calc_baseline_volumes(klines, 48)
        
        # 计算指标
        indicators = []
        for i in range(len(klines)):
            if i < 2:
                indicators.append(None)
                continue
            
            close = klines[i]["close"]
            prev_close = klines[i-1]["close"]
            chg_1h = (close / prev_close - 1) * 100 if prev_close > 0 else 0
            
            oi_now = oi_map.get(klines[i]["time"], 0)
            oi_prev = oi_map.get(klines[i-1]["time"], 0)
            oi_chg_1h = (oi_now / oi_prev - 1) * 100 if oi_prev > 0 else 0
            
            vol_ratio = klines[i]["quote_vol"] / baselines[i] if baselines[i] > 0 else 1
            
            indicators.append({
                "close": close, "chg_1h": chg_1h,
                "oi_chg_1h": oi_chg_1h, "vol_ratio": vol_ratio,
                "time": klines[i]["time"],
            })
        
        # 交易逻辑
        in_position = False
        entry_price = 0
        entry_time = 0
        entry_score = 0
        phase2_hours = 0
        peak_price = 0
        
        for i in range(6, len(indicators)):
            d = indicators[i]
            if not d:
                continue
            
            phase, score = detect_phase(indicators, baselines, i, params)
            
            if not in_position:
                # 入场: Phase 2 确认
                if phase == "phase2" and score >= params["entry_score"]:
                    entry_price = d["close"]
                    entry_time = d["time"]
                    entry_score = score
                    phase2_hours = 0
                    peak_price = d["close"]
                    in_position = True
            else:
                phase2_hours += 1
                peak_price = max(peak_price, d["close"])
                
                current_pnl = (d["close"] - entry_price) / entry_price
                
                # 出场逻辑
                exit_reason = None
                exit_price = d["close"]
                
                # 止损
                if current_pnl <= -config["sl"]:
                    exit_reason = "止损"
                    exit_price = entry_price * (1 - config["sl"])
                
                # 止盈
                elif current_pnl >= config["tp"]:
                    exit_reason = "止盈"
                    exit_price = entry_price * (1 + config["tp"])
                
                # Phase 3 检测 (派发阶段)
                elif phase == "phase3":
                    exit_reason = "派发"
                
                # OI开始下降 (从峰值回落)
                elif phase2_hours >= 3 and d["oi_chg_1h"] < -0.5:
                    exit_reason = "OI衰减"
                
                # 成交量萎缩
                elif phase2_hours >= 3 and d["vol_ratio"] < params["vol_th"] * 0.4:
                    exit_reason = "量缩"
                
                # 最大持仓时间
                elif phase2_hours >= config["max_hold"]:
                    exit_reason = "超时"
                
                # 从高点回撤
                elif peak_price > entry_price * 1.05:
                    drawdown_from_peak = (peak_price - d["close"]) / peak_price
                    if drawdown_from_peak > 0.05:
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
                        "phase2_hours": phase2_hours,
                        "peak_price": peak_price,
                        "peak_gain": (peak_price / entry_price - 1) * 100,
                    })
                    in_position = False
    
    all_trades.sort(key=lambda x: x["entry_time"])
    
    # 资金曲线
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
        "avg_hold": round(sum(t["phase2_hours"] for t in all_trades) / len(all_trades), 1) if all_trades else 0,
        "avg_peak_gain": round(sum(t["peak_gain"] for t in all_trades) / len(all_trades), 2) if all_trades else 0,
        "trades_detail": all_trades,
    }


def main():
    symbols = get_symbols()
    
    base_config = {
        "capital": 1000, "leverage": 10, "pos_pct": 0.5,
        "max_pos": 3, "fee": 0.0004,
    }
    
    # 基于妖币DNA的参数组合
    param_sets = [
        {
            "name": "DNA标准",
            "params": {"oi_th": 0.66, "vol_th": 3.6, "price_th": 0.37, "entry_score": 60},
            "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24},
        },
        {
            "name": "DNA激进",
            "params": {"oi_th": 0.5, "vol_th": 2.5, "price_th": 0.25, "entry_score": 55},
            "exit": {"sl": 0.06, "tp": 0.12, "max_hold": 18},
        },
        {
            "name": "DNA保守",
            "params": {"oi_th": 0.8, "vol_th": 4.0, "price_th": 0.4, "entry_score": 70},
            "exit": {"sl": 0.10, "tp": 0.20, "max_hold": 36},
        },
        {
            "name": "OI主导",
            "params": {"oi_th": 0.5, "vol_th": 2.0, "price_th": 0.2, "entry_score": 50},
            "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24},
        },
        {
            "name": "Vol主导",
            "params": {"oi_th": 0.8, "vol_th": 2.5, "price_th": 0.3, "entry_score": 55},
            "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24},
        },
        {
            "name": "快进快出",
            "params": {"oi_th": 0.66, "vol_th": 3.6, "price_th": 0.37, "entry_score": 55},
            "exit": {"sl": 0.05, "tp": 0.10, "max_hold": 12},
        },
        {
            "name": "长持",
            "params": {"oi_th": 0.66, "vol_th": 3.0, "price_th": 0.3, "entry_score": 55},
            "exit": {"sl": 0.10, "tp": 0.25, "max_hold": 48},
        },
        {
            "name": "高阈值",
            "params": {"oi_th": 1.0, "vol_th": 5.0, "price_th": 0.5, "entry_score": 75},
            "exit": {"sl": 0.08, "tp": 0.15, "max_hold": 24},
        },
    ]
    
    print(f"\n{'='*140}")
    print("🔥 妖币猎手策略 - 基于妖币DNA回测")
    print(f"{'='*140}")
    print("核心逻辑: OI + Vol 是重点 (前中期)，Price + MCap 是派发信号 (后半段)")
    print(f"  • Phase 2 入场: OI加速 ≥0.66%/h + Vol ≥3.6x + Price涨")
    print(f"  • Phase 3 出场: OI下降 + Vol萎缩 = 派发阶段")
    print(f"  • 本金: 1000U | 杠杆: 10x | 仓位: 50%")
    print(f"  • 币种: {len(symbols)} 个")
    print(f"{'='*140}")
    
    results = []
    for ps in param_sets:
        config = {**base_config, **ps["exit"]}
        result = run_demon_hunter(symbols, ps["params"], config)
        result["name"] = ps["name"]
        result["params"] = ps["params"]
        result["exit_cfg"] = ps["exit"]
        results.append(result)
        print(f"  ✅ {ps['name']:<10} | 收益 {result['return_pct']:>+7.2f}% | {result['trades']}笔 | 胜率{result['win_rate']}%")
    
    # 排序
    results.sort(key=lambda x: x["return_pct"], reverse=True)
    
    print(f"\n{'='*140}")
    print("📊 妖币猎手策略对比")
    print(f"{'='*140}")
    print(f"{'#':<3} {'策略':<10} {'最终资金':>10} {'收益%':>8} {'交易':>5} {'胜率':>6} {'均赢':>8} {'均亏':>8} {'盈亏比':>6} {'回撤%':>7} {'均持仓h':>8} {'均峰值%':>8}")
    print("-" * 140)
    
    for i, r in enumerate(results, 1):
        c = "🟢" if r["return_pct"] > 100 else "🔵" if r["return_pct"] > 50 else "🟡" if r["return_pct"] > 0 else "🔴"
        print(f"{c}{i:<2} {r['name']:<10} {r['final']:>10.2f} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['avg_win']:>+8.2f} {r['avg_loss']:>+8.2f} {r['pf']:>6.2f} {r['max_dd']:>6.2f}% {r['avg_hold']:>8.1f} {r['avg_peak_gain']:>+7.2f}%")
    
    # 最佳策略详情
    best = results[0]
    print(f"\n{'='*140}")
    print(f"🏆 最佳策略: {best['name']}")
    print(f"{'='*140}")
    print(f"  入场参数: OI≥{best['params']['oi_th']}%/h | Vol≥{best['params']['vol_th']}x | Score≥{best['params']['entry_score']}")
    print(f"  出场参数: SL{best['exit_cfg']['sl']*100}% | TP{best['exit_cfg']['tp']*100}% | Max{best['exit_cfg']['max_hold']}h")
    print(f"  ---")
    print(f"  1000U → {best['final']}U ({best['return_pct']:+.2f}%)")
    print(f"  {best['trades']}笔 | 胜率{best['win_rate']}% | 盈亏比{best['pf']} | 回撤{best['max_dd']}%")
    print(f"  平均持仓{best['avg_hold']}h | 平均峰值收益{best['avg_peak_gain']:+.2f}%")
    
    # 交易记录
    print(f"\n📋 {best['name']} 交易记录 (前20笔):")
    print("-" * 140)
    print(f"{'币种':<14} {'入场':>12} {'出场':>12} {'入场价':>10} {'出场价':>10} {'PnL%':>7} {'PnL USD':>10} {'原因':>6} {'持仓h':>5} {'峰值%':>7}")
    print("-" * 140)
    
    for t in best["trades_detail"][:20]:
        c = "🟢" if t["pnl_usd"] > 0 else "🔴"
        et = datetime.fromtimestamp(t["entry_time"]/1000).strftime("%m-%d %H:%M")
        xt = datetime.fromtimestamp(t["exit_time"]/1000).strftime("%m-%d %H:%M")
        print(f"{c}{t['symbol']:<13} {et:>12} {xt:>12} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+6.2f}% {t['pnl_usd']:>+10.2f} {t['reason']:>6} {t['phase2_hours']:>5} {t['peak_gain']:>+6.2f}%")
    
    # 出场原因分析
    print(f"\n📊 出场原因分析 ({best['name']}):")
    print("-" * 60)
    reason_stats = {}
    for t in best["trades_detail"]:
        r = t["reason"]
        if r not in reason_stats:
            reason_stats[r] = {"count": 0, "pnl": 0, "wins": 0}
        reason_stats[r]["count"] += 1
        reason_stats[r]["pnl"] += t["pnl_usd"]
        if t["pnl_usd"] > 0:
            reason_stats[r]["wins"] += 1
    
    for reason, stats in sorted(reason_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        c = "🟢" if stats["pnl"] > 0 else "🔴"
        print(f"  {c} {reason:<8} {stats['count']:>3}笔 | 胜率{wr:>5.1f}% | 总PnL {stats['pnl']:>+10.2f}U")
    
    print(f"\n{'='*140}")
    print("⚠️ 回测结果仅供参考，不代表未来收益。合约交易具有高风险。")
    print(f"{'='*140}")


if __name__ == "__main__":
    main()
