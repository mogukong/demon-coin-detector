#!/usr/bin/env python3
"""
🔥 妖币猎手 - 模拟交易引擎
==============================
策略: 混合C-宽松 (S3×DNA混合)
参数: OI 4h≥8% + OI 1h≥0.4% + Vol≥2x + Price 4h≥2%
出场: 10%止损 / 20%止盈 / 36h最大持仓

模拟资金: 1000U | 杠杆: 10x | 仓位: 50% | 最大持仓: 3
"""

import json
import os
import sys
import time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# ============================================================
# 配置
# ============================================================

STRATEGY_NAME = "混合C-宽松"
INITIAL_CAPITAL = 1000
LEVERAGE = 10
POSITION_PCT = 0.50
MAX_POSITIONS = 3
STOP_LOSS = 0.10
TAKE_PROFIT = 0.20
MAX_HOLD_HOURS = 36
FEE_RATE = 0.0004

# 入场参数
OI_4H_THRESHOLD = 8      # OI 4h变化 ≥ 8%
OI_1H_THRESHOLD = 0.4    # OI 1h变化 ≥ 0.4%
VOL_THRESHOLD = 2.0      # 成交量 ≥ 2x 基线
CHG_4H_THRESHOLD = 2     # 价格 4h变化 ≥ 2%
CHG_1H_THRESHOLD = 0.2   # 价格 1h变化 ≥ 0.2%
ENTRY_SCORE = 55         # 入场评分阈值

# 数据源
PERP_BOARD = "https://perp.shouyetech.com/api/board?top=50"
BN_KLINES = "https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=50"
BN_OI_HIST = "https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=1h&limit=50"
BN_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}"

# 文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "sim_state.json")
TRADE_LOG = os.path.join(BASE_DIR, "sim_trades.json")


# ============================================================
# 工具函数
# ============================================================

def fetch(url, timeout=8):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 Simulator/1.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except:
        return None


def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "capital": INITIAL_CAPITAL,
            "positions": [],
            "closed_trades": [],
            "total_pnl": 0,
            "start_time": datetime.now().isoformat(),
            "last_update": datetime.now().isoformat(),
        }


def save_state(state):
    state["last_update"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def log_trade(trade):
    trades = []
    try:
        with open(TRADE_LOG, 'r') as f:
            trades = json.load(f)
    except:
        pass
    trades.append(trade)
    with open(TRADE_LOG, 'w') as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)


def ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    m = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = (p - e) * m + e
    return e


# ============================================================
# 数据获取
# ============================================================

def get_top_symbols():
    """从perp.shouyetech.com获取热门合约"""
    data = fetch(PERP_BOARD)
    if not data or not data.get("ok"):
        return []
    rows = data.get("gainers_rows", [])
    return [r["symbol"] for r in rows if r.get("quote_volume", 0) > 5e6]


def get_klines(sym):
    data = fetch(BN_KLINES.format(sym=sym))
    if not data:
        return []
    return [{
        "time": d[0], "open": float(d[1]), "high": float(d[2]),
        "low": float(d[3]), "close": float(d[4]),
        "quote_vol": float(d[7]), "trades": int(d[8]),
    } for d in data]


def get_oi_hist(sym):
    data = fetch(BN_OI_HIST.format(sym=sym))
    if not data:
        return {}
    return {int(d["timestamp"]): float(d["sumOpenInterestValue"]) for d in data}


def get_ticker(sym):
    return fetch(BN_TICKER.format(sym=sym))


# ============================================================
# 指标计算
# ============================================================

def calc_indicators(klines, oi_map):
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    
    baselines = []
    for i in range(len(volumes)):
        start = max(0, i - 48)
        baselines.append(sum(volumes[start:i]) / max(1, i - start))
    
    indicators = []
    for i in range(len(klines)):
        if i < 5:
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
        
        # OI连续上涨
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


# ============================================================
# 评分函数 (混合C-宽松)
# ============================================================

