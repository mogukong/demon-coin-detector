#!/usr/bin/env python3
"""
🔥 动量策略优化器 - Momentum Strategy Optimizer
================================================
基于最佳策略 A_Momentum 进行多维度参数优化

优化维度:
1. 入场条件: 价格变化阈值、成交量倍数
2. 出场条件: 止损%、止盈%、持仓时间
3. 仓位管理: 仓位比例、最大持仓数
4. 组合策略: 多条件组合
"""

import json
import os
from datetime import datetime
from itertools import product

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backtest")

# ============================================================
# 数据加载 (复用)
# ============================================================

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None

def load_klines_1h(symbol):
    data = load_json(os.path.join(DATA_DIR, f"{symbol}_1h_klines.json"))
    if not data:
        return []
    return [{
        "time": d[0], "open": float(d[1]), "high": float(d[2]),
        "low": float(d[3]), "close": float(d[4]),
        "volume": float(d[5]), "quote_vol": float(d[7]), "trades": int(d[8]),
    } for d in data]

def load_oi_1h(symbol):
    data = load_json(os.path.join(DATA_DIR, f"{symbol}_oi_1h.json"))
    if not data:
        return {}
    return {int(d["timestamp"]): float(d["sumOpenInterestValue"]) for d in data}

def get_symbols():
    symbols = []
    for f in os.listdir(DATA_DIR):
        if f.endswith("_1h_klines.json"):
            symbols.append(f.replace("_1h_klines.json", ""))
    return sorted(symbols)


# ============================================================
# 技术指标
# ============================================================

def ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    m = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = (p - e) * m + e
    return e

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        c = prices[i] - prices[i-1]
        gains.append(max(0, c))
        losses.append(max(0, -c))
    if len(gains) < period:
        return 50
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def calc_all_indicators(klines, oi_map):
    """计算所有指标，返回指标数组"""
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    
    indicators = []
    for i in range(len(klines)):
        if i < 25:
            indicators.append(None)
            continue
        
        close = closes[i]
        
        # 价格变化 (多周期)
        chg_1h = (closes[i] / closes[i-1] - 1) * 100 if i >= 1 else 0
        chg_2h = (closes[i] / closes[i-2] - 1) * 100 if i >= 2 else 0
        chg_4h = (closes[i] / closes[i-4] - 1) * 100 if i >= 4 else 0
        chg_8h = (closes[i] / closes[i-8] - 1) * 100 if i >= 8 else 0
        chg_24h = (closes[i] / closes[i-24] - 1) * 100 if i >= 24 else 0
        
        # 成交量 (多周期)
        vol_avg_5 = sum(volumes[max(0,i-5):i]) / min(5, i) if i > 0 else volumes[i]
        vol_avg_10 = sum(volumes[max(0,i-10):i]) / min(10, i) if i > 0 else volumes[i]
        vol_avg_20 = sum(volumes[max(0,i-20):i]) / min(20, i) if i > 0 else volumes[i]
        
        vol_ratio_5 = volumes[i] / vol_avg_5 if vol_avg_5 > 0 else 1
        vol_ratio_10 = volumes[i] / vol_avg_10 if vol_avg_10 > 0 else 1
        vol_ratio_20 = volumes[i] / vol_avg_20 if vol_avg_20 > 0 else 1
        
        # OI
        oi_now = oi_map.get(klines[i]["time"], 0)
        oi_1h = oi_map.get(klines[i-1]["time"], 0) if i >= 1 else oi_now
        oi_2h = oi_map.get(klines[i-2]["time"], 0) if i >= 2 else oi_now
        oi_4h = oi_map.get(klines[i-4]["time"], 0) if i >= 4 else oi_now
        oi_8h = oi_map.get(klines[i-8]["time"], 0) if i >= 8 else oi_now
        oi_24h = oi_map.get(klines[i-24]["time"], 0) if i >= 24 else oi_now
        
        oi_chg_1h = (oi_now / oi_1h - 1) * 100 if oi_1h > 0 else 0
        oi_chg_2h = (oi_now / oi_2h - 1) * 100 if oi_2h > 0 else 0
        oi_chg_4h = (oi_now / oi_4h - 1) * 100 if oi_4h > 0 else 0
        oi_chg_8h = (oi_now / oi_8h - 1) * 100 if oi_8h > 0 else 0
        oi_chg_24h = (oi_now / oi_24h - 1) * 100 if oi_24h > 0 else 0
        
        # EMA
        ema_10 = ema(closes[max(0,i-10):i+1], 10)
        ema_20 = ema(closes[max(0,i-20):i+1], 20)
        
        # RSI
        rsi_7 = rsi(closes[max(0,i-7):i+1], 7)
        rsi_14 = rsi(closes[max(0,i-14):i+1], 14)
        
        # 连续涨跌
        up_streak = 0
        for j in range(i, max(0, i-5), -1):
            if closes[j] > closes[j-1]:
                up_streak += 1
            else:
                break
        
        # 波动率 (最近5根K线的ATR)
        atr = 0
        if i >= 5:
            trs = []
            for j in range(i-4, i+1):
                tr = max(
                    klines[j]["high"] - klines[j]["low"],
                    abs(klines[j]["high"] - closes[j-1]),
                    abs(klines[j]["low"] - closes[j-1])
                )
                trs.append(tr)
            atr = sum(trs) / len(trs)
        
        indicators.append({
            "close": close, "high": klines[i]["high"], "low": klines[i]["low"],
            "time": klines[i]["time"],
            "chg_1h": chg_1h, "chg_2h": chg_2h, "chg_4h": chg_4h,
            "chg_8h": chg_8h, "chg_24h": chg_24h,
            "vol_ratio_5": vol_ratio_5, "vol_ratio_10": vol_ratio_10, "vol_ratio_20": vol_ratio_20,
            "oi_chg_1h": oi_chg_1h, "oi_chg_2h": oi_chg_2h,
            "oi_chg_4h": oi_chg_4h, "oi_chg_8h": oi_chg_8h, "oi_chg_24h": oi_chg_24h,
            "ema_10": ema_10, "ema_20": ema_20,
            "rsi_7": rsi_7, "rsi_14": rsi_14,
            "up_streak": up_streak, "atr": atr,
            "atr_pct": atr / close * 100 if close > 0 else 0,
        })
    
    return indicators


