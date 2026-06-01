
#!/usr/bin/env python3
"""
A/B 回测: 当前策略 v2.2 vs 策略C (吸收Agent Trade Kit要素)
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

INITIAL_CAPITAL = 1302.0
MAX_POSITIONS = 3
FEE_RATE = 0.0004

STRAT_A = {
    "name": "当前策略 v2.2",
    "leverage": 10,
    "position_pct": 0.30,
    "stop_loss": 0.10,
    "take_profit": 0.50,
    "trail_levels": {"50": 0.15, "100": 0.20, "200": 0.30},
    "max_hold_bars": 72,
    "entry_score": 55,
    "type": "current",
}

STRAT_C = {
    "name": "策略C (多维信号+阶段资金+追踪止盈)",
    "type": "atk",
    "max_hold_bars": 72,
    "entry_score": 55,
    "stages": [
        {"min": 0, "max": 10000, "leverage": 10, "risk_pct": 0.05},
        {"min": 10000, "max": 100000, "leverage": 8, "risk_pct": 0.03},
        {"min": 100000, "max": 1e9, "leverage": 5, "risk_pct": 0.015},
    ],
    "supertrend_period": 10,
    "supertrend_mult": 3.0,
    "stop_loss_by_stage": [0.05, 0.03, 0.015],
    "trail_activate": 0.10,
    "trail_bars": 5,
    "partial_tp": 0.50,
    "partial_pct": 0.30,
    "max_drawdown_pause": 0.30,
    "pause_bars": 24,
}

# ============================================================
# SuperTrend + MACD
# ============================================================

def calc_supertrend(klines, period=10, multiplier=3.0):
    if len(klines) < period + 1:
        return [None] * len(klines)
    result = [None] * len(klines)
    atr_vals = []
    direction = [0] * len(klines)
    upper = [0] * len(klines)
    lower = [0] * len(klines)
    for i in range(len(klines)):
        h, l, c = klines[i]["high"], klines[i]["low"], klines[i]["close"]
        if i == 0:
            atr_vals.append(h - l)
            continue
        pc = klines[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if len(atr_vals) < period:
            atr_vals.append(tr)
        else:
            atr_vals.append((atr_vals[-1] * (period - 1) + tr) / period)
        if len(atr_vals) < period:
            continue
        atr = atr_vals[-1]
        hl2 = (h + l) / 2
        up = hl2 + multiplier * atr
        dn = hl2 - multiplier * atr
        upper[i] = min(up, upper[i-1]) if direction[i-1] >= 0 and upper[i-1] > 0 else up
        lower[i] = max(dn, lower[i-1]) if direction[i-1] <= 0 and lower[i-1] > 0 else dn
        if direction[i-1] >= 0:
            direction[i] = 1 if c > upper[i] else -1
        else:
            direction[i] = -1 if c < lower[i] else 1
        result[i] = {"direction": direction[i], "value": upper[i] if direction[i] < 0 else lower[i]}
    return result

def calc_macd(closes, fast=12, slow=26, sig=9):
    result = [{"macd": 0, "signal": 0, "hist": 0}] * len(closes)
    def ema(data, period):
        if len(data) < period: return data[-1] if data else 0
        m = 2 / (period + 1)
        e = sum(data[:period]) / period
        for p in data[period:]: e = (p - e) * m + e
        return e
    macd_line = []
    for i in range(len(closes)):
        ef = ema(closes[:i+1], fast)
        es = ema(closes[:i+1], slow)
        macd_line.append(ef - es)
    signal_line = []
    for i in range(len(macd_line)):
        signal_line.append(ema(macd_line[:i+1], sig))
    for i in range(len(closes)):
        result[i] = {"macd": macd_line[i], "signal": signal_line[i], "hist": macd_line[i] - signal_line[i]}
    return result

# ============================================================
# 回测引擎
# ============================================================

class Position:
    def __init__(self, symbol, entry_price, quantity, margin, leverage, bar_idx, sl_price, stage_idx=0):
        self.symbol = symbol
        self.entry_price = entry_price
        self.quantity = quantity
        self.margin = margin
        self.leverage = leverage
        self.entry_bar = bar_idx
        self.peak_pnl_pct = 0
        self.sl_price = sl_price
        self.stage_idx = stage_idx
        self.partial_closed = False
        self.add_count = 0
        self.trailing_active = False
        self.trail_stop = 0
    def pnl_pct(self, cp):
        return (cp - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
    def pnl_usd(self, cp):
        return self.pnl_pct(cp) * self.margin * self.leverage

class BacktestEngine:
    def __init__(self, strat, capital):
        self.strat = strat
        self.initial_capital = capital
        self.capital = capital
        self.available = capital
        self.positions = []
        self.trades = []
        self.equity_curve = []
        self.max_equity = capital
        self.pause_until = -1
        self.is_atk = strat.get("type") == "atk"

    def get_stage(self):
        if not self.is_atk: return 0, self.strat
        for i, s in enumerate(self.strat["stages"]):
            if s["min"] <= self.capital < s["max"]:
                return i, s
        return 0, self.strat["stages"][0]

    def get_sl(self, idx):
        if self.is_atk:
            return self.strat["stop_loss_by_stage"][idx]
        return self.strat.get("stop_loss", 0.10)

    def try_open(self, sym, score, price, bar_idx):
        if bar_idx < self.pause_until or len(self.positions) >= MAX_POSITIONS:
            return
        if self.is_atk:
            s_idx, stage = self.get_stage()
            lev = stage["leverage"]
            size = self.available * 0.30
        else:
            s_idx = 0
            lev = self.strat["leverage"]
            if self.capital >= 5000: lev = 5
            elif self.capital >= 3000: lev = 7
            size = self.available * self.strat["position_pct"]
        if size < 5: return
        qty = (size * lev) / price
        fee = size * FEE_RATE
        self.available -= (size + fee)
        sl = price * (1 - self.get_sl(s_idx))
        self.positions.append(Position(sym, price, qty, size, lev, bar_idx, sl, s_idx))

    def check_positions(self, bar_idx, price_map):
        closed = []
        for pos in self.positions:
            if pos.symbol not in price_map: continue
            cp = price_map[pos.symbol]
            pnl = pos.pnl_pct(cp)
            pos.peak_pnl_pct = max(pos.peak_pnl_pct, pnl)
            reason = None
            if cp <= pos.sl_price:
                reason = "止损"
            elif pnl <= -0.15:
                reason = "紧急止损"
            elif bar_idx - pos.entry_bar >= self.strat.get("max_hold_bars", 72):
                reason = "超时"
            elif self.is_atk:
                if pnl >= self.strat["trail_activate"]:
                    pos.trailing_active = True
                if pos.trailing_active:
                    if pnl >= self.strat.get("partial_tp", 0.50) and not pos.partial_closed:
                        pq = pos.quantity * self.strat["partial_pct"]
                        pp = pnl * pos.margin * self.strat["partial_pct"] * pos.leverage
                        fee = abs(pp) * FEE_RATE
                        self.available += pos.margin * self.strat["partial_pct"] + pp - fee
                        pos.quantity -= pq
                        pos.margin *= (1 - self.strat["partial_pct"])
                        pos.partial_closed = True
                        pos.sl_price = max(pos.sl_price, pos.entry_price)
                    # 追踪止盈: 浮盈从峰值回撤超过15%则止盈
                    if pos.peak_pnl_pct > 0 and (pos.peak_pnl_pct - pnl) > 0.15:
                        reason = "追踪止盈"
            else:
                tp = self.strat.get("take_profit", 0.50)
                if pnl >= tp:
                    tl = self.strat.get("trail_levels", {})
                    pp = pos.peak_pnl_pct * 100
                    trail = 0
                    for th in sorted([int(k) for k in tl.keys()], reverse=True):
                        if pp >= th:
                            trail = tl[str(th)]
                            break
                    dd = pos.peak_pnl_pct - pnl
                    if not (trail > 0 and dd < trail):
                        reason = "止盈"
            if reason:
                pnl_usd = pos.pnl_usd(cp)
                fee = abs(pnl_usd) * FEE_RATE
                self.available += pos.margin + pnl_usd - fee
                self.trades.append({"symbol": pos.symbol, "entry_price": pos.entry_price,
                    "exit_price": cp, "pnl_pct": round(pnl*100,2), "pnl_usd": round(pnl_usd-fee,2),
                    "reason": reason, "bar_idx": bar_idx, "leverage": pos.leverage,
                    "stage": pos.stage_idx, "add_count": pos.add_count, "partial": pos.partial_closed})
                closed.append(pos)
        for p in closed:
            self.positions.remove(p)
        # 加仓 (ATK阶段0和1)
        if self.is_atk:
            s_idx, _ = self.get_stage()
            if s_idx <= 1:
                for pos in self.positions:
                    if pos.add_count >= 2 or pos.symbol not in price_map: continue
                    if pos.pnl_pct(price_map[pos.symbol]) >= 0.50:
                        add = self.available * 0.15
                        if add < 5 or len(self.positions) >= MAX_POSITIONS: continue
                        cp = price_map[pos.symbol]
                        aq = (add * pos.leverage) / cp
                        self.available -= add * (1 + FEE_RATE)
                        tc = pos.entry_price * pos.quantity + cp * aq
                        pos.quantity += aq
                        pos.entry_price = tc / pos.quantity
                        pos.margin += add
                        pos.add_count += 1
        # 回撤暂停
        if self.is_atk:
            eq = self.available + sum(p.pnl_usd(price_map.get(p.symbol, p.entry_price)) for p in self.positions)
            self.max_equity = max(self.max_equity, eq)
            dd = (self.max_equity - eq) / self.max_equity if self.max_equity > 0 else 0
            if dd >= self.strat["max_drawdown_pause"]:
                self.pause_until = bar_idx + self.strat.get("pause_bars", 24)

    def snapshot(self, bar_idx, price_map):
        total = self.available + sum(p.margin + p.pnl_usd(price_map.get(p.symbol, p.entry_price)) for p in self.positions)
        self.equity_curve.append({"bar": bar_idx, "equity": round(total, 2)})

# ============================================================
# 数据+主回测
# ============================================================

def collect_data(symbols):
    all_data = {}
    for sym in symbols:
        try:
            k1h = get_klines(sym, "1h", 168)
            k4h = get_klines(sym, "4h", 42)
            oi = get_oi_hist(sym, 168)
            if k1h and len(k1h) >= 30:
                closes = [k["close"] for k in k1h]
                closes4 = [k["close"] for k in k4h] if k4h else []
                all_data[sym] = {
                    "k1h": k1h, "k4h": k4h, "oi": oi,
                    "st_1h": calc_supertrend(k1h),
                    "st_4h": calc_supertrend(k4h) if k4h else [],
                    "macd_1h": calc_macd(closes),
                    "macd_4h": calc_macd(closes4) if closes4 else [],
                }
        except: pass
        time.sleep(0.12)
    return all_data

def run_bt(strat, all_data, syms):
    engine = BacktestEngine(strat, INITIAL_CAPITAL)
    params = load_params()
    max_bars = min(len(d["k1h"]) for d in all_data.values())
    for bar in range(30, max_bars):
        pm = {}
        sigs = []
        for sym in syms:
            if sym not in all_data: continue
            d = all_data[sym]
            kl = d["k1h"]
            ind = calc_indicators(kl, d["oi"])
            if bar >= len(kl) or not ind or bar >= len(ind): continue
            price = kl[bar]["close"]
            pm[sym] = price
            if ind[bar] is None: continue
            sc = score_signal(ind, bar)
            if strat.get("type") == "atk":
                st = d["st_1h"]
                if bar < len(st) and st[bar]:
                    if st[bar]["direction"] > 0: sc += 15
                    elif st[bar]["direction"] < 0: sc -= 10
                macd = d["macd_1h"]
                if bar < len(macd) and macd[bar]["hist"] > 0: sc += 10
                st4 = d["st_4h"]
                if st4 and len(st4) > 0 and st4[-1] and st4[-1]["direction"] > 0: sc += 10
                oi_now = d["oi"].get(kl[bar]["time"], 0) if bar < len(kl) else 0
                oi_prev = d["oi"].get(kl[max(0,bar-4)]["time"], 0) if bar >= 4 else 0
                if oi_prev > 0 and (oi_now - oi_prev) / oi_prev * 100 > 5: sc += 10
            if sc >= strat.get("entry_score", 55):
                sigs.append({"symbol": sym, "score": sc, "price": price})
        engine.check_positions(bar, pm)
        engine.snapshot(bar, pm)
        sigs.sort(key=lambda x: x["score"], reverse=True)
        for s in sigs:
            if len(engine.positions) >= MAX_POSITIONS: break
            engine.try_open(s["symbol"], s["score"], pm.get(s["symbol"], s["price"]), bar)
    return engine

def report(engine, strat):
    t = engine.trades
    w = [x for x in t if x["pnl_usd"] > 0]
    l = [x for x in t if x["pnl_usd"] < 0]
    tp = sum(x["pnl_usd"] for x in t)
    me, md = 0, 0
    for s in engine.equity_curve:
        me = max(me, s["equity"])
        md = max(md, (me - s["equity"]) / me if me > 0 else 0)
    return {
        "策略": strat["name"],
        "最终资金": f"{engine.capital:.2f}U",
        "总收益": f"{tp:+.2f}U ({tp/INITIAL_CAPITAL*100:+.1f}%)",
        "总交易": f"{len(t)}笔",
        "胜率": f"{len(w)/max(len(t),1)*100:.1f}%",
        "平均盈利": f"{sum(x['pnl_usd'] for x in w)/max(len(w),1):.2f}U" if w else "N/A",
        "平均亏损": f"{sum(x['pnl_usd'] for x in l)/max(len(l),1):.2f}U" if l else "N/A",
        "最大回撤": f"{md*100:.1f}%",
        "盈亏比": f"{abs(sum(x['pnl_usd'] for x in w)/min(sum(x['pnl_usd'] for x in l),-0.01)):.2f}" if l and w else "N/A",
        "杠杆": f"{sum(x.get('leverage',10) for x in t)/max(len(t),1):.1f}x" if t else "N/A",
        "加仓": f"{sum(x.get('add_count',0) for x in t)}次" if engine.is_atk else "N/A",
        "部分止盈": f"{sum(1 for x in t if x.get('partial'))}笔" if engine.is_atk else "N/A",
    }

if __name__ == "__main__":
    print("=" * 60)
    print("  A/C 回测: 当前策略 v2.2 vs 策略C (Agent Trade Kit)")
    print("=" * 60)
    symbols = get_top_symbols()[:50]
    print(f"\n📡 采集多时间框架数据...")
    all_data = collect_data(symbols)
    syms = list(all_data.keys())
    print(f"  ✅ {len(all_data)} 个币种有效数据")

    print(f"\n{'='*60}")
    print(f"  🅰️ A: {STRAT_A['name']}")
    print(f"{'='*60}")
    ea = run_bt(STRAT_A, all_data, syms)
    ra = report(ea, STRAT_A)
    for k, v in ra.items(): print(f"  {k}: {v}")

    print(f"\n{'='*60}")
    print(f"  🅲 C: {STRAT_C['name']}")
    print(f"{'='*60}")
    ec = run_bt(STRAT_C, all_data, syms)
    rc = report(ec, STRAT_C)
    for k, v in rc.items(): print(f"  {k}: {v}")

    print(f"\n{'='*60}")
    print(f"  📊 A/C 对比")
    print(f"{'='*60}")
    print(f"  {'指标':<12} {'A(当前)':<22} {'C(增强)':<22}")
    print(f"  {'-'*56}")
    for key in ["总收益","总交易","胜率","最大回撤","盈亏比","杠杆","加仓","部分止盈"]:
        print(f"  {key:<12} {ra.get(key,'N/A'):<22} {rc.get(key,'N/A'):<22}")

    print(f"\n  📋 A组明细:")
    print(f"  {'币种':<14} {'入场':>10} {'出场':>10} {'盈亏%':>8} {'盈亏U':>10} {'原因':<8}")
    for t in ea.trades:
        e = "+" if t["pnl_usd"] > 0 else ""
        print(f"  {t['symbol']:<14} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+8.2f} {e}{t['pnl_usd']:>9.2f} {t['reason']:<8}")

    print(f"\n  📋 C组明细:")
    print(f"  {'币种':<14} {'入场':>10} {'出场':>10} {'盈亏%':>8} {'盈亏U':>10} {'原因':<8} {'杠杆':>4} {'加仓':>3} {'部分':>3}")
    for t in ec.trades:
        e = "+" if t["pnl_usd"] > 0 else ""
        a = f"x{t['add_count']}" if t.get("add_count",0) > 0 else ""
        p = "✓" if t.get("partial") else ""
        print(f"  {t['symbol']:<14} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl_pct']:>+8.2f} {e}{t['pnl_usd']:>9.2f} {t['reason']:<8} {t.get('leverage',10):>3}x {a:>3} {p:>3}")

    print(f"\n  📈 资金曲线:")
    print(f"  {'Bar':>6} {'A':>12} {'C':>12} {'差':>10}")
    for i in range(0, min(len(ea.equity_curve), len(ec.equity_curve)), 24):
        a, c = ea.equity_curve[i], ec.equity_curve[i]
        print(f"  {a['bar']:>6} {a['equity']:>12.2f} {c['equity']:>12.2f} {c['equity']-a['equity']:>+10.2f}")
    if ea.equity_curve and ec.equity_curve:
        a, c = ea.equity_curve[-1], ec.equity_curve[-1]
        print(f"  {a['bar']:>6} {a['equity']:>12.2f} {c['equity']:>12.2f} {c['equity']-a['equity']:>+10.2f}")

    print(f"\n✅ 回测完成")
