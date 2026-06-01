#!/usr/bin/env python3
"""
A/B 回测: 当前策略 v2.2 vs 增强策略 (浮盈加仓+动态杠杆+连亏休息)
用最近7天真实行情数据，同信号源同资金，对比收益/回撤/胜率
"""

import json, time, os, sys
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import hmac, hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from live_trader import (
    BINANCE_API_KEY, BINANCE_API_SECRET, BASE_URL,
    fetch_public, get_klines, get_oi_hist, calc_indicators,
    score_signal, load_params, get_top_symbols
)

# ============================================================
# 配置
# ============================================================
INITIAL_CAPITAL = 1302.0
MAX_POSITIONS = 3
FEE_RATE = 0.0004  # 单边手续费

# 策略A: 当前策略 v2.2
STRAT_A = {
    "name": "当前策略 v2.2",
    "leverage": 10,
    "position_pct": 0.30,       # 每笔仓位占可用余额
    "stop_loss": 0.10,          # 10%止损
    "take_profit": 0.50,        # 50%固定止盈
    "trail_levels": {"50": 0.15, "100": 0.20, "200": 0.30},
    "max_hold_bars": 72,        # 最大持有72根1h线 = 3天
    "add_position": False,      # 不加仓
    "dynamic_leverage": False,  # 不动态降杠杆
    "loss_streak_pause": 0,     # 不连亏休息
    "entry_score": 55,
}

# 策略B: 增强版 (吸收比特皇+予与)
STRAT_B = {
    "name": "增强策略 (浮盈加仓+动态杠杆+连亏休息)",
    "leverage": 10,
    "position_pct": 0.30,
    "stop_loss": 0.10,
    "take_profit": 0.50,
    "trail_levels": {"50": 0.15, "100": 0.20, "200": 0.30},
    "max_hold_bars": 72,
    "add_position": True,       # ✅ 浮盈加仓
    "add_threshold": 0.10,      # 浮盈10%触发加仓
    "add_size_pct": 0.15,       # 加仓金额=可用余额的15%
    "add_max_times": 2,         # 最多加仓2次
    "dynamic_leverage": True,   # ✅ 动态降杠杆
    "leverage_tiers": [         # 资金→杠杆
        (5000, 5),              # 5000U以上用5x
        (3000, 7),              # 3000U以上用7x
        (0, 10),                # 默认10x
    ],
    "loss_streak_pause": 3,     # ✅ 连亏3次休息
    "pause_bars": 24,           # 休息24根1h线 = 24小时
    "entry_score": 55,
}

# ============================================================
# 回测引擎
# ============================================================

class Position:
    def __init__(self, symbol, entry_price, quantity, margin, leverage, bar_idx, strat):
        self.symbol = symbol
        self.entry_price = entry_price
        self.quantity = quantity
        self.margin = margin
        self.leverage = leverage
        self.entry_bar = bar_idx
        self.peak_pnl_pct = 0
        self.add_count = 0  # 加仓次数
        self.strat = strat

    def pnl_pct(self, current_price):
        if self.entry_price <= 0: return 0
        return (current_price - self.entry_price) / self.entry_price

    def pnl_usd(self, current_price):
        return self.pnl_pct(current_price) * self.margin * self.leverage

