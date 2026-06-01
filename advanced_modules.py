#!/usr/bin/env python3
"""
高级交易模块 v3.0
1. 因子贡献复盘
2. 入场前EV预估
3. 行情状态分仓位
4. 失败样本库
5. 交易所对账审计
"""

import json, os, time
from datetime import datetime
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FACTOR_LOG = os.path.join(BASE_DIR, "factor_log.json")
FAILURE_DB = os.path.join(BASE_DIR, "failure_db.json")
REGIME_LOG = os.path.join(BASE_DIR, "regime_log.json")

# ============================================================
# 1. 因子贡献复盘
# ============================================================
class FactorTracker:
    """记录每个因子对开仓的贡献，平仓后统计胜率"""
    
    FACTORS = [
        "oi_chg_1h",    # OI 1h变化
        "oi_chg_4h",    # OI 4h变化
        "oi_up_streak", # OI连续上涨
        "vol_ratio",    # 成交量比
        "vol_ratio_5",  # 5根成交量比
        "chg_1h",       # 1h价格变化
        "chg_4h",       # 4h价格变化
        "supertrend",   # 超级趋势方向
        "rsi",          # RSI值
        "score",        # 总评分
    ]
    
    @staticmethod
    def record_entry(symbol, indicators, score, rsi, st_dir):
        """开仓时记录各因子状态"""
        entry = {
            "symbol": symbol,
            "time": datetime.now().isoformat(),
            "factors": {},
            "score": score,
            "rsi": rsi,
            "supertrend": st_dir,
        }
        
        if indicators:
            for f in FactorTracker.FACTORS:
                if f in indicators:
                    entry["factors"][f] = indicators[f]
        
        # 保存到文件
        data = []
        try:
            with open(FACTOR_LOG, "r") as f:
                data = json.load(f)
        except:
            pass
        
        data.append(entry)
        with open(FACTOR_LOG, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return entry
    
    @staticmethod
    def record_exit(symbol, pnl_pct, reason):
        """平仓时更新因子记录"""
        try:
            with open(FACTOR_LOG, "r") as f:
                data = json.load(f)
        except:
            return
        
        # 找到最近一条该币种的开仓记录
        for entry in reversed(data):
            if entry["symbol"] == symbol and "exit" not in entry:
                entry["exit"] = {
                    "time": datetime.now().isoformat(),
                    "pnl_pct": pnl_pct,
                    "reason": reason,
                    "win": pnl_pct > 0,
                }
                break
        
        with open(FACTOR_LOG, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def analyze_factors():
        """分析各因子的胜率贡献"""
        try:
            with open(FACTOR_LOG, "r") as f:
                data = json.load(f)
        except:
            return {}
        
        stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0})
        
        for entry in data:
            if "exit" not in entry:
                continue
            
            win = entry["exit"]["win"]
            pnl = entry["exit"]["pnl_pct"]
            
            for factor, value in entry.get("factors", {}).items():
                stats[factor]["count"] += 1
                stats[factor]["total_pnl"] += pnl
                if win:
                    stats[factor]["wins"] += 1
                else:
                    stats[factor]["losses"] += 1
        
        # 计算胜率
        result = {}
        for factor, s in stats.items():
            if s["count"] > 0:
                result[factor] = {
                    "count": s["count"],
                    "win_rate": s["wins"] / s["count"] * 100,
                    "avg_pnl": s["total_pnl"] / s["count"],
                    "total_pnl": s["total_pnl"],
                }
        
        return result


