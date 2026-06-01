#!/usr/bin/env python3
"""
🔥 妖币检测器 v2.0 - Demon Coin Detector Pro
==============================================
三维立体扫描: 市场筛选 × 持仓分析 × 情绪面
基于 RIVER/RAVE/BEAT/MAVIA 等妖币案例提取的共同特征模式

维度一: 市场筛选 (Market Screening)
  - 价格动量、OI暴增、成交量/OI比、资金费率、多空比、市值

维度二: 持仓分析 (Position Analysis)
  - 大户持仓变化、Taker买卖比、OI历史趋势、资金流向

维度三: 情绪面 (Sentiment)
  - 市安广场热度、恐惧贪婪指数、叙事切换、多空情绪
"""

import json
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from urllib.request import urlopen, Request
from urllib.error import URLError


# ============================================================
# 配置
# ============================================================

class Config:
    # === 数据源 ===
    PERP_BOARD = "https://perp.shouyetech.com/api/board?top={top}"
    PERP_ALERTS = "https://perp.shouyetech.com/api/alerts"
    SQUARE_RADAR = "https://perp.shouyetech.com/api/square-radar/overview"

    BN_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
    BN_OI = "https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
    BN_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit={limit}"
    BN_KLINE = "https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    BN_OI_HIST = "https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period={period}&limit={limit}"
    BN_TOP_LS_POS = "https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={symbol}&period={period}&limit={limit}"
    BN_TOP_LS_ACC = "https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period={period}&limit={limit}"
    BN_GLOBAL_LS = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period={period}&limit={limit}"
    BN_TAKER_VOL = "https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={symbol}&period={period}&limit={limit}"
    BN_FEAR_GREED = "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=1"

    # === 维度权重 ===
    WEIGHTS = {
        "market": 0.40,      # 市场筛选 40%
        "position": 0.35,    # 持仓分析 35%
        "sentiment": 0.25,   # 情绪面 25%
    }

    # 市场筛选子权重
    MARKET_WEIGHTS = {
        "price_momentum": 0.20,
        "oi_surge": 0.25,
        "vol_oi_ratio": 0.15,
        "funding_rate": 0.15,
        "long_short_ratio": 0.10,
        "market_cap": 0.10,
        "signal": 0.05,
    }

    # 持仓分析子权重
    POSITION_WEIGHTS = {
        "top_trader_bias": 0.25,       # 大户方向
        "taker_buy_sell": 0.25,        # 主动买卖比
        "oi_trend": 0.20,              # OI趋势
        "whale_divergence": 0.15,      # 散户vs大户分歧
        "capital_flow": 0.15,          # 资金流向
    }

    # 情绪面子权重
    SENTIMENT_WEIGHTS = {
        "square_heat": 0.30,           # 广场热度
        "fear_greed": 0.20,            # 恐惧贪婪
        "narrative_shift": 0.20,       # 叙事切换
        "sentiment_extreme": 0.15,     # 情绪极端值
        "social_volume": 0.15,         # 社交讨论量
    }

    # === 阈值 ===
    THRESH = {
        "price_strong": 15, "price_moderate": 5,
        "oi_24h_strong": 30, "oi_24h_moderate": 15, "oi_1h_alert": 5,
        "vol_oi_hot": 5.0, "vol_oi_active": 3.0,
        "fr_optimal_lo": 0.005, "fr_optimal_hi": 0.03, "fr_danger": 0.05,
        "ls_optimal_lo": 1.5, "ls_optimal_hi": 2.5, "ls_danger": 3.0,
        "mcap_small": 50e6, "mcap_medium": 200e6,
        "taker_dominant": 1.3,      # Taker买卖比显著偏多
        "whale_vs_retail_diverge": 0.15,  # 大户vs散户分歧度
        "oi_7d_surge": 20,          # 7天OI暴增
    }


# ============================================================
# 数据获取层
# ============================================================

def fetch(url: str, timeout: int = 8) -> Optional[Any]:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 DemonCoin/2.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except:
        return None


def fetch_perp_board(top=50):
    d = fetch(Config.PERP_BOARD.format(top=top))
    return d.get("gainers_rows", []) if d and d.get("ok") else []


def fetch_square_radar():
    return fetch(Config.SQUARE_RADAR)


