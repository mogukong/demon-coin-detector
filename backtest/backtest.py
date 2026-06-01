#!/usr/bin/env python3
"""
🔥 妖币检测器 - 回测引擎 v1.0
================================
回测过去10天，5种策略，1000U本金，10x杠杆，8%止损

策略:
A. Pure Momentum - 价格动量 + 成交量放大
B. OI + Price - OI暴增 + 价格涨
C. Volume Surge - 成交量暴涨 + 趋势
D. RSI Reversal - RSI超卖 + OI增加
E. Combined Score - 综合评分 (类似妖币检测器)
"""

import json
import os
import math
from datetime import datetime, timedelta
from glob import glob

# ============================================================
# 配置
# ============================================================
INITIAL_CAPITAL = 1000
LEVERAGE = 10
STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.15
MAX_POSITION_PCT = 0.50
MAX_POSITIONS = 3
COMMISSION_RATE = 0.0004  # 0.04% maker fee

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backtest")


# ============================================================
# 数据加载
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
        "time": d[0],
        "open": float(d[1]),
        "high": float(d[2]),
        "low": float(d[3]),
        "close": float(d[4]),
        "volume": float(d[5]),
        "quote_vol": float(d[7]),
        "trades": int(d[8]),
    } for d in data]


def load_oi_1h(symbol):
    data = load_json(os.path.join(DATA_DIR, f"{symbol}_oi_1h.json"))
    if not data:
        return {}
    return {int(d["timestamp"]): float(d["sumOpenInterestValue"]) for d in data}


# ============================================================
# 技术指标计算
# ============================================================