# ============================================================
# 2. 入场前EV预估
# ============================================================
class EVEstimator:
    """开仓前计算期望值 (Expected Value)"""
    
    @staticmethod
    def estimate(win_rate, avg_win, avg_loss, fee_rate=0.0004, slippage=0.001, funding_rate=0.0001):
        """
        计算EV
        win_rate: 胜率 (0-1)
        avg_win: 平均盈利 (如 0.15 = 15%)
        avg_loss: 平均亏损 (如 -0.05 = -5%)
        fee_rate: 手续费率 (0.04% = 0.0004)
        slippage: 滑点 (0.1% = 0.001)
        funding_rate: 资金费率 (0.01% = 0.0001)
        """
        # 预期收益 = 胜率 × 盈利 - 失败率 × 亏损 - 成本
        cost = fee_rate * 2 + slippage + funding_rate  # 开仓+平仓手续费+滑点+资金费
        
        ev = (win_rate * avg_win) + ((1 - win_rate) * avg_loss) - cost
        return ev
    
    @staticmethod
    def should_trade(win_rate, avg_win, avg_loss, min_ev=0.02):
        """
        判断是否应该开仓
        min_ev: 最低EV阈值 (2% = 0.02)
        """
        ev = EVEstimator.estimate(win_rate, avg_win, avg_loss)
        return ev >= min_ev, ev
    
    @staticmethod
    def get_historical_stats(trades_file):
        """从历史交易计算胜率和平均盈亏"""
        try:
            with open(trades_file, "r") as f:
                trades = json.load(f)
        except:
            return 0.5, 0.10, -0.05  # 默认值
        
        if not trades:
            return 0.5, 0.10, -0.05
        
        wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]
        
        win_rate = len(wins) / len(trades) if trades else 0.5
        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) / 100 if wins else 0.10
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) / 100 if losses else -0.05
        
        return win_rate, avg_win, avg_loss


# ============================================================
# 3. 行情状态识别 (Regime Detection)
# ============================================================
class RegimeDetector:
    """识别市场状态: 趋势/震荡/插针/低流动性"""
    
    REGIMES = {
        "trend": "趋势市",
        "range": "震荡市",
        "spike": "插针市",
        "illiquid": "低流动性市",
    }
    
    @staticmethod
    def detect(klines):
        """根据K线数据判断市场状态"""
        if len(klines) < 20:
            return "range", 0.5  # 数据不足默认震荡
        
        closes = [k["close"] for k in klines[-20:]]
        highs = [k["high"] for k in klines[-20:]]
        lows = [k["low"] for k in klines[-20:]]
        volumes = [k["quote_vol"] for k in klines[-20:]]
        
        # 1. 趋势检测: 价格方向一致性
        up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        down_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])
        trend_strength = abs(up_count - down_count) / len(closes)
        
        # 2. 波动率: ATR / 价格
        atr = sum(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) 
                  for i in range(1, len(closes))) / len(closes)
        volatility = atr / closes[-1]
        
        # 3. 插针检测: 单根K线极端波动
        max_spike = max((highs[i] - lows[i]) / lows[i] for i in range(len(closes)))
        
        # 4. 流动性: 成交量变化
        vol_avg = sum(volumes) / len(volumes)
        vol_recent = sum(volumes[-5:]) / 5
        vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1
        
        # 判断状态
        if max_spike > 0.08:  # 单根K线波动>8%
            return "spike", max_spike
        elif volatility > 0.03:  # 高波动
            if trend_strength > 0.6:  # 方向一致
                return "trend", trend_strength
            else:
                return "range", volatility
        elif vol_ratio < 0.5:  # 成交量萎缩
            return "illiquid", vol_ratio
        else:
            return "range", volatility
    
    @staticmethod
    def get_regime_params(regime):
        """根据市场状态返回参数调整"""
        params = {
            "trend": {
                "position_pct_mult": 1.2,    # 趋势市加大仓位
                "stop_loss_mult": 1.5,       # 止损放宽
                "trail_activate": 0.12,      # 追踪止盈启动更晚
                "trail_draw": 0.18,          # 追踪止盈回撤更大
                "max_hold_hours": 240,       # 持仓时间延长
            },
            "range": {
                "position_pct_mult": 0.8,    # 震荡市降低仓位
                "stop_loss_mult": 0.8,       # 止损收紧
                "trail_activate": 0.08,      # 追踪止盈启动更早
                "trail_draw": 0.12,          # 追踪止盈回撤更小
                "max_hold_hours": 120,       # 持仓时间缩短
            },
            "spike": {
                "position_pct_mult": 0.5,    # 插针市大幅降低仓位
                "stop_loss_mult": 0.6,       # 止损很紧
                "trail_activate": 0.06,      # 追踪止盈启动更早
                "trail_draw": 0.10,          # 追踪止盈回撤更小
                "max_hold_hours": 48,        # 持仓时间很短
            },
            "illiquid": {
                "position_pct_mult": 0.3,    # 低流动性市最小仓位
                "stop_loss_mult": 0.5,       # 止损很紧
                "trail_activate": 0.05,      # 追踪止盈启动更早
                "trail_draw": 0.08,          # 追踪止盈回撤更小
                "max_hold_hours": 24,        # 持仓时间很短
            },
        }
        return params.get(regime, params["range"])