def fetch_alerts():
    return fetch(Config.PERP_ALERTS)


def fetch_bn_ticker(sym):
    return fetch(Config.BN_TICKER.format(symbol=sym))


def fetch_bn_oi(sym):
    return fetch(Config.BN_OI.format(symbol=sym))


def fetch_bn_funding(sym, limit=8):
    return fetch(Config.BN_FUNDING.format(symbol=sym, limit=limit)) or []


def fetch_bn_oi_hist(sym, period="1d", limit=7):
    return fetch(Config.BN_OI_HIST.format(symbol=sym, period=period, limit=limit)) or []


def fetch_bn_top_ls(sym, period="1d", limit=7):
    return fetch(Config.BN_TOP_LS_POS.format(symbol=sym, period=period, limit=limit)) or []


def fetch_bn_global_ls(sym, period="1d", limit=7):
    return fetch(Config.BN_GLOBAL_LS.format(symbol=sym, period=period, limit=limit)) or []


def fetch_bn_taker(sym, period="1d", limit=7):
    return fetch(Config.BN_TAKER_VOL.format(symbol=sym, period=period, limit=limit)) or []


def fetch_bn_kline(sym, interval="4h", limit=7):
    return fetch(Config.BN_KLINE.format(symbol=sym, interval=interval, limit=limit)) or []


# ============================================================
# 评分函数
# ============================================================

def s_price(chg):
    T = Config.THRESH
    if chg >= T["price_strong"]: return 100
    if chg >= T["price_moderate"]: return 70 + (chg - T["price_moderate"]) / (T["price_strong"] - T["price_moderate"]) * 30
    if chg >= 0: return 40 + chg / T["price_moderate"] * 30
    return max(0, 20 + (chg + 5) * 4)


def s_oi(oi24, oi1h):
    T = Config.THRESH
    sc = 0
    if oi24 >= T["oi_24h_strong"]: sc += 70
    elif oi24 >= T["oi_24h_moderate"]: sc += 50 + (oi24 - T["oi_24h_moderate"]) / (T["oi_24h_strong"] - T["oi_24h_moderate"]) * 20
    elif oi24 >= 0: sc += 30 + oi24 / T["oi_24h_moderate"] * 20
    else: sc += max(0, 30 + oi24)
    if oi1h >= T["oi_1h_alert"]: sc += 30
    elif oi1h >= 1: sc += 15 + (oi1h - 1) / (T["oi_1h_alert"] - 1) * 15
    return min(100, sc)


def s_vol_oi(r):
    T = Config.THRESH
    if r >= T["vol_oi_hot"]: return 100
    if r >= T["vol_oi_active"]: return 70 + (r - T["vol_oi_active"]) / (T["vol_oi_hot"] - T["vol_oi_active"]) * 30
    if r >= 1: return 40 + (r - 1) / (T["vol_oi_active"] - 1) * 30
    return r * 40


def s_fr(fr_pct):
    T = Config.THRESH
    if T["fr_optimal_lo"] <= fr_pct <= T["fr_optimal_hi"]: return 100
    if 0 <= fr_pct < T["fr_optimal_lo"]: return 80 + fr_pct / T["fr_optimal_lo"] * 20
    if T["fr_optimal_hi"] < fr_pct <= T["fr_danger"]: return 80 - (fr_pct - T["fr_optimal_hi"]) / (T["fr_danger"] - T["fr_optimal_hi"]) * 30
    if fr_pct > T["fr_danger"]: return max(20, 50 - fr_pct * 100)
    if T["fr_danger"] <= fr_pct < 0: return 60 + fr_pct / T["fr_danger"] * 20
    return max(10, 40 + fr_pct * 10)


def s_ls(r):
    T = Config.THRESH
    if T["ls_optimal_lo"] <= r <= T["ls_optimal_hi"]: return 100
    if 1.0 <= r < T["ls_optimal_lo"]: return 60 + (r - 1) / (T["ls_optimal_lo"] - 1) * 40
    if T["ls_optimal_hi"] < r <= T["ls_danger"]: return 80 - (r - T["ls_optimal_hi"]) / (T["ls_danger"] - T["ls_optimal_hi"]) * 30
    if r > T["ls_danger"]: return max(20, 50 - (r - T["ls_danger"]) * 10)
    return r / 1 * 60