def score_signal(ind, i):
    """混合C-宽松评分"""
    d = ind[i]
    if not d:
        return 0
    
    s = 0
    
    # OI 4h (25分)
    if d["oi_chg_4h"] > OI_4H_THRESHOLD:
        s += 25
    elif d["oi_chg_4h"] > OI_4H_THRESHOLD * 0.5:
        s += 15
    elif d["oi_chg_4h"] > 0:
        s += 8
    
    # OI 1h (15分)
    if d["oi_chg_1h"] > OI_1H_THRESHOLD:
        s += 15
    elif d["oi_chg_1h"] > 0:
        s += 8
    
    # OI连续上涨 (10分)
    if d["oi_up_streak"] >= 3:
        s += 10
    elif d["oi_up_streak"] >= 2:
        s += 5
    
    # 成交量 (15分)
    if d["vol_ratio"] > VOL_THRESHOLD:
        s += 15
    elif d["vol_ratio"] > VOL_THRESHOLD * 0.7:
        s += 10
    
    # 成交量5周期 (10分)
    if d["vol_ratio_5"] > 2:
        s += 10
    elif d["vol_ratio_5"] > 1.5:
        s += 5
    
    # 价格 4h (15分)
    if d["chg_4h"] > CHG_4H_THRESHOLD:
        s += 15
    elif d["chg_4h"] > 0:
        s += 8
    
    # 价格 1h (10分)
    if d["chg_1h"] > CHG_1H_THRESHOLD:
        s += 10
    elif d["chg_1h"] > 0:
        s += 5
    
    return s


# ============================================================
# 模拟交易引擎
# ============================================================