class BacktestEngine:
    def __init__(self, strat, initial_capital):
        self.strat = strat
        self.capital = initial_capital
        self.available = initial_capital
        self.positions = []
        self.trades = []
        self.equity_curve = []
        self.loss_streak = 0
        self.pause_until = -1  # 连亏休息到第几根bar
        self.total_bars = 0

    def get_leverage(self):
        if not self.strat.get("dynamic_leverage"):
            return self.strat["leverage"]
        for threshold, lev in self.strat.get("leverage_tiers", []):
            if self.capital >= threshold:
                return lev
        return self.strat["leverage"]

    def try_open(self, signal, bar_idx, current_price):
        if bar_idx < self.pause_until:
            return  # 连亏休息中

        if len(self.positions) >= MAX_POSITIONS:
            return

        leverage = self.get_leverage()
        size = self.available * self.strat["position_pct"]
        if size < 5:
            return

        qty = (size * leverage) / current_price
        fee = size * FEE_RATE
        self.available -= (size + fee)

        pos = Position(
            symbol=signal["symbol"],
            entry_price=current_price,
            quantity=qty,
            margin=size,
            leverage=leverage,
            bar_idx=bar_idx,
            strat=self.strat
        )
        self.positions.append(pos)

    def check_positions(self, bar_idx, price_map):
        closed = []
        for pos in self.positions:
            sym = pos.symbol
            if sym not in price_map:
                continue
            current = price_map[sym]
            pnl_pct = pos.pnl_pct(current)
            pos.peak_pnl_pct = max(pos.peak_pnl_pct, pnl_pct)

            exit_reason = None

            # 止损
            if pnl_pct <= -self.strat["stop_loss"]:
                exit_reason = "止损"
            # 紧急止损
            elif pnl_pct <= -0.15:
                exit_reason = "紧急止损"
            # 超时
            elif bar_idx - pos.entry_bar >= self.strat["max_hold_bars"]:
                exit_reason = "超时"
            else:
                # 止盈 + 自适应回撤
                tp = self.strat["take_profit"]
                if pnl_pct >= tp:
                    trail_levels = self.strat.get("trail_levels", {})
                    peak_pct = pos.peak_pnl_pct * 100
                    trail = 0
                    for threshold in sorted([int(k) for k in trail_levels.keys()], reverse=True):
                        if peak_pct >= threshold:
                            trail = trail_levels[str(threshold)]
                            break
                    drawdown = pos.peak_pnl_pct - pnl_pct
                    if trail > 0 and drawdown < trail:
                        pass  # 继续持有
                    else:
                        exit_reason = "止盈"

            if exit_reason:
                pnl_usd = pos.pnl_usd(current)
                fee = abs(pnl_usd) * FEE_RATE
                net_pnl = pnl_usd - fee
                self.available += pos.margin + net_pnl
                self.capital = self.available + sum(
                    p.pnl_usd(price_map.get(p.symbol, p.entry_price))
                    for p in self.positions if p != pos
                )

                self.trades.append({
                    "symbol": sym,
                    "entry_price": pos.entry_price,
                    "exit_price": current,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "pnl_usd": round(net_pnl, 2),
                    "reason": exit_reason,
                    "bar_idx": bar_idx,
                    "add_count": pos.add_count,
                })

                # 连亏计数
                if net_pnl < 0:
                    self.loss_streak += 1
                    if (self.strat.get("loss_streak_pause", 0) > 0 and
                        self.loss_streak >= self.strat["loss_streak_pause"]):
                        self.pause_until = bar_idx + self.strat.get("pause_bars", 24)
                        self.loss_streak = 0
                else:
                    self.loss_streak = 0

                closed.append(pos)

        for p in closed:
            self.positions.remove(p)

        # 浮盈加仓检查
        if self.strat.get("add_position"):
            for pos in self.positions:
                if pos.add_count >= self.strat.get("add_max_times", 2):
                    continue
                sym = pos.symbol
                if sym not in price_map:
                    continue
                pnl_pct = pos.pnl_pct(price_map[sym])
                threshold = self.strat.get("add_threshold", 0.10)
                if pnl_pct >= threshold:
                    add_size = self.available * self.strat.get("add_size_pct", 0.15)
                    if add_size < 5 or len(self.positions) >= MAX_POSITIONS:
                        continue
                    leverage = self.get_leverage()
                    current = price_map[sym]
                    add_qty = (add_size * leverage) / current
                    fee = add_size * FEE_RATE
                    self.available -= (add_size + fee)

                    # 更新持仓 (加权平均入场价)
                    total_cost = pos.entry_price * pos.quantity + current * add_qty
                    pos.quantity += add_qty
                    pos.entry_price = total_cost / pos.quantity
                    pos.margin += add_size
                    pos.add_count += 1

    def snapshot(self, bar_idx, price_map):
        total = self.available
        for p in self.positions:
            total += p.margin + p.pnl_usd(price_map.get(p.symbol, p.entry_price))
        self.equity_curve.append({"bar": bar_idx, "equity": round(total, 2)})

# ============================================================
# 数据采集
# ============================================================