def s_mcap(m):
    T = Config.THRESH
    if m <= 0: return 50
    if m <= T["mcap_small"]: return 100
    if m <= T["mcap_medium"]: return 70 + (T["mcap_medium"] - m) / (T["mcap_medium"] - T["mcap_small"]) * 30
    return max(30, 70 - m / 1e9 * 100)


def s_signal(sig):
    return {"多开": 100, "空平": 70, "多平": 40, "空开": 20}.get(sig, 50)


# ============================================================
# 维度二: 持仓分析评分
# ============================================================

def score_top_trader_bias(pos_data, acc_data):
    """大户持仓方向评分 - 大户看多得高分"""
    if not pos_data or not acc_data:
        return 50
    latest_pos = pos_data[-1] if pos_data else {}
    latest_acc = acc_data[-1] if acc_data else {}

    top_long_pct = float(latest_pos.get("longAccount", 0.5)) * 100
    retail_long_pct = float(latest_acc.get("longAccount", 0.5)) * 100

    # 大户多头占比 55-70% 最优
    if 55 <= top_long_pct <= 70:
        top_score = 100
    elif 50 <= top_long_pct < 55:
        top_score = 70 + (top_long_pct - 50) / 5 * 30
    elif 70 < top_long_pct <= 80:
        top_score = 80 - (top_long_pct - 70) / 10 * 30
    else:
        top_score = max(20, 50 - abs(top_long_pct - 60))

    return top_score


def score_taker_buy_sell(taker_data):
    """主动买卖比评分 - 主动买入多得高分"""
    if not taker_data:
        return 50
    latest = taker_data[-1] if taker_data else {}
    buy_vol = float(latest.get("buySellRatio", 1)) 

    # buySellRatio > 1 表示买盘主导
    if buy_vol >= 1.3:
        return 100
    elif buy_vol >= 1.1:
        return 80 + (buy_vol - 1.1) / 0.2 * 20
    elif buy_vol >= 0.9:
        return 60 + (buy_vol - 0.9) / 0.2 * 20
    elif buy_vol >= 0.7:
        return 40 + (buy_vol - 0.7) / 0.2 * 20
    else:
        return max(10, buy_vol / 0.7 * 40)


def score_oi_trend(oi_hist):
    """OI趋势评分 - OI持续增加得高分"""
    if not oi_hist or len(oi_hist) < 2:
        return 50

    values = [float(o.get("sumOpenInterestValue", 0)) for o in oi_hist]
    if not values or values[0] == 0:
        return 50

    # 计算趋势
    changes = []
    for i in range(1, len(values)):
        if values[i-1] > 0:
            changes.append((values[i] - values[i-1]) / values[i-1] * 100)

    if not changes:
        return 50

    # 正向趋势天数
    positive_days = sum(1 for c in changes if c > 0)
    total_change = (values[-1] - values[0]) / values[0] * 100

    score = 50
    # 总变化
    if total_change > 20: score += 30
    elif total_change > 10: score += 20
    elif total_change > 0: score += 10
    elif total_change > -10: score += 0
    else: score -= 20

    # 趋势一致性
    consistency = positive_days / len(changes)
    score += consistency * 20

    return min(100, max(0, score))


def score_whale_divergence(top_pos, global_ls):
    """散户vs大户分歧评分 - 散户空+大户多=最强信号"""
    if not top_pos or not global_ls:
        return 50

    top_long = float(top_pos[-1].get("longAccount", 0.5)) * 100
    retail_long = float(global_ls[-1].get("longAccount", 0.5)) * 100

    divergence = top_long - retail_long

    # 大户比散户更看多 = 正分歧 (看多信号)
    if divergence > 15:
        return 100  # 大户显著比散户更看多
    elif divergence > 5:
        return 80 + (divergence - 5) / 10 * 20
    elif divergence > -5:
        return 60 + (divergence + 5) / 10 * 20
    elif divergence > -15:
        return 40 + (divergence + 15) / 10 * 20
    else:
        return max(20, 40 + divergence)  # 散户比大户更看多 (危险)