def run_scan():
    """扫描市场，开仓/平仓"""
    state = load_state()
    capital = state["capital"]
    positions = state["positions"]
    
    print(f"\n{'='*80}")
    print(f"🔥 妖币猎手模拟仓 - 扫描中...")
    print(f"{'='*80}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💰 资金: {capital:.2f}U | 持仓: {len(positions)}/{MAX_POSITIONS}")
    print(f"{'='*80}")
    
    # 获取热门合约
    symbols = get_top_symbols()
    if not symbols:
        print("❌ 获取数据失败")
        return
    
    print(f"📊 扫描 {len(symbols)} 个合约...")
    
    # --- 检查现有持仓 ---
    positions_to_close = []
    for pos in positions:
        ticker = get_ticker(pos["symbol"])
        if not ticker:
            continue
        
        current_price = float(ticker.get("lastPrice", pos["entry_price"]))
        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
        holding_hours = (datetime.now().timestamp() * 1000 - pos["entry_time"]) / 3600000
        
        exit_reason = None
        
        if pnl_pct <= -STOP_LOSS:
            exit_reason = "止损"
        elif pnl_pct >= TAKE_PROFIT:
            exit_reason = "止盈"
        elif holding_hours >= MAX_HOLD_HOURS:
            exit_reason = "超时"
        elif holding_hours >= 2:
            # 检查OI衰减
            oi_map = get_oi_hist(pos["symbol"])
            klines = get_klines(pos["symbol"])
            if klines and oi_map and len(klines) >= 2:
                oi_now = oi_map.get(klines[-1]["time"], 0)
                oi_prev = oi_map.get(klines[-2]["time"], 0)
                if oi_prev > 0 and (oi_now - oi_prev) / oi_prev * 100 < -0.5:
                    exit_reason = "OI衰减"
        
        if exit_reason:
            actual_pnl = pnl_pct * pos["size"] * LEVERAGE
            fee = pos["size"] * LEVERAGE * FEE_RATE * 2
            net_pnl = actual_pnl - fee
            
            capital += net_pnl
            
            trade = {
                "symbol": pos["symbol"],
                "entry_time": datetime.fromtimestamp(pos["entry_time"]/1000).isoformat(),
                "exit_time": datetime.now().isoformat(),
                "entry_price": pos["entry_price"],
                "exit_price": current_price,
                "size": pos["size"],
                "pnl_pct": round(pnl_pct * 100, 2),
                "pnl_usd": round(net_pnl, 2),
                "reason": exit_reason,
                "score": pos.get("score", 0),
            }
            
            log_trade(trade)
            state["closed_trades"].append(trade)
            
            print(f"  🔴 平仓 {pos['symbol']}: {pnl_pct*100:+.2f}% ({net_pnl:+.2f}U) [{exit_reason}]")
            
            positions_to_close.append(pos)
        else:
            print(f"  📊 持仓 {pos['symbol']}: {pnl_pct*100:+.2f}% | 入场{pos['entry_price']:.4f} | 现价{current_price:.4f}")
    
    for p in positions_to_close:
        positions.remove(p)
    
    # --- 扫描新信号 ---
    if len(positions) < MAX_POSITIONS:
        held_symbols = [p["symbol"] for p in positions]
        signals = []
        
        for sym in symbols:
            if sym in held_symbols:
                continue
            
            klines = get_klines(sym)
            oi_map = get_oi_hist(sym)
            if len(klines) < 10:
                continue
            
            indicators = calc_indicators(klines, oi_map)
            if not indicators or not indicators[-1]:
                continue
            
            score = score_signal(indicators, len(indicators) - 1)
            if score >= ENTRY_SCORE:
                signals.append({
                    "symbol": sym,
                    "score": score,
                    "price": indicators[-1]["close"],
                    "chg_1h": indicators[-1]["chg_1h"],
                    "chg_4h": indicators[-1]["chg_4h"],
                    "oi_chg_1h": indicators[-1]["oi_chg_1h"],
                    "oi_chg_4h": indicators[-1]["oi_chg_4h"],
                    "vol_ratio": indicators[-1]["vol_ratio"],
                })
            
            time.sleep(0.2)  # 限速
        
        # 按评分排序
        signals.sort(key=lambda x: x["score"], reverse=True)
        
        # 开仓
        for sig in signals:
            if len(positions) >= MAX_POSITIONS:
                break
            
            size = capital * POSITION_PCT
            if size <= 0:
                break
            
            position = {
                "symbol": sig["symbol"],
                "entry_price": sig["price"],
                "entry_time": datetime.now().timestamp() * 1000,
                "size": size,
                "score": sig["score"],
                "leverage": LEVERAGE,
            }
            
            positions.append(position)
            capital -= size  # 冻结资金
            
            print(f"  🟢 开仓 {sig['symbol']}: {sig['price']:.4f} | 评分{sig['score']} | 仓位{size:.2f}U")
            print(f"     OI 4h:{sig['oi_chg_4h']:+.2f}% | OI 1h:{sig['oi_chg_1h']:+.2f}% | Vol:{sig['vol_ratio']:.1f}x | Price 4h:{sig['chg_4h']:+.2f}%")
    
    # 保存状态
    state["capital"] = capital
    state["positions"] = positions
    save_state(state)
    
    # 打印摘要
    total_value = capital + sum(p["size"] for p in positions)
    print(f"\n{'='*80}")
    print(f"📊 账户摘要")
    print(f"{'='*80}")
    print(f"  可用资金: {capital:.2f}U")
    print(f"  持仓冻结: {sum(p['size'] for p in positions):.2f}U")
    print(f"  总资产: {total_value:.2f}U")
    print(f"  总收益: {total_value - INITIAL_CAPITAL:+.2f}U ({(total_value/INITIAL_CAPITAL-1)*100:+.2f}%)")
    print(f"  交易笔数: {len(state['closed_trades'])}")
    print(f"  持仓数: {len(positions)}/{MAX_POSITIONS}")
    print(f"{'='*80}")
    
    return state


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="持续运行 (每5分钟扫描)")
    parser.add_argument("--once", action="store_true", help="扫描一次")
    parser.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()
    
    if args.status:
        show_status()
    elif args.loop:
        print("🔥 妖币猎手模拟仓 - 持续运行模式 (每5分钟扫描)")
        while True:
            try:
                run_scan()
                print(f"\n⏳ 等待5分钟...")
                time.sleep(300)
            except KeyboardInterrupt:
                print("\n🛑 停止运行")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
                time.sleep(60)
    else:
        run_scan()


