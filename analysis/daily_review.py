#!/usr/bin/env python3
"""
🔥 妖币猎手 - 每日复盘 (安全版)
====================================
每天23:00自动运行:
1. 统计当日交易表现
2. 分析胜率/盈亏比/回撤
3. 安全优化: 先回测验证再应用
4. 生成复盘报告
"""

import json
import os
import time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import hmac
import hashlib

BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BASE_URL = "https://fapi.binance.com"

DAILY_COST = 50
DAILY_TARGET = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "live_state.json")
TRADE_LOG = os.path.join(BASE_DIR, "live_trades.json")
REVIEW_DIR = os.path.join(BASE_DIR, "reviews")


def sign_request(params):
    query = urlencode(params)
    sig = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def api_get(endpoint, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = sign_request(params)
    url = f"{BASE_URL}{endpoint}?{query}"
    req = Request(url, headers={"X-MBX-APIKEY": BINANCE_API_KEY})
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except:
        return None

def fetch_public(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params: url += "?" + urlencode(params)
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 Review/1.0"})
        with urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except:
        return None

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None

def get_balance():
    data = api_get("/fapi/v3/balance")
    if data:
        for item in data:
            if item.get("asset") == "USDT":
                return {
                    "balance": float(item.get("balance", 0)),
                    "available": float(item.get("availableBalance", 0)),
                    "unrealized_pnl": float(item.get("crossUnPnl", 0)),
                }
    return None

def get_positions():
    data = api_get("/fapi/v3/positionRisk")
    positions = []
    if data:
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol": p["symbol"],
                    "side": "LONG" if amt > 0 else "SHORT",
                    "amount": abs(amt),
                    "entry_price": float(p.get("entryPrice", 0)),
                    "mark_price": float(p.get("markPrice", 0)),
                    "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 10)),
                    "margin": float(p.get("initialMargin", 0)),
                })
    return positions

def get_today_trades():
    trades = load_json(TRADE_LOG) or []
    today = datetime.now().strftime("%Y-%m-%d")
    return [t for t in trades if t.get("exit_time", "").startswith(today)]

def analyze_day():
    state = load_json(STATE_FILE) or {}
    trades = get_today_trades()
    balance = get_balance()
    positions = get_positions()
    
    total_trades = len(trades)
    wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
    losses = [t for t in trades if t.get("pnl_usd", 0) <= 0]
    
    total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
    unrealized = sum(p["unrealized_pnl"] for p in positions)
    
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    
    exit_reasons = {}
    for t in trades:
        reason = t.get("reason", "unknown")
        if reason not in exit_reasons:
            exit_reasons[reason] = {"count": 0, "pnl": 0, "wins": 0}
        exit_reasons[reason]["count"] += 1
        exit_reasons[reason]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            exit_reasons[reason]["wins"] += 1
    
    symbol_stats = {}
    for t in trades:
        sym = t.get("symbol", "")
        if sym not in symbol_stats:
            symbol_stats[sym] = {"count": 0, "pnl": 0, "wins": 0}
        symbol_stats[sym]["count"] += 1
        symbol_stats[sym]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            symbol_stats[sym]["wins"] += 1
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "balance": balance["balance"] if balance else 0,
        "available": balance["available"] if balance else 0,
        "positions": positions,
        "exit_reasons": exit_reasons,
        "symbol_stats": symbol_stats,
        "net_profit": round(total_pnl - DAILY_COST, 2),
    }