def score_capital_flow(taker_data, oi_hist):
    """资金流向评分 - 买盘+OI增加=资金流入"""
    if not taker_data or not oi_hist:
        return 50

    latest_taker = taker_data[-1] if taker_data else {}
    buy_ratio = float(latest_taker.get("buySellRatio", 1))

    oi_values = [float(o.get("sumOpenInterestValue", 0)) for o in oi_hist]
    oi_change = (oi_values[-1] - oi_values[0]) / oi_values[0] * 100 if oi_values[0] > 0 else 0

    score = 50
    # 买盘主导 + OI增加 = 资金流入
    if buy_ratio > 1.1 and oi_change > 5:
        score = 100
    elif buy_ratio > 1.0 and oi_change > 0:
        score = 80
    elif buy_ratio > 0.9 and oi_change > -5:
        score = 60
    elif buy_ratio < 0.9 and oi_change < -5:
        score = 20  # 资金流出

    return min(100, max(0, score))


# ============================================================
# 维度三: 情绪面评分
# ============================================================

def score_square_heat(square_data, symbol):
    """币安广场热度评分"""
    if not square_data:
        return 50

    windows = square_data.get("windows", {})

    # 检查1h和24h窗口
    heat_score = 50
    for window in ["1h", "24h"]:
        w = windows.get(window, {}).get("non_majors", {})
        combined = w.get("combined", [])
        mentions = w.get("mentions", [])
        homepage = w.get("homepage_exposure", [])

        # 在combined列表中的排名
        for i, item in enumerate(combined):
            if item.get("symbol", "").upper() == symbol.replace("USDT", ""):
                rank_score = max(0, 100 - i * 10)
                heat_score = max(heat_score, rank_score)
                break

        # 在mentions列表中
        for i, item in enumerate(mentions):
            if item.get("symbol", "").upper() == symbol.replace("USDT", ""):
                mention_score = max(0, 90 - i * 8)
                heat_score = max(heat_score, mention_score)
                break

    return heat_score


def score_fear_greed(square_data):
    """恐惧贪婪指数评分 - 适度恐惧时入场最佳"""
    if not square_data:
        return 50

    # 从insights中获取恐惧贪婪数据
    fg = square_data.get("fear_greed", {})
    value = fg.get("value", 50)

    # 最佳入场: 恐惧区间 (25-45)
    if 25 <= value <= 45:
        return 100
    elif 15 <= value < 25:
        return 80
    elif 45 < value <= 55:
        return 70
    elif 55 < value <= 70:
        return 50
    elif value > 70:
        return 30  # 极度贪婪，危险
    else:
        return 60  # 极度恐惧，有机会但风险大


def score_narrative_shift(square_data, symbol):
    """叙事切换评分 - 叙事变化=新资金关注"""
    if not square_data:
        return 50

    insights = square_data.get("insights", {})
    events = insights.get("events_1h", [])
    narratives = insights.get("narratives_24h", [])

    base_sym = symbol.replace("USDT", "").upper()

    # 检查是否有叙事切换事件
    for event in events:
        if base_sym in str(event).upper():
            return 100

    # 检查是否在新叙事中
    for n in narratives:
        if base_sym in str(n).upper():
            return 80

    return 50


def score_sentiment_extreme(global_ls, taker_data):
    """情绪极端值评分 - 散户极度看空时反转做多"""
    if not global_ls:
        return 50

    retail_long = float(global_ls[-1].get("longAccount", 0.5)) * 100

    # 散户极度看空 (< 35% 多头) = 反转做多信号
    if retail_long < 35:
        return 100  # 极度看空，反转机会
    elif retail_long < 40:
        return 85
    elif retail_long < 45:
        return 70
    elif retail_long < 55:
        return 55  # 中性
    elif retail_long < 65:
        return 45
    elif retail_long < 75:
        return 30  # 偏多
    else:
        return 15  # 极度看多，危险


def score_social_volume(square_data, symbol):
    """社交讨论量评分"""
    if not square_data:
        return 50

    windows = square_data.get("windows", {})
    for window in ["1h", "24h"]:
        w = windows.get(window, {}).get("non_majors", {})
        mentions = w.get("mentions", [])
        for i, item in enumerate(mentions):
            if item.get("symbol", "").upper() == symbol.replace("USDT", ""):
                count = item.get("count", 0)
                if count > 100: return 100
                if count > 50: return 80
                if count > 20: return 60
                if count > 5: return 40
                return 20

    return 50