def collect_signals(symbols, params):
    """采集每个币种每小时的信号评分和价格"""
    all_data = {}
    for sym in symbols:
        klines = get_klines(sym, interval="1h", limit=168)  # 7天
        oi_map = get_oi_hist(sym, limit=168)
        if len(klines) < 20:
            continue
        indicators = calc_indicators(klines, oi_map)
        if not indicators:
            continue
        all_data[sym] = {
            "klines": klines,
            "indicators": indicators,
        }
        time.sleep(0.12)
    return all_data

# ============================================================
# 主回测
# ============================================================

def run_backtest(strat, all_data, symbols):
    engine = BacktestEngine(strat, INITIAL_CAPITAL)
    params = load_params()

    # 找到所有数据中最长的共同长度
    max_bars = min(len(d["klines"]) for d in all_data.values())

    for bar_idx in range(5, max_bars):
        price_map = {}
        signals = []

        for sym in symbols:
            if sym not in all_data:
                continue
            d = all_data[sym]
            klines = d["klines"]
            indicators = d["indicators"]

            if bar_idx >= len(klines) or bar_idx >= len(indicators):
                continue

            price = klines[bar_idx]["close"]
            price_map[sym] = price

            ind = indicators[bar_idx]
            if ind is None:
                continue

            score = score_signal(indicators, bar_idx)
            if score >= strat.get("entry_score", 55):
                signals.append({"symbol": sym, "score": score, "price": price})

        # 检查现有仓位
        engine.check_positions(bar_idx, price_map)
        engine.snapshot(bar_idx, price_map)

        # 开新仓 (按评分排序)
        signals.sort(key=lambda x: x["score"], reverse=True)
        for sig in signals:
            if len(engine.positions) >= MAX_POSITIONS:
                break
            engine.try_open(sig, bar_idx, price_map.get(sig["symbol"], sig["price"]))

    # 最终平仓
    final_prices = {}
    for sym in symbols:
        if sym in all_data:
            klines = all_data[sym]["klines"]
            if klines:
                final_prices[sym] = klines[-1]["close"]

    for pos in list(engine.positions):
        current = final_prices.get(pos.symbol, pos.entry_price)
        pnl_pct = pos.pnl_pct(current)
        pnl_usd = pos.pnl_usd(current)
        fee = abs(pnl_usd) * FEE_RATE
        net_pnl = pnl_usd - fee
        engine.available += pos.margin + net_pnl
        engine.trades.append({
            "symbol": pos.symbol,
            "entry_price": pos.entry_price,
            "exit_price": current,
            "pnl_pct": round(pnl_pct * 100, 2),
            "pnl_usd": round(net_pnl, 2),
            "reason": "回测结束",
            "bar_idx": 0,
            "add_count": pos.add_count,
        })

    engine.capital = engine.available
    return engine

def format_report(engine, strat):
    trades = engine.trades
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] < 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)

    max_equity = 0
    max_dd = 0
    for snap in engine.equity_curve:
        eq = snap["equity"]
        max_equity = max(max_equity, eq)
        dd = (max_equity - eq) / max_equity if max_equity > 0 else 0
        max_dd = max(max_dd, dd)

    # 加仓统计
    add_trades = [t for t in trades if t.get("add_count", 0) > 0]

    report = {
        "策略": strat["name"],
        "初始资金": f"{INITIAL_CAPITAL:.2f}U",
        "最终资金": f"{engine.capital:.2f}U",
        "总收益": f"{total_pnl:+.2f}U ({total_pnl/INITIAL_CAPITAL*100:+.1f}%)",
        "总交易": f"{len(trades)}笔",
        "盈利": f"{len(wins)}笔",
        "亏损": f"{len(losses)}笔",
        "胜率": f"{len(wins)/max(len(trades),1)*100:.1f}%",
        "平均盈利": f"{sum(t['pnl_usd'] for t in wins)/max(len(wins),1):.2f}U" if wins else "N/A",
        "平均亏损": f"{sum(t['pnl_usd'] for t in losses)/max(len(losses),1):.2f}U" if losses else "N/A",
        "最大回撤": f"{max_dd*100:.1f}%",
        "加仓次数": f"{sum(t.get('add_count',0) for t in trades)}次 ({len(add_trades)}笔触发)",
        "盈亏比": f"{abs(sum(t['pnl_usd'] for t in wins)/min(sum(t['pnl_usd'] for t in losses), -0.01)):.2f}" if losses and wins else "N/A",
    }
    return report

