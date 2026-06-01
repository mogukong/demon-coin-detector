#!/usr/bin/env python3
"""
🔥 妖币检测器 v3.0 - 六维终极扫描
====================================
从 RIVER/RAVE/BEAT/MAVIA/ALT 等妖币案例提取的终极检测模型

六维评分体系:
  1. 换手率 (15%) - 是不是开始活跃?
  2. 动能 (20%) - 是不是刚启动，而不是已经冲太高?
  3. 市值结构 (15%) - 是不是还有空间?
  4. 流动性 (15%) - 能不能进出?
  5. 社交热度 (15%) - 有没有开始被讨论?
  6. 风险集中度 (20%) - 是不是过度控盘/捆绑/开发者持仓太高?
"""

import json
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.request import urlopen, Request
from urllib.error import URLError


# ============================================================
# 数据获取
# ============================================================

def fetch(url, timeout=8):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 DemonCoin/3.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except:
        return None

def fetch_board(top=50):
    d = fetch(f"https://perp.shouyetech.com/api/board?top={top}")
    return d.get("gainers_rows", []) if d and d.get("ok") else []

def fetch_square_radar():
    return fetch("https://perp.shouyetech.com/api/square-radar/overview")

def fetch_alerts():
    return fetch("https://perp.shouyetech.com/api/alerts")

def fetch_ticker(sym):
    return fetch(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}")

def fetch_depth(sym, limit=20):
    return fetch(f"https://fapi.binance.com/fapi/v1/depth?symbol={sym}&limit={limit}")

def fetch_klines(sym, interval="4h", limit=30):
    return fetch(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}")