# ============================================================
# 妖币检测器 v2.0
# ============================================================

class DemonCoinDetectorV2:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.results = []
        self.square_data = None
        self.alerts = None

    def scan(self, top=50):
        print(f"\n{'='*140}")
        print("🔥 妖币检测器 v2.0 - 三维立体扫描")
        print(f"{'='*140}")
        print(f"维度一: 市场筛选 (40%) | 维度二: 持仓分析 (35%) | 维度三: 情绪面 (25%)")
        print(f"{'='*140}")

        # 预加载广场数据
        print("\n📡 加载币安广场数据...")
        self.square_data = fetch_square_radar()
        self.alerts = fetch_alerts()

        # 获取主榜
        print(f"📊 扫描 Top {top} 合约...")
        board = fetch_perp_board(top)
        if not board:
            print("❌ 获取数据失败")
            return []

        print(f"✅ 获取到 {len(board)} 个合约")

        self.results = []
        for i, row in enumerate(board):
            symbol = row.get("symbol", "")
            if self.verbose:
                print(f"  [{i+1}/{len(board)}] {symbol}...")

            result = self._analyze(symbol, row)
            if result:
                self.results.append(result)

            if i % 10 == 9:
                time.sleep(0.3)

        self.results.sort(key=lambda x: x["total_score"], reverse=True)
        return self.results

    def _analyze(self, symbol, board_row):
        chg = board_row.get("price_change_percent", 0)
        vol = board_row.get("quote_volume", 0)
        oi_val = board_row.get("oi_value") or 0
        oi_24h = board_row.get("oi_change_24h_pct") or 0
        oi_1h = board_row.get("oi_change_1h_pct") or 0
        signal = board_row.get("signal_label", "")
        mcap = board_row.get("market_cap_value") or 0
        price = board_row.get("last_price", 0)
        vol_oi = vol / oi_val if oi_val > 0 else 0

        # --- 维度一: 市场筛选 ---
        fr_data = fetch_bn_funding(symbol, 3)
        rates = [float(f["fundingRate"]) for f in fr_data] if fr_data else [0]
        avg_fr = sum(rates) / len(rates) if rates else 0

        ls_data = fetch_bn_global_ls(symbol, "1d", 1)
        ls_ratio = float(ls_data[-1]["longShortRatio"]) if ls_data else 0

        mkt_scores = {
            "price_momentum": s_price(chg),
            "oi_surge": s_oi(oi_24h, oi_1h),
            "vol_oi_ratio": s_vol_oi(vol_oi),
            "funding_rate": s_fr(avg_fr * 100),
            "long_short_ratio": s_ls(ls_ratio),
            "market_cap": s_mcap(mcap),
            "signal": s_signal(signal),
        }
        mkt_total = sum(mkt_scores[k] * Config.MARKET_WEIGHTS[k] for k in mkt_scores)

        # --- 维度二: 持仓分析 ---
        oi_hist = fetch_bn_oi_hist(symbol, "1d", 7)
        top_pos = fetch_bn_top_ls(symbol, "1d", 7)
        taker = fetch_bn_taker(symbol, "1d", 7)

        pos_scores = {
            "top_trader_bias": score_top_trader_bias(top_pos, ls_data),
            "taker_buy_sell": score_taker_buy_sell(taker),
            "oi_trend": score_oi_trend(oi_hist),
            "whale_divergence": score_whale_divergence(top_pos, ls_data),
            "capital_flow": score_capital_flow(taker, oi_hist),
        }
        pos_total = sum(pos_scores[k] * Config.POSITION_WEIGHTS[k] for k in pos_scores)

        # --- 维度三: 情绪面 ---
        sent_scores = {
            "square_heat": score_square_heat(self.square_data, symbol),
            "fear_greed": score_fear_greed(self.square_data),
            "narrative_shift": score_narrative_shift(self.square_data, symbol),
            "sentiment_extreme": score_sentiment_extreme(ls_data, taker),
            "social_volume": score_social_volume(self.square_data, symbol),
        }
        sent_total = sum(sent_scores[k] * Config.SENTIMENT_WEIGHTS[k] for k in sent_scores)

        # --- 综合评分 ---
        total = (
            mkt_total * Config.WEIGHTS["market"] +
            pos_total * Config.WEIGHTS["position"] +
            sent_total * Config.WEIGHTS["sentiment"]
        )

        # --- 风险标记 ---
        risks = []
        if avg_fr * 100 > Config.THRESH["fr_danger"]: risks.append("费率过热")
        if ls_ratio > Config.THRESH["ls_danger"]: risks.append("多空比极端")
        if oi_1h > 10: risks.append("1h OI暴增")
        if chg > 30: risks.append("涨幅过大")

        # 逆向风险 (散户极度看多)
        retail_long = float(ls_data[-1].get("longAccount", 0.5)) * 100 if ls_data else 50
        if retail_long > 75: risks.append("散户极度看多⚠️")

        # --- 洞察 ---
        insights = []
        if chg > 5 and oi_24h > 15:
            insights.append("📈 价格+OI同步上涨")
        if vol_oi > 5:
            insights.append("🔥 成交极度活跃")
        if 0.005 <= avg_fr * 100 <= 0.03:
            insights.append("💰 费率温和看多")
        if mcap and mcap < 50e6:
            insights.append("🎯 小市值易拉")
        if retail_long < 40:
            insights.append("🐻 散户极度看空→反转机会")
        if retail_long > 70:
            insights.append("⚠️ 散户极度看多→谨慎")

        # 持仓分析洞察
        top_long = float(top_pos[-1].get("longAccount", 0.5)) * 100 if top_pos else 50
        if top_long > 65 and retail_long < 50:
            insights.append("🐳 大户看多+散户看空=强烈信号")

        taker_ratio = float(taker[-1].get("buySellRatio", 1)) if taker else 1
        if taker_ratio > 1.3:
            insights.append("🛒 主动买入强势")
        elif taker_ratio < 0.7:
            insights.append("💸 主动卖出强势")

        return {
            "symbol": symbol, "price": price, "change_24h": chg,
            "volume": vol, "oi_value": oi_val, "oi_change_24h": oi_24h,
            "oi_change_1h": oi_1h, "vol_oi_ratio": vol_oi,
            "avg_fr": avg_fr, "ls_ratio": ls_ratio, "mcap": mcap,
            "signal": signal,
            "mkt_scores": mkt_scores, "mkt_total": mkt_total,
            "pos_scores": pos_scores, "pos_total": pos_total,
            "sent_scores": sent_scores, "sent_total": sent_total,
            "total_score": total,
            "risk_flags": risks, "insights": insights,
            "retail_long_pct": retail_long,
            "top_long_pct": top_long,
            "taker_ratio": taker_ratio,
        }

    def print_report(self, top_n=20):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*150}")
        print("🔥 妖币检测器 v2.0 - 三维立体扫描报告")
        print(f"{'='*150}")
        print(f"⏰ 扫描时间: {now}")
        print(f"📊 扫描范围: Binance USDT 永续合约")
        print(f"🧬 检测模型: 市场筛选(40%) × 持仓分析(35%) × 情绪面(25%)")
        print(f"{'='*150}")

        print(f"\n🏆 TOP {top_n} 潜在妖币 (三维综合评分)")
        print("-" * 150)
        print(f"{'排名':<3} {'合约':<14} {'总分':>5} {'市场':>5} {'持仓':>5} {'情绪':>5} {'价格':>9} {'24h%':>7} {'OI%':>7} {'费率':>8} {'散户多':>7} {'大户多':>7} {'Taker':>6} {'风险':>14} {'建议':>10}")
        print("-" * 150)

        for i, r in enumerate(self.results[:top_n], 1):
            if r["total_score"] >= 80: rating = "🔥 强烈关注"
            elif r["total_score"] >= 65: rating = "✅ 推荐"
            elif r["total_score"] >= 50: rating = "🟡 观察"
            else: rating = "⚪ 暂缓"

            risk_str = ",".join(r["risk_flags"][:2]) if r["risk_flags"] else "✅"
            print(f"{i:<3} {r['symbol']:<14} {r['total_score']:>5.1f} {r['mkt_total']:>5.1f} {r['pos_total']:>5.1f} {r['sent_total']:>5.1f} {r['price']:>9.4f} {r['change_24h']:>+6.2f}% {r['oi_change_24h']:>+6.2f}% {r['avg_fr']*100:>+7.4f}% {r['retail_long_pct']:>6.1f}% {r['top_long_pct']:>6.1f}% {r['taker_ratio']:>6.2f} {risk_str:>14} {rating:>10}")

        # TOP 5 详细分析
        print(f"\n{'='*150}")
        print("📋 TOP 5 三维详细分析:")
        print(f"{'='*150}")

        for i, r in enumerate(self.results[:5], 1):
            print(f"\n{'─'*100}")
            print(f" #{i} {r['symbol']} - 综合: {r['total_score']:.1f}/100 | 市场:{r['mkt_total']:.1f} | 持仓:{r['pos_total']:.1f} | 情绪:{r['sent_total']:.1f}")
            print(f"{'─'*100}")

            print(f"  📊 市场筛选 ({r['mkt_total']:.1f}/100):")
            for k, v in r["mkt_scores"].items():
                bar = "█" * int(v / 5) + "░" * (20 - int(v / 5))
                print(f"     {k:<18} {bar} {v:.0f}")

            print(f"\n  🐳 持仓分析 ({r['pos_total']:.1f}/100):")
            for k, v in r["pos_scores"].items():
                bar = "█" * int(v / 5) + "░" * (20 - int(v / 5))
                print(f"     {k:<18} {bar} {v:.0f}")

            print(f"\n  🧠 情绪面 ({r['sent_total']:.1f}/100):")
            for k, v in r["sent_scores"].items():
                bar = "█" * int(v / 5) + "░" * (20 - int(v / 5))
                print(f"     {k:<18} {bar} {v:.0f}")

            if r["insights"]:
                print(f"\n  💡 洞察:")
                for ins in r["insights"]:
                    print(f"     {ins}")

            if r["risk_flags"]:
                print(f"\n  ⚠️ 风险: {', '.join(r['risk_flags'])}")

        # 妖币 DNA
        print(f"\n{'='*150}")
        print("🧬 妖币 DNA (三维特征):")
        print(f"{'='*150}")
        print("""
  ┌─────────────────────────────────────────────────────────────────────┐
  │ 维度一: 市场筛选 (40%)                                              │
  │  ✅ 24h涨幅 5-15%     ✅ OI 24h > 15%      ✅ 成交/OI > 3.0       │
  │  ✅ 费率 0.005-0.03%  ✅ 多空比 1.5-2.5    ✅ 市值 < $100M         │
  ├─────────────────────────────────────────────────────────────────────┤
  │ 维度二: 持仓分析 (35%)                                              │
  │  ✅ 大户多头 55-70%   ✅ Taker买>卖        ✅ OI趋势向上            │
  │  ✅ 大户>散户看多     ✅ 资金净流入                                 │
  ├─────────────────────────────────────────────────────────────────────┤
  │ 维度三: 情绪面 (25%)                                                │
  │  ✅ 广场热度上升      ✅ 恐惧贪婪 25-45     ✅ 叙事切换              │
  │  ✅ 散户极度看空(反)  ✅ 社交讨论量增                               │
  └─────────────────────────────────────────────────────────────────────┘

  ⚠️ 危险信号 (回避):
  • 费率 > 0.05% | 多空比 > 3.0 | 散户多头 > 75% | OI 1h暴增 > 10%
""")
        print(f"{'='*150}")
        print("⚠️ 风险提示: 合约交易具有高风险，以上分析仅供参考，不构成投资建议")
        print(f"{'='*150}")

    def get_top_alerts(self, min_score=70):
        return [r for r in self.results if r["total_score"] >= min_score]


# ============================================================
# 主程序
# ============================================================

def main():
    import argparse
    p = argparse.ArgumentParser(description="🔥 妖币检测器 v2.0")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--show", type=int, default=20)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    det = DemonCoinDetectorV2(verbose=args.verbose)
    results = det.scan(top=args.top)

    if args.json:
        print(json.dumps(results[:args.show], indent=2, ensure_ascii=False))
    else:
        det.print_report(top_n=args.show)

    return results


if __name__ == "__main__":
    main()