# ============================================================
# 策略定义 (12种动量策略变体)
# ============================================================

def strat_momentum_v1(ind, i, params):
    """基础动量: 1h涨 + 成交量放大"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["chg_1h"] > params["chg_th"]: s += 50
    elif d["chg_1h"] > params["chg_th"] * 0.5: s += 25
    if d["vol_ratio_20"] > params["vol_th"]: s += 35
    elif d["vol_ratio_20"] > params["vol_th"] * 0.7: s += 18
    if d["close"] > d["ema_20"]: s += 15
    return s

def strat_momentum_v2(ind, i, params):
    """多周期动量: 1h+4h共振"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["chg_1h"] > params["chg_th"]: s += 25
    if d["chg_4h"] > params["chg_th"] * 2: s += 35
    elif d["chg_4h"] > params["chg_th"]: s += 20
    if d["vol_ratio_20"] > params["vol_th"]: s += 25
    if d["close"] > d["ema_20"]: s += 15
    return s

def strat_oi_momentum(ind, i, params):
    """OI驱动动量: OI暴增 + 价格涨"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["oi_chg_4h"] > params["oi_th"]: s += 35
    elif d["oi_chg_4h"] > params["oi_th"] * 0.5: s += 18
    if d["chg_1h"] > params["chg_th"]: s += 30
    elif d["chg_1h"] > 0: s += 15
    if d["vol_ratio_20"] > params["vol_th"]: s += 20
    if d["close"] > d["ema_20"]: s += 15
    return s

def strat_breakout(ind, i, params):
    """突破策略: 价格突破EMA + 放量"""
    d = ind[i]
    if not d: return 0
    prev = ind[i-1]
    if not prev: return 0
    s = 0
    # 从下方突破EMA20
    if prev["close"] < prev["ema_20"] and d["close"] > d["ema_20"]:
        s += 40
    elif d["close"] > d["ema_20"]:
        s += 20
    if d["vol_ratio_20"] > params["vol_th"]: s += 30
    elif d["vol_ratio_20"] > params["vol_th"] * 0.7: s += 15
    if d["chg_1h"] > 0: s += 15
    if d["oi_chg_1h"] > 0: s += 15
    return s

def strat_rsi_bounce(ind, i, params):
    """RSI反弹: RSI低位 + 动量恢复"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["rsi_7"] < 30: s += 35
    elif d["rsi_7"] < 40: s += 25
    elif d["rsi_7"] < 50: s += 10
    if d["chg_1h"] > params["chg_th"]: s += 30
    elif d["chg_1h"] > 0: s += 15
    if d["vol_ratio_20"] > params["vol_th"]: s += 20
    if d["oi_chg_4h"] > 0: s += 15
    return s