def generate_report(analysis, optimize_changes):
    os.makedirs(REVIEW_DIR, exist_ok=True)
    params = load_json(os.path.join(BASE_DIR, "strategy_params.json")) or {}
    
    report = f"""
{'='*80}
🔥 妖币猎手 - 每日复盘报告
{'='*80}
📅 日期: {analysis['date']}
⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*80}

💰 账户概况
{'─'*40}
  余额: {analysis['balance']:.2f}U
  可用: {analysis['available']:.2f}U
  持仓: {len(analysis['positions'])} 个
  未实现盈亏: {analysis['unrealized_pnl']:+.2f}U

📊 今日交易
{'─'*40}
  总交易: {analysis['total_trades']} 笔
  盈利: {analysis['wins']} 笔 | 亏损: {analysis['losses']} 笔
  胜率: {analysis['win_rate']:.1f}%
  平均盈利: {analysis['avg_win']:+.2f}U
  平均亏损: {analysis['avg_loss']:+.2f}U
  已实现盈亏: {analysis['total_pnl']:+.2f}U
  未实现盈亏: {analysis['unrealized_pnl']:+.2f}U

💸 成本与收益
{'─'*40}
  每日成本: {DAILY_COST}U
  今日收益: {analysis['total_pnl']:+.2f}U
  净利润: {analysis['net_profit']:+.2f}U
  目标达成: {'✅' if analysis['total_pnl'] >= DAILY_TARGET else '❌'} (目标: {DAILY_TARGET}U)
"""
    
    if analysis["exit_reasons"]:
        report += f"\n📋 出场原因\n{'─'*40}\n"
        for reason, stats in sorted(analysis["exit_reasons"].items(), key=lambda x: x[1]["pnl"], reverse=True):
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            emoji = "🟢" if stats["pnl"] > 0 else "🔴"
            report += f"  {emoji} {reason:<10} {stats['count']:>2}笔 | 胜率{wr:>5.1f}% | PnL {stats['pnl']:>+8.2f}U\n"
    
    if analysis["symbol_stats"]:
        report += f"\n📊 币种表现\n{'─'*40}\n"
        for sym, stats in sorted(analysis["symbol_stats"].items(), key=lambda x: x[1]["pnl"], reverse=True):
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            emoji = "🟢" if stats["pnl"] > 0 else "🔴"
            report += f"  {emoji} {sym:<14} {stats['count']:>2}笔 | 胜率{wr:>5.1f}% | PnL {stats['pnl']:>+8.2f}U\n"
    
    if analysis["positions"]:
        report += f"\n📈 当前持仓\n{'─'*40}\n"
        for p in analysis["positions"]:
            pnl_pct = (p["mark_price"] - p["entry_price"]) / p["entry_price"] * 100 if p["entry_price"] > 0 else 0
            emoji = "🟢" if p["unrealized_pnl"] > 0 else "🔴"
            report += f"  {emoji} {p['symbol']:<14} {p['side']} {p['amount']} | 入:{p['entry_price']:.4f} 现:{p['mark_price']:.4f} | {pnl_pct:+.2f}% ({p['unrealized_pnl']:+.2f}U)\n"
    
    if optimize_changes:
        report += f"\n🔧 安全优化 (已回测验证)\n{'─'*40}\n"
        for change in optimize_changes:
            report += f"  ✅ {change[0]}: {change[1]}\n"
            r = change[2]
            report += f"     回测: 收益{r['return_pct']:+.1f}% | 胜率{r['win_rate']}% | 回撤{r['max_dd']}%\n"
    else:
        report += f"\n🔧 优化状态\n{'─'*40}\n  无需优化，保持当前参数\n"
    
    report += f"""
📐 当前参数 (v{params.get('version', 1)})
{'─'*40}
  入场: OI 4h≥{params.get('oi_4h_th',8)}% | OI 1h≥{params.get('oi_1h_th',0.4)}% | Vol≥{params.get('vol_th',2.0)}x | 评分≥{params.get('entry_score',55)}
  出场: SL{params.get('stop_loss',0.10)*100}% | TP{params.get('take_profit',0.20)*100}% | Max{params.get('max_hold_hours',36)}h
  仓位: {params.get('position_pct',0.30)*100}%

{'='*80}
"""
    
    report_file = os.path.join(REVIEW_DIR, f"review_{analysis['date']}.txt")
    with open(report_file, 'w') as f:
        f.write(report)
    
    return report, report_file


def daily_review():
    from safe_optimize import safe_optimize
    
    print(f"\n{'='*80}")
    print("🔥 妖币猎手 - 每日复盘")
    print(f"{'='*80}")
    
    print("\n📊 分析当日表现...")
    analysis = analyze_day()
    
    print("🔍 安全优化 (先回测验证)...")
    changes = safe_optimize(analysis)
    
    print("📝 生成报告...")
    report, report_file = generate_report(analysis, changes)
    
    print(report)
    print(f"\n📁 报告: {report_file}")
    
    return analysis, changes


if __name__ == "__main__":
    daily_review()