def ema(prices, period):
    """指数移动平均"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    for price in prices[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return ema_val


def rsi(prices, period=14):
    """RSI指标"""
    if len(prices) < period + 1:
        return 50
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    
    if len(gains) < period:
        return 50
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_indicators(klines, oi_map):
    """计算所有技术指标"""
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    
    indicators = []
    
    for i in range(len(klines)):
        if i < 25:  # 需要至少25根K线
            indicators.append(None)
            continue
        
        close = closes[i]
        
        # 价格变化
        chg_1h = (closes[i] / closes[i-1] - 1) * 100 if i >= 1 else 0
        chg_4h = (closes[i] / closes[i-4] - 1) * 100 if i >= 4 else 0
        chg_24h = (closes[i] / closes[i-24] - 1) * 100 if i >= 24 else 0
        
        # 成交量
        vol_avg_20 = sum(volumes[max(0,i-20):i]) / min(20, i) if i > 0 else volumes[i]
        vol_ratio = volumes[i] / vol_avg_20 if vol_avg_20 > 0 else 1
        
        # OI
        oi_now = oi_map.get(klines[i]["time"], 0)
        oi_1h_ago = oi_map.get(klines[i-1]["time"], 0) if i >= 1 else oi_now
        oi_4h_ago = oi_map.get(klines[i-4]["time"], 0) if i >= 4 else oi_now
        oi_24h_ago = oi_map.get(klines[i-24]["time"], 0) if i >= 24 else oi_now
        
        oi_chg_1h = (oi_now / oi_1h_ago - 1) * 100 if oi_1h_ago > 0 else 0
        oi_chg_4h = (oi_now / oi_4h_ago - 1) * 100 if oi_4h_ago > 0 else 0
        oi_chg_24h = (oi_now / oi_24h_ago - 1) * 100 if oi_24h_ago > 0 else 0
        
        # EMA
        ema_20 = ema(closes[max(0,i-20):i+1], 20)
        
        # RSI
        rsi_14 = rsi(closes[max(0,i-14):i+1], 14)
        
        # Volume/OI ratio
        vol_oi = volumes[i] / (oi_now / close) if oi_now > 0 and close > 0 else 0
        
        indicators.append({
            "close": close,
            "high": highs[i],
            "low": lows[i],
            "chg_1h": chg_1h,
            "chg_4h": chg_4h,
            "chg_24h": chg_24h,
            "vol_ratio": vol_ratio,
            "vol_oi": vol_oi,
            "oi_chg_1h": oi_chg_1h,
            "oi_chg_4h": oi_chg_4h,
            "oi_chg_24h": oi_chg_24h,
            "ema_20": ema_20,
            "rsi": rsi_14,
            "time": klines[i]["time"],
        })
    
    return indicators


# ============================================================
# 策略定义
# ============================================================

def strategy_a_momentum(ind, i):
    """Pure Momentum: 1h涨>3% + 成交量>2x"""
    d = ind[i]
    if not d:
        return 0
    score = 0
    if d["chg_1h"] > 3:
        score += 50
    if d["chg_1h"] > 1:
        score += 20
    if d["vol_ratio"] > 2:
        score += 30
    elif d["vol_ratio"] > 1.5:
        score += 15
    return score


def strategy_b_oi_price(ind, i):
    """OI + Price: OI 4h涨>10% + 价格4h涨>5%"""
    d = ind[i]
    if not d:
        return 0
    score = 0
    if d["oi_chg_4h"] > 10:
        score += 40
    elif d["oi_chg_4h"] > 5:
        score += 25
    if d["chg_4h"] > 5:
        score += 35
    elif d["chg_4h"] > 2:
        score += 20
    if d["chg_1h"] > 0:
        score += 15
    if d["vol_ratio"] > 1.5:
        score += 10
    return score


def strategy_c_volume_surge(ind, i):
    """Volume Surge: 成交量>3x + 价格>EMA20"""
    d = ind[i]
    if not d:
        return 0
    score = 0
    if d["vol_ratio"] > 3:
        score += 40
    elif d["vol_ratio"] > 2:
        score += 25
    if d["close"] > d["ema_20"]:
        score += 30
    if d["chg_1h"] > 0:
        score += 15
    if d["oi_chg_1h"] > 2:
        score += 15
    return score


def strategy_d_rsi_reversal(ind, i):
    """RSI Reversal: RSI<35 + OI增加 + 成交量增加"""
    d = ind[i]
    if not d:
        return 0
    score = 0
    if d["rsi"] < 30:
        score += 40
    elif d["rsi"] < 40:
        score += 25
    if d["oi_chg_4h"] > 5:
        score += 30
    elif d["oi_chg_4h"] > 0:
        score += 15
    if d["vol_ratio"] > 1.5:
        score += 20
    elif d["vol_ratio"] > 1:
        score += 10
    if d["chg_1h"] > 0:
        score += 10
    return score


def strategy_e_combined(ind, i):
    """Combined Score: 综合评分 (类似妖币检测器)"""
    d = ind[i]
    if not d:
        return 0
    
    score = 0
    
    # 动量 (30%)
    if d["chg_4h"] > 10: score += 30
    elif d["chg_4h"] > 5: score += 22
    elif d["chg_4h"] > 2: score += 15
    elif d["chg_4h"] > 0: score += 8
    
    # OI (30%)
    if d["oi_chg_4h"] > 15: score += 30
    elif d["oi_chg_4h"] > 10: score += 22
    elif d["oi_chg_4h"] > 5: score += 15
    elif d["oi_chg_4h"] > 0: score += 8
    
    # 成交量 (20%)
    if d["vol_ratio"] > 3: score += 20
    elif d["vol_ratio"] > 2: score += 15
    elif d["vol_ratio"] > 1.5: score += 10
    elif d["vol_ratio"] > 1: score += 5
    
    # RSI (20%)
    if 30 < d["rsi"] < 50: score += 20  # 超卖反弹区
    elif 50 <= d["rsi"] < 65: score += 15  # 中性偏多
    elif d["rsi"] < 30: score += 10  # 极度超卖
    elif 65 <= d["rsi"] < 75: score += 5
    
    return score


STRATEGIES = {
    "A_Momentum": strategy_a_momentum,
    "B_OI_Price": strategy_b_oi_price,
    "C_Vol_Surge": strategy_c_volume_surge,
    "D_RSI_Rev": strategy_d_rsi_reversal,
    "E_Combined": strategy_e_combined,
}

ENTRY_THRESHOLD = 60  # 入场阈值


# ============================================================
# 回测引擎
# ============================================================

def backtest_symbol(symbol, strategy_fn, threshold=ENTRY_THRESHOLD):
    """回测单个币种"""
    klines = load_klines_1h(symbol)
    oi_map = load_oi_1h(symbol)
    
    if len(klines) < 30:
        return []
    
    indicators = calc_indicators(klines, oi_map)
    
    trades = []
    in_position = False
    entry_price = 0
    entry_time = 0
    entry_score = 0
    position_size = 0
    
    for i in range(25, len(indicators)):
        d = indicators[i]
        if not d:
            continue
        
        if not in_position:
            # 检查入场信号
            score = strategy_fn(indicators, i)
            if score >= threshold:
                entry_price = d["close"]
                entry_time = d["time"]
                entry_score = score
                position_size = INITIAL_CAPITAL * MAX_POSITION_PCT * LEVERAGE / MAX_POSITIONS
                in_position = True
        else:
            # 检查出场
            current_price = d["close"]
            pnl_pct = (current_price - entry_price) / entry_price
            
            exit_reason = None
            exit_price = current_price
            
            # 止损
            if pnl_pct <= -STOP_LOSS_PCT:
                exit_reason = "止损"
                exit_price = entry_price * (1 - STOP_LOSS_PCT)
            
            # 止盈
            elif pnl_pct >= TAKE_PROFIT_PCT:
                exit_reason = "止盈"
                exit_price = entry_price * (1 + TAKE_PROFIT_PCT)
            
            # 持仓超过24小时且没有盈利
            elif i - (entry_time - klines[0]["time"]) // 3600000 > 24 and pnl_pct < 0.02:
                exit_reason = "超时"
                exit_price = current_price
            
            if exit_reason:
                # 计算PnL
                actual_pnl_pct = (exit_price - entry_price) / entry_price
                pnl_usd = position_size * actual_pnl_pct
                commission = position_size * COMMISSION_RATE * 2  # 开仓+平仓
                net_pnl = pnl_usd - commission
                
                trades.append({
                    "symbol": symbol,
                    "entry_time": entry_time,
                    "exit_time": d["time"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "score": entry_score,
                    "pnl_pct": actual_pnl_pct * 100,
                    "pnl_usd": net_pnl,
                    "reason": exit_reason,
                    "holding_hours": (d["time"] - entry_time) / 3600000,
                })
                
                in_position = False
    
    return trades


def run_backtest(strategy_name, strategy_fn, symbols):
    """运行完整回测"""
    all_trades = []
    
    for sym in symbols:
        trades = backtest_symbol(sym, strategy_fn)
        all_trades.extend(trades)
    
    # 按时间排序
    all_trades.sort(key=lambda x: x["entry_time"])
    
    # 模拟资金曲线
    capital = INITIAL_CAPITAL
    peak_capital = capital
    max_drawdown = 0
    equity_curve = [capital]
    
    active_positions = []
    completed_trades = []
    
    for trade in all_trades:
        # 检查是否有空闲仓位
        if len(active_positions) >= MAX_POSITIONS:
            # 找到最早的活跃仓位，假设已平仓
            earliest = active_positions.pop(0)
            capital += earliest["pnl_usd"]
            peak_capital = max(peak_capital, capital)
            dd = (peak_capital - capital) / peak_capital
            max_drawdown = max(max_drawdown, dd)
            equity_curve.append(capital)
        
        # 开新仓
        active_positions.append(trade)
        completed_trades.append(trade)
    
    # 平掉剩余仓位
    for trade in active_positions:
        capital += trade["pnl_usd"]
        equity_curve.append(capital)
    
    # 计算统计
    wins = [t for t in completed_trades if t["pnl_usd"] > 0]
    losses = [t for t in completed_trades if t["pnl_usd"] <= 0]
    
    total_return = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    win_rate = len(wins) / len(completed_trades) * 100 if completed_trades else 0
    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 0
    
    # 最大回撤
    peak = equity_curve[0]
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, dd)
    
    # 简化Sharpe
    returns = []
    for i in range(1, len(equity_curve)):
        r = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1] if equity_curve[i-1] > 0 else 0
        returns.append(r)
    avg_return = sum(returns) / len(returns) if returns else 0
    std_return = (sum((r - avg_return)**2 for r in returns) / len(returns))**0.5 if returns else 1
    sharpe = (avg_return / std_return) * (365**0.5) if std_return > 0 else 0
    
    return {
        "strategy": strategy_name,
        "final_capital": round(capital, 2),
        "total_return_pct": round(total_return, 2),
        "total_trades": len(completed_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "trades": completed_trades,
    }


# ============================================================
# 主程序
# ============================================================

def format_time(ts):
    return datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M")


def main():
    # 获取所有可用币种
    symbols = []
    for f in os.listdir(DATA_DIR):
        if f.endswith("_1h_klines.json"):
            sym = f.replace("_1h_klines.json", "")
            symbols.append(sym)
    
    symbols.sort()
    print(f"\n{'='*120}")
    print("🔥 妖币检测器 - 回测引擎 v1.0")
    print(f"{'='*120}")
    print(f"📊 回测参数:")
    print(f"  • 初始资金: {INITIAL_CAPITAL} USDT")
    print(f"  • 杠杆: {LEVERAGE}x")
    print(f"  • 止损: {STOP_LOSS_PCT*100}%")
    print(f"  • 止盈: {TAKE_PROFIT_PCT*100}%")
    print(f"  • 最大仓位: {MAX_POSITION_PCT*100}%")
    print(f"  • 最大持仓数: {MAX_POSITIONS}")
    print(f"  • 手续费: {COMMISSION_RATE*100}%")
    print(f"  • 回测币种: {len(symbols)} 个")
    print(f"  • 币种列表: {', '.join(symbols)}")
    print(f"  • 回测周期: 10天 (1小时K线)")
    print(f"{'='*120}")

    # 运行所有策略
    results = []
    for name, fn in STRATEGIES.items():
        print(f"\n⏳ 回测策略 {name}...")
        result = run_backtest(name, fn, symbols)
        results.append(result)
        print(f"  ✅ 完成 | 交易{result['total_trades']}笔 | 收益{result['total_return_pct']}%")

    # 打印结果
    print(f"\n{'='*120}")
    print("📊 回测结果对比")
    print(f"{'='*120}")
    print(f"{'策略':<16} {'最终资金':>10} {'总收益%':>8} {'交易数':>6} {'胜率%':>6} {'均赢':>8} {'均亏':>8} {'盈亏比':>6} {'最大回撤%':>8} {'Sharpe':>7}")
    print("-" * 120)

    for r in sorted(results, key=lambda x: x["total_return_pct"], reverse=True):
        color = "🟢" if r["total_return_pct"] > 0 else "🔴"
        print(f"{color} {r['strategy']:<14} {r['final_capital']:>10.2f} {r['total_return_pct']:>+7.2f}% {r['total_trades']:>6} {r['win_rate']:>5.1f}% {r['avg_win']:>+8.2f} {r['avg_loss']:>+8.2f} {r['profit_factor']:>6.2f} {r['max_drawdown_pct']:>7.2f}% {r['sharpe_ratio']:>7.2f}")

    print(f"{'='*120}")

    # 最佳策略详情
    best = max(results, key=lambda x: x["total_return_pct"])
    print(f"\n🏆 最佳策略: {best['strategy']}")
    print(f"{'='*120}")
    print(f"  • 初始资金: {INITIAL_CAPITAL} USDT")
    print(f"  • 最终资金: {best['final_capital']} USDT")
    print(f"  • 总收益: {best['total_return_pct']:+.2f}% ({best['final_capital'] - INITIAL_CAPITAL:+.2f} USDT)")
    print(f"  • 交易笔数: {best['total_trades']}")
    print(f"  • 胜率: {best['win_rate']:.1f}%")
    print(f"  • 最大回撤: {best['max_drawdown_pct']:.2f}%")
    print(f"  • Sharpe: {best['sharpe_ratio']:.2f}")

    # 最佳策略交易记录
    print(f"\n📋 {best['strategy']} 交易记录 (前20笔):")
    print("-" * 120)
    print(f"{'币种':<14} {'入场时间':>12} {'出场时间':>12} {'入场价':>10} {'出场价':>10} {'评分':>4} {'PnL%':>7} {'PnL USD':>10} {'原因':>6} {'持仓h':>6}")
    print("-" * 120)

    for t in best["trades"][:20]:
        color = "🟢" if t["pnl_usd"] > 0 else "🔴"
        print(f"{color} {t['symbol']:<13} {format_time(t['entry_time']):>12} {format_time(t['exit_time']):>12} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['score']:>4} {t['pnl_pct']:>+6.2f}% {t['pnl_usd']:>+10.2f} {t['reason']:>6} {t['holding_hours']:>6.1f}")

    # 各策略收益排名
    print(f"\n{'='*120}")
    print("📊 策略收益排名:")
    print(f"{'='*120}")
    sorted_results = sorted(results, key=lambda x: x["total_return_pct"], reverse=True)
    for i, r in enumerate(sorted_results, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
        bar_len = int(abs(r["total_return_pct"]) / 2)
        bar = "█" * min(bar_len, 50)
        sign = "+" if r["total_return_pct"] > 0 else "-"
        print(f"  {emoji} #{i} {r['strategy']:<16} {r['total_return_pct']:>+8.2f}% |{bar}| {r['final_capital']:.2f} USDT ({r['total_trades']}笔)")

    # 各币种表现
    print(f"\n{'='*120}")
    print("📊 各币种表现 (最佳策略):")
    print(f"{'='*120}")
    
    symbol_stats = {}
    for t in best["trades"]:
        sym = t["symbol"]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"trades": 0, "wins": 0, "total_pnl": 0}
        symbol_stats[sym]["trades"] += 1
        symbol_stats[sym]["total_pnl"] += t["pnl_usd"]
        if t["pnl_usd"] > 0:
            symbol_stats[sym]["wins"] += 1
    
    print(f"{'币种':<14} {'交易数':>6} {'胜率':>6} {'总PnL':>10}")
    print("-" * 50)
    for sym, stats in sorted(symbol_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        color = "🟢" if stats["total_pnl"] > 0 else "🔴"
        print(f"{color} {sym:<13} {stats['trades']:>6} {wr:>5.1f}% {stats['total_pnl']:>+10.2f}")

    print(f"\n{'='*120}")
    print("⚠️ 回测结果仅供参考，不代表未来收益。合约交易具有高风险。")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