# ============================================================
# 运行
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  A/B 回测: 当前策略 vs 增强策略")
    print("=" * 60)

    params = load_params()
    print(f"\n📡 采集信号数据...")
    symbols = get_top_symbols()[:60]
    print(f"  扫描 {len(symbols)} 个币种, 7天1h数据...")

    all_data = collect_signals(symbols, params)
    print(f"  ✅ 采集完成: {len(all_data)} 个币种有效数据")

    # 找共同数据集
    common_syms = list(all_data.keys())
    print(f"  共同币种: {len(common_syms)} 个")

    # A组
    print(f"\n{'='*60}")
    print(f"  🅰️ 回测 A: {STRAT_A['name']}")
    print(f"{'='*60}")
    engine_a = run_backtest(STRAT_A, all_data, common_syms)
    report_a = format_report(engine_a, STRAT_A)
    for k, v in report_a.items():
        print(f"  {k}: {v}")

    # B组
    print(f"\n{'='*60}")
    print(f"  🅱️ 回测 B: {STRAT_B['name']}")
    print(f"{'='*60}")
    engine_b = run_backtest(STRAT_B, all_data, common_syms)
    report_b = format_report(engine_b, STRAT_B)
    for k, v in report_b.items():
        print(f"  {k}: {v}")

    # 对比
    print(f"\n{'='*60}")
    print(f"  📊 A/B 对比")
    print(f"{'='*60}")
    print(f"  {'指标':<12} {'A(当前)':<20} {'B(增强)':<20} {'差异':<15}")
    print(f"  {'-'*67}")
    for key in ["总收益", "总交易", "胜率", "最大回撤", "加仓次数"]:
        a = report_a.get(key, "N/A")
        b = report_b.get(key, "N/A")
        print(f"  {key:<12} {a:<20} {b:<20}")

    # 交易明细
    print(f"\n{'='*60}")
    print(f"  📋 A组交易明细")
    print(f"{'='*60}")
    print(f"  {'币种':<14} {'入场':>10} {'出场':>10} {'盈亏%':>8} {'盈亏U':>10} {'原因':<8}")
    print(f"  {'-'*62}")
    for t in engine_a.trades:
        emoji = "+" if t["pnl_usd"] > 0 else ""
        print(f"  {t['symbol']:<14} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+8.2f} {emoji}{t['pnl_usd']:>9.2f} {t['reason']:<8}")

    print(f"\n{'='*60}")
    print(f"  📋 B组交易明细")
    print(f"{'='*60}")
    print(f"  {'币种':<14} {'入场':>10} {'出场':>10} {'盈亏%':>8} {'盈亏U':>10} {'原因':<8} {'加仓':>4}")
    print(f"  {'-'*67}")
    for t in engine_b.trades:
        emoji = "+" if t["pnl_usd"] > 0 else ""
        add = f"x{t['add_count']}" if t.get("add_count", 0) > 0 else ""
        print(f"  {t['symbol']:<14} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+8.2f} {emoji}{t['pnl_usd']:>9.2f} {t['reason']:<8} {add:>4}")

    # 资金曲线关键节点
    print(f"\n{'='*60}")
    print(f"  📈 资金曲线 (每24bar采样)")
    print(f"{'='*60}")
    print(f"  {'Bar':>6} {'A组资金':>12} {'B组资金':>12}")
    print(f"  {'-'*32}")
    for i in range(0, min(len(engine_a.equity_curve), len(engine_b.equity_curve)), 24):
        a = engine_a.equity_curve[i]
        b = engine_b.equity_curve[i]
        print(f"  {a['bar']:>6} {a['equity']:>12.2f} {b['equity']:>12.2f}")
    # 最后一个
    if engine_a.equity_curve and engine_b.equity_curve:
        a = engine_a.equity_curve[-1]
        b = engine_b.equity_curve[-1]
        print(f"  {a['bar']:>6} {a['equity']:>12.2f} {b['equity']:>12.2f}")

    print(f"\n✅ 回测完成")