def show_status():
    """查看当前状态"""
    state = load_state()
    capital = state["capital"]
    positions = state["positions"]
    closed = state["closed_trades"]
    
    print(f"\n{'='*80}")
    print(f"🔥 妖币猎手模拟仓 - 状态查询")
    print(f"{'='*80}")
    print(f"⏰ 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📅 启动时间: {state.get('start_time', 'N/A')}")
    print(f"{'='*80}")
    
    # 计算当前持仓盈亏
    total_unrealized = 0
    print(f"\n📊 当前持仓 ({len(positions)}/{MAX_POSITIONS}):")
    print("-" * 80)
    
    if positions:
        for pos in positions:
            ticker = get_ticker(pos["symbol"])
            if ticker:
                current = float(ticker.get("lastPrice", pos["entry_price"]))
                pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
                pnl_usd = pnl_pct * pos["size"] * LEVERAGE
                total_unrealized += pnl_usd
                holding_h = (datetime.now().timestamp() * 1000 - pos["entry_time"]) / 3600000
                
                c = "🟢" if pnl_pct > 0 else "🔴"
                print(f"  {c} {pos['symbol']:<14} 入场:{pos['entry_price']:.4f} 现价:{current:.4f} 盈亏:{pnl_pct*100:+.2f}% ({pnl_usd:+.2f}U) 持仓:{holding_h:.1f}h 评分:{pos.get('score',0)}")
    else:
        print("  (无持仓)")
    
    # 已平仓统计
    realized_pnl = sum(t.get("pnl_usd", 0) for t in closed)
    wins = [t for t in closed if t.get("pnl_usd", 0) > 0]
    losses = [t for t in closed if t.get("pnl_usd", 0) <= 0]
    
    print(f"\n📊 账户总览:")
    print("-" * 80)
    print(f"  可用资金: {capital:.2f}U")
    print(f"  持仓冻结: {sum(p['size'] for p in positions):.2f}U")
    print(f"  未实现盈亏: {total_unrealized:+.2f}U")
    print(f"  已实现盈亏: {realized_pnl:+.2f}U")
    
    total_value = capital + sum(p["size"] for p in positions) + total_unrealized
    print(f"  总资产: {total_value:.2f}U")
    print(f"  总收益: {total_value - INITIAL_CAPITAL:+.2f}U ({(total_value/INITIAL_CAPITAL-1)*100:+.2f}%)")
    
    print(f"\n📊 交易统计:")
    print("-" * 80)
    print(f"  总交易: {len(closed)} 笔")
    print(f"  盈利: {len(wins)} 笔 | 亏损: {len(losses)} 笔")
    if closed:
        print(f"  胜率: {len(wins)/len(closed)*100:.1f}%")
    if wins:
        print(f"  平均盈利: {sum(t['pnl_usd'] for t in wins)/len(wins):+.2f}U")
    if losses:
        print(f"  平均亏损: {sum(t['pnl_usd'] for t in losses)/len(losses):+.2f}U")
    
    # 最近交易
    if closed:
        print(f"\n📋 最近5笔交易:")
        print("-" * 80)
        for t in closed[-5:]:
            c = "🟢" if t.get("pnl_usd", 0) > 0 else "🔴"
            print(f"  {c} {t['symbol']:<14} {t.get('entry_price',0):.4f} → {t.get('exit_price',0):.4f} | {t.get('pnl_pct',0):+.2f}% ({t.get('pnl_usd',0):+.2f}U) | {t.get('reason','')}")
    
    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