def strat_trend_follow(ind, i, params):
    """趋势跟随: 多周期趋势一致"""
    d = ind[i]
    if not d: return 0
    s = 0
    # 多周期趋势
    if d["chg_1h"] > 0: s += 15
    if d["chg_4h"] > 0: s += 20
    if d["chg_8h"] > 0: s += 15
    # 趋势强度
    if d["chg_1h"] > params["chg_th"]: s += 20
    if d["chg_4h"] > params["chg_th"] * 2: s += 15
    # 成交量确认
    if d["vol_ratio_20"] > params["vol_th"]: s += 15
    return s

def strat_vol_spike(ind, i, params):
    """成交量异常: 成交量暴涨 + 价格启动"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["vol_ratio_5"] > params["vol_th"] * 1.5: s += 40
    elif d["vol_ratio_5"] > params["vol_th"]: s += 25
    if d["chg_1h"] > params["chg_th"]: s += 30
    elif d["chg_1h"] > 0: s += 15
    if d["close"] > d["ema_20"]: s += 15
    if d["oi_chg_1h"] > 0: s += 15
    return s

def strat_streak_break(ind, i, params):
    """连涨接力: 连续上涨 + 放量"""
    d = ind[i]
    if not d: return 0
    s = 0
    if d["up_streak"] >= 3: s += 35
    elif d["up_streak"] >= 2: s += 20
    if d["chg_1h"] > params["chg_th"]: s += 25
    if d["vol_ratio_20"] > params["vol_th"]: s += 25
    if d["close"] > d["ema_20"]: s += 15
    return s

STRATEGIES = {
    "S1_基础动量": strat_momentum_v1,
    "S2_多周期共振": strat_momentum_v2,
    "S3_OI驱动": strat_oi_momentum,
    "S4_EMA突破": strat_breakout,
    "S5_RSI反弹": strat_rsi_bounce,
    "S6_趋势跟随": strat_trend_follow,
    "S7_量价异常": strat_vol_spike,
    "S8_连涨接力": strat_streak_break,
}


# ============================================================
# 回测引擎
# ============================================================

def backtest(symbols, strategy_fn, params, config):
    """通用回测引擎"""
    all_trades = []
    
    for sym in symbols:
        klines = load_klines_1h(sym)
        oi_map = load_oi_1h(sym)
        if len(klines) < 30:
            continue
        
        indicators = calc_all_indicators(klines, oi_map)
        
        in_pos = False
        entry_price = 0
        entry_time = 0
        entry_score = 0
        
        for i in range(25, len(indicators)):
            d = indicators[i]
            if not d:
                continue
            
            if not in_pos:
                score = strategy_fn(indicators, i, params)
                if score >= config["entry_th"]:
                    entry_price = d["close"]
                    entry_time = d["time"]
                    entry_score = score
                    in_pos = True
            else:
                pnl_pct = (d["close"] - entry_price) / entry_price
                holding_h = (d["time"] - entry_time) / 3600000
                
                exit_reason = None
                exit_price = d["close"]
                
                if pnl_pct <= -config["sl"]:
                    exit_reason = "止损"
                    exit_price = entry_price * (1 - config["sl"])
                elif pnl_pct >= config["tp"]:
                    exit_reason = "止盈"
                    exit_price = entry_price * (1 + config["tp"])
                elif holding_h >= config["max_hold"]:
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
                        "holding_h": holding_h,
                    })
                    in_pos = False
    
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
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "avg_win": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else 0,
        "max_dd": round(max_dd * 100, 2),
        "pf": round(abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)), 2) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0,
        "trades_detail": all_trades,
    }


# ============================================================
# 参数优化
# ============================================================

def optimize():
    symbols = get_symbols()
    
    # 基础配置
    base_config = {
        "capital": 1000, "leverage": 10, "pos_pct": 0.5,
        "max_pos": 3, "fee": 0.0004,
    }
    
    # 参数网格
    param_grids = {
        "S1_基础动量": [
            {"chg_th": 2, "vol_th": 1.5},
            {"chg_th": 3, "vol_th": 2.0},
            {"chg_th": 4, "vol_th": 2.5},
            {"chg_th": 2, "vol_th": 2.0},
            {"chg_th": 3, "vol_th": 1.5},
        ],
        "S2_多周期共振": [
            {"chg_th": 2, "vol_th": 1.5},
            {"chg_th": 3, "vol_th": 2.0},
            {"chg_th": 2, "vol_th": 2.0},
        ],
        "S3_OI驱动": [
            {"chg_th": 2, "oi_th": 5, "vol_th": 1.5},
            {"chg_th": 3, "oi_th": 10, "vol_th": 2.0},
            {"chg_th": 2, "oi_th": 8, "vol_th": 2.0},
        ],
        "S4_EMA突破": [
            {"vol_th": 1.5},
            {"vol_th": 2.0},
            {"vol_th": 2.5},
        ],
        "S5_RSI反弹": [
            {"chg_th": 2, "vol_th": 1.5},
            {"chg_th": 3, "vol_th": 2.0},
        ],
        "S6_趋势跟随": [
            {"chg_th": 2, "vol_th": 1.5},
            {"chg_th": 3, "vol_th": 2.0},
        ],
        "S7_量价异常": [
            {"chg_th": 2, "vol_th": 2.0},
            {"chg_th": 3, "vol_th": 2.5},
        ],
        "S8_连涨接力": [
            {"chg_th": 2, "vol_th": 1.5},
            {"chg_th": 3, "vol_th": 2.0},
        ],
    }
    
    # 出场参数网格
    exit_configs = [
        {"sl": 0.08, "tp": 0.15, "max_hold": 48, "entry_th": 60},
        {"sl": 0.06, "tp": 0.12, "max_hold": 36, "entry_th": 60},
        {"sl": 0.10, "tp": 0.20, "max_hold": 72, "entry_th": 60},
        {"sl": 0.08, "tp": 0.20, "max_hold": 48, "entry_th": 55},
        {"sl": 0.08, "tp": 0.15, "max_hold": 24, "entry_th": 65},
        {"sl": 0.05, "tp": 0.10, "max_hold": 24, "entry_th": 60},
    ]
    
    print(f"\n{'='*140}")
    print("🔥 动量策略优化器 - 全面参数搜索")
    print(f"{'='*140}")
    print(f"📊 优化维度:")
    print(f"  • 策略变体: {len(STRATEGIES)} 种")
    print(f"  • 入场参数: 每策略 2-5 组")
    print(f"  • 出场参数: {len(exit_configs)} 组 (止损/止盈/持仓时间)")
    print(f"  • 币种: {len(symbols)} 个")
    print(f"  • 本金: 1000U | 杠杆: 10x | 仓位: 50%")
    print(f"{'='*140}")
    
    all_results = []
    total_combos = sum(len(v) for v in param_grids.values()) * len(exit_configs)
    done = 0
    
    for strat_name, strategy_fn in STRATEGIES.items():
        params_list = param_grids.get(strat_name, [{"chg_th": 3, "vol_th": 2.0}])
        
        for params in params_list:
            for exit_cfg in exit_configs:
                config = {**base_config, **exit_cfg}
                result = backtest(symbols, strategy_fn, params, config)
                
                all_results.append({
                    "strategy": strat_name,
                    "params": params,
                    "exit": exit_cfg,
                    **result,
                })
                
                done += 1
    
    # 按收益排序
    all_results.sort(key=lambda x: x["return_pct"], reverse=True)
    
    # 打印TOP 20
    print(f"\n🏆 TOP 20 最佳组合 (共测试 {total_combos} 种组合)")
    print(f"{'='*140}")
    print(f"{'#':<3} {'策略':<14} {'入场参数':<24} {'SL':>4} {'TP':>4} {'持仓h':>5} {'阈值':>4} {'最终资金':>10} {'收益%':>8} {'交易':>5} {'胜率':>6} {'盈亏比':>6} {'回撤%':>7}")
    print("-" * 140)
    
    for i, r in enumerate(all_results[:20], 1):
        p = r["params"]
        e = r["exit"]
        params_str = " ".join(f"{k}={v}" for k, v in p.items())
        color = "🟢" if r["return_pct"] > 100 else "🔵" if r["return_pct"] > 50 else "🟡" if r["return_pct"] > 0 else "🔴"
        
        print(f"{color}{i:<2} {r['strategy']:<14} {params_str:<24} {e['sl']*100:>3.0f}% {e['tp']*100:>3.0f}% {e['max_hold']:>5} {e['entry_th']:>4} {r['final']:>10.2f} {r['return_pct']:>+7.2f}% {r['trades']:>5} {r['win_rate']:>5.1f}% {r['pf']:>6.2f} {r['max_dd']:>6.2f}%")
    
    # 最佳组合详情
    best = all_results[0]
    print(f"\n{'='*140}")
    print(f"🏆 最佳组合详情")
    print(f"{'='*140}")
    print(f"  策略: {best['strategy']}")
    print(f"  入场参数: {best['params']}")
    print(f"  出场参数: 止损{best['exit']['sl']*100}% | 止盈{best['exit']['tp']*100}% | 最大持仓{best['exit']['max_hold']}h | 入场阈值{best['exit']['entry_th']}")
    print(f"  ---")
    print(f"  初始资金: 1000 USDT")
    print(f"  最终资金: {best['final']} USDT")
    print(f"  总收益: {best['return_pct']:+.2f}% ({best['final']-1000:+.2f} USDT)")
    print(f"  交易笔数: {best['trades']}")
    print(f"  胜率: {best['win_rate']:.1f}%")
    print(f"  平均赢: {best['avg_win']:+.2f} USDT")
    print(f"  平均亏: {best['avg_loss']:+.2f} USDT")
    print(f"  盈亏比: {best['pf']}")
    print(f"  最大回撤: {best['max_dd']:.2f}%")
    
    # TOP 3 交易记录
    print(f"\n📋 最佳组合交易记录 (前15笔):")
    print("-" * 140)
    print(f"{'币种':<14} {'入场':>12} {'出场':>12} {'入场价':>10} {'出场价':>10} {'PnL%':>7} {'PnL USD':>10} {'原因':>6} {'持仓h':>6}")
    print("-" * 140)
    
    for t in best["trades_detail"][:15]:
        c = "🟢" if t["pnl_usd"] > 0 else "🔴"
        et = datetime.fromtimestamp(t["entry_time"]/1000).strftime("%m-%d %H:%M")
        xt = datetime.fromtimestamp(t["exit_time"]/1000).strftime("%m-%d %H:%M")
        print(f"{c}{t['symbol']:<13} {et:>12} {xt:>12} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+6.2f}% {t['pnl_usd']:>+10.2f} {t['reason']:>6} {t['holding_h']:>6.1f}")
    
    # 策略维度对比
    print(f"\n{'='*140}")
    print("📊 各策略最佳表现对比")
    print(f"{'='*140}")
    
    best_per_strategy = {}
    for r in all_results:
        s = r["strategy"]
        if s not in best_per_strategy or r["return_pct"] > best_per_strategy[s]["return_pct"]:
            best_per_strategy[s] = r
    
    sorted_strats = sorted(best_per_strategy.values(), key=lambda x: x["return_pct"], reverse=True)
    for i, r in enumerate(sorted_strats, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        bar_len = min(int(max(0, r["return_pct"]) / 3), 50)
        bar = "█" * bar_len
        print(f"  {emoji} #{i} {r['strategy']:<14} {r['return_pct']:>+8.2f}% |{bar}| {r['final']:.2f}U ({r['trades']}笔, 胜率{r['win_rate']}%)")
    
    # 出场参数对比
    print(f"\n{'='*140}")
    print("📊 出场参数影响分析")
    print(f"{'='*140}")
    
    exit_analysis = {}
    for r in all_results:
        key = f"SL{r['exit']['sl']*100:.0f}_TP{r['exit']['tp']*100:.0f}"
        if key not in exit_analysis:
            exit_analysis[key] = {"returns": [], "key": key, "exit": r["exit"]}
        exit_analysis[key]["returns"].append(r["return_pct"])
    
    print(f"{'出场参数':<20} {'平均收益':>10} {'最高收益':>10} {'最低收益':>10}")
    print("-" * 60)
    for key, data in sorted(exit_analysis.items(), key=lambda x: sum(x[1]["returns"])/len(x[1]["returns"]), reverse=True):
        avg_r = sum(data["returns"]) / len(data["returns"])
        max_r = max(data["returns"])
        min_r = min(data["returns"])
        e = data["exit"]
        print(f"  SL{e['sl']*100:.0f}%/TP{e['tp']*100:.0f}%/{e['max_hold']}h  {avg_r:>+9.2f}% {max_r:>+9.2f}% {min_r:>+9.2f}%")
    
    print(f"\n{'='*140}")
    print("⚠️ 回测结果仅供参考，不代表未来收益。合约交易具有高风险。")
    print(f"{'='*140}")


if __name__ == "__main__":
    optimize()