def fetch_funding(sym, limit=8):
    return fetch(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit={limit}") or []

def fetch_oi_hist(sym, limit=7):
    return fetch(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=1d&limit={limit}") or []

def fetch_top_ls(sym, limit=7):
    return fetch(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={sym}&period=1d&limit={limit}") or []

def fetch_global_ls(sym, limit=7):
    return fetch(f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={sym}&period=1d&limit={limit}") or []

def fetch_taker(sym, limit=7):
    return fetch(f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={sym}&period=1d&limit={limit}") or []


# ============================================================
# 维度一: 换手率 (Turnover Rate)
# ============================================================

def calc_turnover(ticker_data, board_row):
    """
    换手率 = 成交活跃度
    指标:
    - 成交笔数 (count) - 越高越活跃
    - 平均单笔金额 (quoteVolume/count) - 机构vs散户
    - 成交额/OI比 - 换手速度
    """
    count = ticker_data.get("count", 0) if ticker_data else 0
    quote_vol = ticker_data.get("quoteVolume", 0) if ticker_data else 0
    quote_vol = float(quote_vol)
    count = int(count)

    oi_val = board_row.get("oi_value") or 0
    vol = board_row.get("quote_volume", 0)

    # 平均单笔金额
    avg_trade = quote_vol / count if count > 0 else 0

    # 成交额/OI比 (换手速度)
    vol_oi = vol / oi_val if oi_val > 0 else 0

    # 评分
    score = 0

    # 成交笔数评分 (0-40)
    if count > 1000000: score += 40
    elif count > 500000: score += 30
    elif count > 100000: score += 20
    elif count > 50000: score += 10
    else: score += 5

    # 换手速度评分 (0-35)
    if vol_oi > 10: score += 35
    elif vol_oi > 5: score += 28
    elif vol_oi > 3: score += 21
    elif vol_oi > 1: score += 14
    else: score += 7

    # 平均单笔金额合理性 (0-25)
    # $10-$200 = 散户活跃，合理；太大=机构，太小=bot
    if 10 <= avg_trade <= 200: score += 25
    elif 5 <= avg_trade < 10: score += 18
    elif 200 < avg_trade <= 500: score += 15
    elif avg_trade > 500: score += 8  # 可能是机构
    else: score += 5  # 太小，可能是bot

    return min(100, score), {
        "trade_count": count,
        "avg_trade_usd": round(avg_trade, 2),
        "vol_oi_ratio": round(vol_oi, 2),
    }


# ============================================================
# 维度二: 动能 (Momentum)
# ============================================================

def calc_momentum(klines_4h, klines_1h, board_row):
    """
    动能 = 是不是刚启动?
    指标:
    - 距离24h高点 (越近=动能强但可能见顶)
    - 4h涨速 (价格变化/h)
    - 1h vs 4h动量对比 (加速还是减速)
    - OI变化方向
    """
    chg_24h = board_row.get("price_change_percent", 0)
    oi_chg_24h = board_row.get("oi_change_24h_pct") or 0
    oi_chg_1h = board_row.get("oi_change_1h_pct") or 0

    # 从klines计算涨速
    price_vel_4h = 0
    price_vel_1h = 0
    dist_from_high = 0

    if klines_4h and len(klines_4h) >= 2:
        # 4h价格变化率
        opens = [float(k[1]) for k in klines_4h]
        closes = [float(k[4]) for k in klines_4h]
        highs = [float(k[2]) for k in klines_4h]

        if opens[-1] > 0:
            price_vel_4h = (closes[-1] - opens[-1]) / opens[-1] * 100

        # 距离近期高点
        recent_high = max(highs[-6:]) if len(highs) >= 6 else max(highs)
        if recent_high > 0:
            dist_from_high = (recent_high - closes[-1]) / recent_high * 100

    if klines_1h and len(klines_1h) >= 2:
        opens_1h = [float(k[1]) for k in klines_1h]
        closes_1h = [float(k[4]) for k in klines_1h]
        if opens_1h[-1] > 0:
            price_vel_1h = (closes_1h[-1] - opens_1h[-1]) / opens_1h[-1] * 100

    # 评分
    score = 0

    # 24h涨幅合理性 (0-30) - 5-15%最佳
    if 5 <= chg_24h <= 15: score += 30
    elif 3 <= chg_24h < 5: score += 20
    elif 15 < chg_24h <= 25: score += 20
    elif 1 <= chg_24h < 3: score += 10
    elif chg_24h > 25: score += 5  # 可能见顶
    else: score += 0

    # 距离高点 (0-25) - 离高点不太远也不太近
    if 2 <= dist_from_high <= 8: score += 25  # 刚回调一点，还有空间
    elif 0 <= dist_from_high < 2: score += 15  # 接近高点，可能突破或见顶
    elif 8 < dist_from_high <= 15: score += 20  # 回调较多，可能反弹
    elif dist_from_high > 15: score += 10  # 回调太深
    else: score += 10

    # OI配合 (0-25) - 价格涨+OI涨=真涨
    if chg_24h > 0 and oi_chg_24h > 10: score += 25
    elif chg_24h > 0 and oi_chg_24h > 0: score += 18
    elif chg_24h > 0 and oi_chg_24h > -5: score += 10
    elif chg_24h > 0 and oi_chg_24h < -10: score += 5  # 价格涨但OI跌=逼空
    else: score += 0

    # 1h加速 (0-20) - 短期动能
    if oi_chg_1h > 5: score += 20  # OI 1h暴增
    elif oi_chg_1h > 2: score += 15
    elif oi_chg_1h > 0: score += 10
    elif oi_chg_1h > -2: score += 5

    return min(100, score), {
        "price_vel_4h": round(price_vel_4h, 2),
        "price_vel_1h": round(price_vel_1h, 2),
        "dist_from_high": round(dist_from_high, 2),
        "chg_24h": chg_24h,
    }


# ============================================================
# 维度三: 市值结构 (Market Cap Structure)
# ============================================================

def calc_mcap_structure(board_row):
    """
    市值结构 = 还有多少空间?
    指标:
    - 市值大小 (越小越容易拉)
    - 市值/成交额比 (估值合理性)
    - 市值区间评分
    """
    mcap = board_row.get("market_cap_value") or 0
    vol = board_row.get("quote_volume", 0)
    oi = board_row.get("oi_value") or 0

    # 市值/成交额比
    mcap_vol = mcap / vol if vol > 0 else 0

    # 市值/OI比
    mcap_oi = mcap / oi if oi > 0 else 0

    score = 0

    # 市值大小 (0-40)
    if mcap <= 0:
        score += 20  # 未知
    elif mcap <= 20e6:
        score += 40  # 微盘，最容易拉
    elif mcap <= 50e6:
        score += 35  # 小盘
    elif mcap <= 100e6:
        score += 28  # 中小盘
    elif mcap <= 200e6:
        score += 20  # 中盘
    elif mcap <= 500e6:
        score += 12  # 中大盘
    else:
        score += 5   # 大盘

    # 市值/成交额比 (0-30) - 比值小=流动性好/估值低
    if mcap_vol <= 0:
        score += 15
    elif mcap_vol <= 2:
        score += 30  # 成交额超过市值一半，极度活跃
    elif mcap_vol <= 5:
        score += 25
    elif mcap_vol <= 10:
        score += 18
    elif mcap_vol <= 20:
        score += 10
    else:
        score += 5

    # 市值/OI比 (0-30) - OI相对市值大=杠杆高
    if mcap_oi <= 0:
        score += 15
    elif mcap_oi <= 5:
        score += 30  # OI占比高，杠杆效应大
    elif mcap_oi <= 10:
        score += 22
    elif mcap_oi <= 20:
        score += 15
    else:
        score += 8

    return min(100, score), {
        "mcap_millions": round(mcap / 1e6, 2) if mcap else 0,
        "mcap_vol_ratio": round(mcap_vol, 2),
        "mcap_oi_ratio": round(mcap_oi, 2),
    }


# ============================================================
# 维度四: 流动性 (Liquidity)
# ============================================================

def calc_liquidity(depth_data, ticker_data):
    """
    流动性 = 能不能进出?
    指标:
    - 买卖价差 (spread) - 越小越好
    - 订单簿深度 (bid/ask总量)
    - 订单簿不平衡度 (bid>ask=买压)
    - 成交密度 (trades/min)
    """
    spread_bps = 0
    bid_depth = 0
    ask_depth = 0
    imbalance = 0

    if depth_data:
        bids = depth_data.get("bids", [])
        asks = depth_data.get("asks", [])

        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid = (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) / mid * 10000 if mid > 0 else 0

            bid_depth = sum(float(b[1]) * float(b[0]) for b in bids[:10])
            ask_depth = sum(float(a[1]) * float(a[0]) for a in asks[:10])
            total = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total if total > 0 else 0

    # 成交密度
    count = int(ticker_data.get("count", 0)) if ticker_data else 0
    trades_per_min = count / (24 * 60)

    score = 0

    # 价差 (0-30) - 越小越好
    if spread_bps <= 1: score += 30
    elif spread_bps <= 3: score += 25
    elif spread_bps <= 5: score += 20
    elif spread_bps <= 10: score += 12
    elif spread_bps <= 20: score += 5
    else: score += 0

    # 深度 (0-30)
    total_depth = bid_depth + ask_depth
    if total_depth > 1e6: score += 30
    elif total_depth > 500e3: score += 25
    elif total_depth > 100e3: score += 18
    elif total_depth > 50e3: score += 10
    else: score += 5

    # 订单簿不平衡 (0-20) - 正=买压
    if imbalance > 0.2: score += 20  # 买压强
    elif imbalance > 0.1: score += 15
    elif imbalance > 0: score += 10
    elif imbalance > -0.1: score += 5
    else: score += 0  # 卖压重

    # 成交密度 (0-20)
    if trades_per_min > 500: score += 20
    elif trades_per_min > 100: score += 15
    elif trades_per_min > 50: score += 10
    elif trades_per_min > 10: score += 5
    else: score += 0

    return min(100, score), {
        "spread_bps": round(spread_bps, 2),
        "bid_depth_usd": round(bid_depth, 0),
        "ask_depth_usd": round(ask_depth, 0),
        "imbalance": round(imbalance, 3),
        "trades_per_min": round(trades_per_min, 1),
    }


# ============================================================
# 维度五: 社交热度 (Social Heat)
# ============================================================

def calc_social_heat(square_data, symbol):
    """
    社交热度 = 有没有开始被讨论?
    指标:
    - 广场热度排名
    - 提及量变化
    - 叙事切换
    - 热度/市值比 (小市值+高热度=妖币信号)
    """
    base_sym = symbol.replace("USDT", "").upper()

    heat_rank = 999
    mention_count = 0
    has_narrative_shift = False
    homepage_exposure = False

    if square_data:
        windows = square_data.get("windows", {})
        for window in ["1h", "24h"]:
            w = windows.get(window, {}).get("non_majors", {})

            # Combined排名
            for i, item in enumerate(w.get("combined", [])):
                if item.get("symbol", "").upper() == base_sym:
                    heat_rank = min(heat_rank, i + 1)
                    break

            # 提及量
            for item in w.get("mentions", []):
                if item.get("symbol", "").upper() == base_sym:
                    mention_count = max(mention_count, item.get("count", 0))
                    break

            # 首页曝光
            for item in w.get("homepage_exposure", []):
                if item.get("symbol", "").upper() == base_sym:
                    homepage_exposure = True
                    break

        # 叙事切换
        insights = square_data.get("insights", {})
        events = insights.get("events_1h", [])
        for event in events:
            if base_sym in str(event).upper():
                has_narrative_shift = True

    score = 0

    # 热度排名 (0-30)
    if heat_rank <= 3: score += 30
    elif heat_rank <= 5: score += 25
    elif heat_rank <= 10: score += 18
    elif heat_rank <= 20: score += 10
    else: score += 0

    # 提及量 (0-25)
    if mention_count > 100: score += 25
    elif mention_count > 50: score += 20
    elif mention_count > 20: score += 15
    elif mention_count > 5: score += 8
    else: score += 0

    # 叙事切换 (0-25)
    if has_narrative_shift: score += 25
    else: score += 5

    # 首页曝光 (0-20)
    if homepage_exposure: score += 20
    else: score += 0

    return min(100, score), {
        "heat_rank": heat_rank,
        "mention_count": mention_count,
        "narrative_shift": has_narrative_shift,
        "homepage": homepage_exposure,
    }


# ============================================================
# 维度六: 风险集中度 (Risk Concentration)
# ============================================================

def calc_risk_concentration(top_ls, global_ls, taker, funding, board_row):
    """
    风险集中度 = 是不是过度控盘?
    指标:
    - 散户vs大户分歧 (分歧大=大户控盘)
    - 多空比极端度 (>3.0=极度拥挤)
    - 资金费率极端度 (>0.05%=过热)
    - Taker单边主导 (极端=可能被操纵)
    - OI集中度 (从OI变化推断)
    """
    chg_24h = board_row.get("price_change_percent", 0)
    oi_chg_1h = board_row.get("oi_change_1h_pct") or 0

    # 大户vs散户
    top_long = float(top_ls[-1].get("longAccount", 0.5)) * 100 if top_ls else 50
    retail_long = float(global_ls[-1].get("longAccount", 0.5)) * 100 if global_ls else 50
    divergence = abs(top_long - retail_long)

    # 多空比
    ls_ratio = float(global_ls[-1].get("longShortRatio", 1)) if global_ls else 1

    # 资金费率
    rates = [float(f["fundingRate"]) * 100 for f in funding] if funding else [0]
    avg_fr = sum(rates) / len(rates) if rates else 0
    max_fr = max(rates) if rates else 0

    # Taker方向
    taker_ratio = float(taker[-1].get("buySellRatio", 1)) if taker else 1

    score = 100  # 从满分扣分 (风险越低分越高)

    risks = []

    # 散户vs大户分歧 (-20)
    if divergence > 20:
        score -= 20
        risks.append("大户散户严重分歧")
    elif divergence > 15:
        score -= 15
        risks.append("大户散户较大分歧")
    elif divergence > 10:
        score -= 8

    # 多空比极端 (-20)
    if ls_ratio > 3.0:
        score -= 20
        risks.append("散户极度看多")
    elif ls_ratio > 2.5:
        score -= 12
        risks.append("散户偏多")
    elif ls_ratio < 0.7:
        score -= 15
        risks.append("散户极度看空")

    # 资金费率极端 (-15)
    if abs(avg_fr) > 0.05:
        score -= 15
        risks.append("费率极端")
    elif abs(avg_fr) > 0.03:
        score -= 8

    # Taker单边 (-15)
    if taker_ratio > 1.5:
        score -= 10
        risks.append("买盘单边主导")
    elif taker_ratio < 0.6:
        score -= 15
        risks.append("卖盘单边主导")

    # OI 1h暴增 (-15)
    if oi_chg_1h > 10:
        score -= 15
        risks.append("OI短期暴增")
    elif oi_chg_1h > 5:
        score -= 8

    # 涨幅过大 (-15)
    if chg_24h > 30:
        score -= 15
        risks.append("涨幅过大")
    elif chg_24h > 20:
        score -= 8

    return max(0, score), {
        "top_long_pct": round(top_long, 1),
        "retail_long_pct": round(retail_long, 1),
        "divergence": round(divergence, 1),
        "ls_ratio": round(ls_ratio, 2),
        "avg_funding": round(avg_fr, 4),
        "taker_ratio": round(taker_ratio, 2),
        "risk_flags": risks,
    }


# ============================================================
# 妖币检测器 v3.0
# ============================================================

class DemonCoinDetectorV3:
    WEIGHTS = {
        "turnover": 0.15,
        "momentum": 0.20,
        "mcap_structure": 0.15,
        "liquidity": 0.15,
        "social_heat": 0.15,
        "risk_concentration": 0.20,
    }

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.results = []
        self.square_data = None

    def scan(self, top=50):
        print(f"\n{'='*160}")
        print("🔥 妖币检测器 v3.0 - 六维终极扫描")
        print(f"{'='*160}")
        print("维度一: 换手率 (15%) | 维度二: 动能 (20%) | 维度三: 市值结构 (15%)")
        print("维度四: 流动性 (15%) | 维度五: 社交热度 (15%) | 维度六: 风险集中度 (20%)")
        print(f"{'='*160}")

        print("\n📡 加载广场数据...")
        self.square_data = fetch_square_radar()

        print(f"📊 扫描 Top {top} 合约...")
        board = fetch_board(top)
        print(f"✅ 获取到 {len(board)} 个合约")

        self.results = []
        for i, row in enumerate(board):
            sym = row.get("symbol", "")
            if self.verbose:
                print(f"  [{i+1}/{len(board)}] {sym}...")

            result = self._analyze(sym, row)
            if result:
                self.results.append(result)

            if i % 10 == 9:
                time.sleep(0.3)

        self.results.sort(key=lambda x: x["total"], reverse=True)
        return self.results

    def _analyze(self, sym, row):
        # 并行获取数据
        ticker = fetch_ticker(sym)
        depth = fetch_depth(sym, 20)
        klines_4h = fetch_klines(sym, "4h", 30)
        klines_1h = fetch_klines(sym, "1h", 24)
        funding = fetch_funding(sym, 8)
        oi_hist = fetch_oi_hist(sym, 7)
        top_ls = fetch_top_ls(sym, 7)
        global_ls = fetch_global_ls(sym, 7)
        taker = fetch_taker(sym, 7)

        # 六维评分
        s1, d1 = calc_turnover(ticker, row)
        s2, d2 = calc_momentum(klines_4h, klines_1h, row)
        s3, d3 = calc_mcap_structure(row)
        s4, d4 = calc_liquidity(depth, ticker)
        s5, d5 = calc_social_heat(self.square_data, sym)
        s6, d6 = calc_risk_concentration(top_ls, global_ls, taker, funding, row)

        # 加权总分
        total = (
            s1 * self.WEIGHTS["turnover"] +
            s2 * self.WEIGHTS["momentum"] +
            s3 * self.WEIGHTS["mcap_structure"] +
            s4 * self.WEIGHTS["liquidity"] +
            s5 * self.WEIGHTS["social_heat"] +
            s6 * self.WEIGHTS["risk_concentration"]
        )

        # 洞察
        insights = []
        if d1["vol_oi_ratio"] > 5: insights.append("🔥 换手率极高")
        if d2["chg_24h"] > 5 and d2["dist_from_high"] < 5: insights.append("📈 接近高点，可能突破")
        if d2["chg_24h"] > 5 and 2 <= d2["dist_from_high"] <= 8: insights.append("🎯 刚回调，动能充足")
        if d3["mcap_millions"] < 50: insights.append("💎 小市值，空间大")
        if d4["imbalance"] > 0.2: insights.append("📊 买盘深度占优")
        if d5["narrative_shift"]: insights.append("📰 叙事切换中")
        if d5["mention_count"] > 50: insights.append("🗣️ 社交热度高")
        if d6["divergence"] > 15 and d6["top_long_pct"] > d6["retail_long_pct"]:
            insights.append("🐳 大户比散户更看多")
        if d6["retail_long_pct"] < 40:
            insights.append("🐻 散户极度看空→反转信号")

        return {
            "symbol": sym,
            "price": row.get("last_price", 0),
            "change_24h": row.get("price_change_percent", 0),
            "volume": row.get("quote_volume", 0),
            "mcap": row.get("market_cap_value") or 0,
            "oi_chg_24h": row.get("oi_change_24h_pct") or 0,
            "signal": row.get("signal_label", ""),
            "scores": {
                "turnover": s1, "momentum": s2, "mcap_structure": s3,
                "liquidity": s4, "social_heat": s5, "risk_concentration": s6,
            },
            "details": {
                "turnover": d1, "momentum": d2, "mcap_structure": d3,
                "liquidity": d4, "social_heat": d5, "risk": d6,
            },
            "total": total,
            "insights": insights,
            "risk_flags": d6.get("risk_flags", []),
        }

    def print_report(self, top_n=20):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*160}")
        print("🔥 妖币检测器 v3.0 - 六维终极扫描报告")
        print(f"{'='*160}")
        print(f"⏰ {now} | 📊 Binance USDT永续 | 🧬 六维评分模型")
        print(f"{'='*160}")

        # TOP N
        print(f"\n🏆 TOP {top_n} 潜在妖币 (六维综合评分)")
        print("-" * 160)
        hdr = f"{'#':<3} {'合约':<14} {'总分':>5} {'换手':>5} {'动能':>5} {'市值':>5} {'流动':>5} {'社交':>5} {'风险':>5} {'价格':>10} {'24h%':>7} {'OI%':>7} {'信号':>6} {'洞察'}"
        print(hdr)
        print("-" * 160)

        for i, r in enumerate(self.results[:top_n], 1):
            s = r["scores"]
            if r["total"] >= 75: rt = "🔥"
            elif r["total"] >= 60: rt = "✅"
            elif r["total"] >= 45: rt = "🟡"
            else: rt = "⚪"

            ins_str = " | ".join(r["insights"][:3])
            print(f"{i:<3} {r['symbol']:<14} {r['total']:>5.1f} {s['turnover']:>5} {s['momentum']:>5} {s['mcap_structure']:>5} {s['liquidity']:>5} {s['social_heat']:>5} {s['risk_concentration']:>5} {r['price']:>10.4f} {r['change_24h']:>+6.2f}% {r['oi_chg_24h']:>+6.2f}% {r['signal']:>6} {ins_str}")

        # TOP 5 详细
        print(f"\n{'='*160}")
        print("📋 TOP 5 六维详细分析:")
        print(f"{'='*160}")

        for i, r in enumerate(self.results[:5], 1):
            d = r["details"]
            print(f"\n{'─'*120}")
            print(f" #{i} {r['symbol']} | 综合: {r['total']:.1f}/100 | 价格: {r['price']:.4f} | 24h: {r['change_24h']:+.2f}%")
            print(f"{'─'*120}")

            # 换手率
            t = d["turnover"]
            print(f"  📊 换手率 ({r['scores']['turnover']}/100):")
            print(f"     成交笔数: {t['trade_count']:,} | 平均单笔: ${t['avg_trade_usd']} | 成交/OI: {t['vol_oi_ratio']}")

            # 动能
            m = d["momentum"]
            print(f"  🚀 动能 ({r['scores']['momentum']}/100):")
            print(f"     4h涨速: {m['price_vel_4h']:+.2f}% | 1h涨速: {m['price_vel_1h']:+.2f}% | 距高点: {m['dist_from_high']:.2f}%")

            # 市值结构
            mc = d["mcap_structure"]
            print(f"  💎 市值结构 ({r['scores']['mcap_structure']}/100):")
            print(f"     市值: ${mc['mcap_millions']}M | 市值/成交: {mc['mcap_vol_ratio']} | 市值/OI: {mc['mcap_oi_ratio']}")

            # 流动性
            liq = d["liquidity"]
            print(f"  💧 流动性 ({r['scores']['liquidity']}/100):")
            print(f"     价差: {liq['spread_bps']}bps | 买盘: ${liq['bid_depth_usd']:,.0f} | 卖盘: ${liq['ask_depth_usd']:,.0f} | 不平衡: {liq['imbalance']:+.3f}")

            # 社交热度
            sh = d["social_heat"]
            print(f"  🗣️ 社交热度 ({r['scores']['social_heat']}/100):")
            print(f"     热度排名: #{sh['heat_rank']} | 提及量: {sh['mention_count']} | 叙事切换: {'✅' if sh['narrative_shift'] else '❌'} | 首页: {'✅' if sh['homepage'] else '❌'}")

            # 风险集中度
            rc = d["risk"]
            print(f"  🛡️ 风险集中度 ({r['scores']['risk_concentration']}/100):")
            print(f"     大户多头: {rc['top_long_pct']}% | 散户多头: {rc['retail_long_pct']}% | 分歧: {rc['divergence']}% | Taker: {rc['taker_ratio']}")

            if r["insights"]:
                print(f"\n  💡 洞察: {' | '.join(r['insights'])}")
            if r["risk_flags"]:
                print(f"  ⚠️ 风险: {', '.join(r['risk_flags'])}")

        # DNA
        print(f"\n{'='*160}")
        print("🧬 妖币 DNA (六维特征):")
        print(f"{'='*160}")
        print("""
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ① 换手率 (15%) - 是不是开始活跃?                                       │
  │    ✅ 成交笔数>10万  ✅ 成交/OI>3  ✅ 平均单笔$10-200                  │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ② 动能 (20%) - 是不是刚启动?                                           │
  │    ✅ 24h涨5-15%  ✅ 距高点2-8%  ✅ OI配合上涨  ✅ 1h加速              │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ③ 市值结构 (15%) - 还有多少空间?                                       │
  │    ✅ 市值<$100M  ✅ 市值/成交<5  ✅ 市值/OI<10                        │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ④ 流动性 (15%) - 能不能进出?                                           │
  │    ✅ 价差<3bps  ✅ 深度>$50万  ✅ 买盘>卖盘  ✅ 成交密度>100/min      │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ⑤ 社交热度 (15%) - 有没有开始被讨论?                                   │
  │    ✅ 热度排名前10  ✅ 提及量>50  ✅ 叙事切换中  ✅ 首页曝光            │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ ⑥ 风险集中度 (20%) - 是不是过度控盘?                                   │
  │    ✅ 大户散户分歧<15%  ✅ 多空比1.5-2.5  ✅ 费率正常  ✅ Taker均衡    │
  └──────────────────────────────────────────────────────────────────────────┘

  ⚠️ 危险信号: 散户多头>75% | 费率>0.05% | OI 1h暴增>10% | 涨幅>30% | 价差>10bps
""")
        print(f"{'='*160}")
        print("⚠️ 合约交易高风险，以上分析仅供参考，不构成投资建议")
        print(f"{'='*160}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="🔥 妖币检测器 v3.0")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--show", type=int, default=20)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    det = DemonCoinDetectorV3(verbose=args.verbose)
    results = det.scan(top=args.top)

    if args.json:
        print(json.dumps(results[:args.show], indent=2, ensure_ascii=False))
    else:
        det.print_report(top_n=args.show)

    return results


if __name__ == "__main__":
    main()