# ============================================================
# 4. 失败样本库
# ============================================================
class FailureDB:
    """记录失败交易，自动分类，连续错误降低权重"""
    
    CATEGORIES = {
        "chase_high": "追高",
        "false_breakout": "假突破",
        "trend_reversal": "趋势反转",
        "data_missing": "数据缺失",
        "stop_too_tight": "止损太紧",
        "tp_too_close": "止盈太近",
        "timeout_exit": "超时离场",
        "against_market": "逆大盘",
        "low_liquidity": "流动性不足",
    }
    
    @staticmethod
    def classify_failure(entry_price, exit_price, peak_pnl, hold_hours, exit_reason, market_context):
        """自动分类失败原因"""
        pnl = (exit_price - entry_price) / entry_price * 100
        
        categories = []
        
        # 追高: 入场后立刻下跌
        if pnl < -3 and hold_hours < 4:
            categories.append("chase_high")
        
        # 假突破: 盈利后快速回撤
        if peak_pnl > 5 and pnl < 0:
            categories.append("false_breakout")
        
        # 趋势反转: 大亏
        if pnl < -8:
            categories.append("trend_reversal")
        
        # 止损太紧: 小亏后反弹
        if pnl > -3 and "stop_loss" in exit_reason:
            categories.append("stop_too_tight")
        
        # 超时离场
        if hold_hours > 120:
            categories.append("timeout_exit")
        
        # 逆大盘: 市场跌但做多
        if market_context.get("market_trend") == "down" and pnl < 0:
            categories.append("against_market")
        
        # 低流动性
        if market_context.get("vol_ratio", 1) < 0.5:
            categories.append("low_liquidity")
        
        if not categories:
            categories.append("other")
        
        return categories
    
    @staticmethod
    def record_failure(symbol, entry_price, exit_price, peak_pnl, hold_hours, exit_reason, market_context):
        """记录失败交易"""
        categories = FailureDB.classify_failure(
            entry_price, exit_price, peak_pnl, hold_hours, exit_reason, market_context
        )
        
        entry = {
            "symbol": symbol,
            "time": datetime.now().isoformat(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": (exit_price - entry_price) / entry_price * 100,
            "peak_pnl": peak_pnl,
            "hold_hours": hold_hours,
            "exit_reason": exit_reason,
            "categories": categories,
            "market_context": market_context,
        }
        
        data = []
        try:
            with open(FAILURE_DB, "r") as f:
                data = json.load(f)
        except:
            pass
        
        data.append(entry)
        with open(FAILURE_DB, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return categories
    
    @staticmethod
    def get_category_weights():
        """获取各失败类别的权重(连续出现降低权重)"""
        try:
            with open(FAILURE_DB, "r") as f:
                data = json.load(f)
        except:
            return {}
        
        # 统计最近20笔失败
        recent = data[-20:] if len(data) > 20 else data
        
        counts = defaultdict(int)
        for entry in recent:
            for cat in entry.get("categories", []):
                counts[cat] += 1
        
        # 计算权重: 出现越多权重越低
        weights = {}
        for cat, count in counts.items():
            if count >= 5:
                weights[cat] = 0.5  # 严重问题，权重减半
            elif count >= 3:
                weights[cat] = 0.7  # 中等问题
            else:
                weights[cat] = 1.0  # 正常
        
        return weights


# ============================================================
# 5. 交易所对账审计
# ============================================================
class ExchangeAudit:
    """从币安拉取真实数据，强制对账"""
    
    def __init__(self, api_get_func, api_post_func):
        self.api_get = api_get_func
        self.api_post = api_post_func
    
    def get_real_positions(self):
        """获取真实持仓"""
        data = self.api_get("/fapi/v3/positionRisk")
        if not data:
            return []
        
        positions = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if abs(amt) > 0:
                positions.append({
                    "symbol": p["symbol"],
                    "amount": amt,
                    "entry_price": float(p.get("entryPrice", 0)),
                    "mark_price": float(p.get("markPrice", 0)),
                    "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 10)),
                    "side": "LONG" if amt > 0 else "SHORT",
                })
        
        return positions
    
    def get_real_orders(self):
        """获取真实挂单"""
        data = self.api_get("/fapi/v1/openOrders")
        if not data:
            return []
        
        orders = []
        for o in data:
            orders.append({
                "symbol": o["symbol"],
                "order_id": o["orderId"],
                "type": o["type"],
                "side": o["side"],
                "price": float(o.get("price", 0)),
                "qty": float(o.get("origQty", 0)),
                "status": o["status"],
            })
        
        return orders
    
    def get_real_algo_orders(self):
        """获取真实条件单"""
        data = self.api_get("/fapi/v1/algo/openOrders")
        if not data or "orders" not in data:
            return []
        
        orders = []
        for o in data["orders"]:
            orders.append({
                "symbol": o["symbol"],
                "algo_id": o.get("algoId"),
                "type": o.get("orderType"),
                "side": o.get("side"),
                "trigger_price": float(o.get("triggerPrice", 0)),
                "status": o.get("status"),
            })
        
        return orders
    
    def get_real_trades(self, symbol, limit=50):
        """获取真实成交记录"""
        data = self.api_get("/fapi/v1/userTrades", {"symbol": symbol, "limit": limit})
        if not data:
            return []
        
        trades = []
        for t in data:
            trades.append({
                "symbol": t["symbol"],
                "order_id": t["orderId"],
                "price": float(t["price"]),
                "qty": float(t["qty"]),
                "commission": float(t["commission"]),
                "time": t["time"],
                "realized_pnl": float(t.get("realizedPnl", 0)),
            })
        
        return trades
    
    def get_real_pnl(self, symbol, start_time=None, end_time=None):
        """获取真实已实现盈亏"""
        params = {"symbol": symbol, "limit": 100}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        data = self.api_get("/fapi/v1/income", params)
        if not data:
            return []
        
        income = []
        for i in data:
            income.append({
                "symbol": i["symbol"],
                "income_type": i["incomeType"],
                "income": float(i["income"]),
                "asset": i["asset"],
                "time": i["time"],
            })
        
        return income
    
    def audit(self, local_state):
        """对账审计: 本地 vs 币安"""
        report = {
            "time": datetime.now().isoformat(),
            "discrepancies": [],
            "real_positions": [],
            "real_algo_orders": [],
        }
        
        # 获取真实数据
        real_pos = self.get_real_positions()
        real_algo = self.get_real_algo_orders()
        
        report["real_positions"] = real_pos
        report["real_algo_orders"] = real_algo
        
        # 对比持仓
        local_pos = local_state.get("positions", [])
        local_syms = {p["symbol"] for p in local_pos}
        real_syms = {p["symbol"] for p in real_pos}
        
        # 本地有但币安没有
        for sym in local_syms - real_syms:
            report["discrepancies"].append({
                "type": "position_missing",
                "symbol": sym,
                "detail": "本地有持仓但币安没有",
            })
        
        # 币安有但本地没有
        for sym in real_syms - local_syms:
            report["discrepancies"].append({
                "type": "position_extra",
                "symbol": sym,
                "detail": "币安有持仓但本地没有",
            })
        
        # 对比止损单
        for pos in real_pos:
            sym = pos["symbol"]
            has_algo = any(o["symbol"] == sym for o in real_algo)
            if not has_algo:
                report["discrepancies"].append({
                    "type": "stop_loss_missing",
                    "symbol": sym,
                    "detail": f"持仓{pos['amount']}但无止损单",
                })
        
        return report


# ============================================================
# 集成接口
# ============================================================
def init_advanced_modules(api_get_func, api_post_func):
    """初始化高级模块"""
    return {
        "factor_tracker": FactorTracker(),
        "ev_estimator": EVEstimator(),
        "regime_detector": RegimeDetector(),
        "failure_db": FailureDB(),
        "exchange_audit": ExchangeAudit(api_get_func, api_post_func),
    }
