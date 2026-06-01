#!/usr/bin/env python3
"""
🔥 妖币检测器 v1.0 - Demon Coin Detector
==========================================
基于 RIVER/RAVE/BEAT/MAVIA 等妖币案例提取的共同特征模式，
实时扫描 Binance USDT 永续合约市场，发现拉盘初期机会。

数据源:
- perp.shouyetech.com (永续合约主榜)
- Binance Futures API (OI/费率/多空比)

妖币 DNA 特征:
1. 价格动量: 24h涨幅 > 5%
2. OI暴增: 24h OI变化 > 15%
3. 成交量/OI比 > 3.0
4. 资金费率: 0.005% - 0.03% (温和看多)
5. 多空比: 1.5 - 2.5 (多头占优但不极端)
6. 市值 < $100M (容易被拉)
7. 信号: "多开" (新多头入场)
"""

import json
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


# ============================================================
# 配置
# ============================================================

class Config:
    """检测器配置"""
    # 数据源
    PERP_BOARD_API = "https://perp.shouyetech.com/api/board?top={top}"
    PERP_SMALLCAP_API = "https://perp.shouyetech.com/api/board/small-cap?top={top}"
    BINANCE_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
    BINANCE_OI = "https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
    BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit={limit}"
    BINANCE_LS_RATIO = "https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=1d&limit={limit}"
    BINANCE_OI_HIST = "https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=1d&limit={limit}"

    # 评分权重
    WEIGHTS = {
        "price_momentum": 20,    # 价格动量
        "oi_surge": 25,          # OI暴增
        "volume_oi_ratio": 15,   # 成交量/OI比
        "funding_rate": 15,      # 资金费率
        "long_short_ratio": 10,  # 多空比
        "market_cap": 10,        # 市值
        "signal": 5,             # 信号标签
    }

    # 妖币特征阈值
    THRESHOLDS = {
        # 价格动量
        "price_change_strong": 15,      # 强势涨幅
        "price_change_moderate": 5,     # 温和涨幅

        # OI变化
        "oi_change_24h_strong": 30,     # 强势OI增长
        "oi_change_24h_moderate": 15,   # 温和OI增长
        "oi_change_1h_alert": 5,        # 1h OI暴增警报

        # 成交量/OI比
        "vol_oi_hot": 5.0,              # 高度活跃
        "vol_oi_active": 3.0,           # 活跃
        "vol_oi_normal": 1.0,           # 正常

        # 资金费率
        "fr_optimal_low": 0.005,        # 最优费率下限
        "fr_optimal_high": 0.03,        # 最优费率上限
        "fr_danger_high": 0.05,         # 过热警报
        "fr_danger_low": -0.03,         # 极度看空

        # 多空比
        "ls_optimal_low": 1.5,          # 最优多空比下限
        "ls_optimal_high": 2.5,         # 最优多空比上限
        "ls_danger": 3.0,               # 极度拥挤

        # 市值
        "mcap_small": 50e6,             # 小市值
        "mcap_medium": 200e6,           # 中市值
    }


# ============================================================
# 数据获取
# ============================================================

def fetch_json(url: str, timeout: int = 10) -> Optional[dict]:
    """获取JSON数据"""
    try:
        req = Request(url, headers={"User-Agent": "DemonCoinDetector/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, json.JSONDecodeError, Exception) as e:
        return None


def fetch_perp_board(top: int = 50) -> list:
    """获取永续合约主榜数据"""
    data = fetch_json(Config.PERP_BOARD_API.format(top=top))
    if data and data.get("ok"):
        return data.get("gainers_rows", [])
    return []


def fetch_binance_ticker(symbol: str) -> Optional[dict]:
    """获取Binance 24h行情"""
    return fetch_json(Config.BINANCE_TICKER.format(symbol=symbol))


def fetch_binance_oi(symbol: str) -> Optional[dict]:
    """获取Binance当前OI"""
    return fetch_json(Config.BINANCE_OI.format(symbol=symbol))


def fetch_binance_funding(symbol: str, limit: int = 3) -> list:
    """获取Binance资金费率"""
    data = fetch_json(Config.BINANCE_FUNDING.format(symbol=symbol, limit=limit))
    return data if data else []


def fetch_binance_ls_ratio(symbol: str) -> Optional[dict]:
    """获取Binance大户多空比"""
    data = fetch_json(Config.BINANCE_LS_RATIO.format(symbol=symbol, limit=1))
    if data and len(data) > 0:
        return data[0]
    return None


def fetch_binance_oi_hist(symbol: str, limit: int = 7) -> list:
    """获取Binance OI历史"""
    data = fetch_json(Config.BINANCE_OI_HIST.format(symbol=symbol, limit=limit))
    return data if data else []


# ============================================================
# 评分模型
# ============================================================

def score_price_momentum(change_24h: float) -> float:
    """价格动量评分 (0-100)"""
    T = Config.THRESHOLDS
    if change_24h >= T["price_change_strong"]:
        return 100
    elif change_24h >= T["price_change_moderate"]:
        return 70 + (change_24h - T["price_change_moderate"]) / (T["price_change_strong"] - T["price_change_moderate"]) * 30
    elif change_24h >= 0:
        return 40 + change_24h / T["price_change_moderate"] * 30
    elif change_24h >= -5:
        return 20 + (change_24h + 5) / 5 * 20
    else:
        return max(0, 20 + change_24h)


def score_oi_surge(oi_change_24h: float, oi_change_1h: float) -> float:
    """OI暴增评分 (0-100)"""
    T = Config.THRESHOLDS
    score = 0

    # 24h OI变化
    if oi_change_24h >= T["oi_change_24h_strong"]:
        score += 70
    elif oi_change_24h >= T["oi_change_24h_moderate"]:
        score += 50 + (oi_change_24h - T["oi_change_24h_moderate"]) / (T["oi_change_24h_strong"] - T["oi_change_24h_moderate"]) * 20
    elif oi_change_24h >= 0:
        score += 30 + oi_change_24h / T["oi_change_24h_moderate"] * 20
    else:
        score += max(0, 30 + oi_change_24h)

    # 1h OI变化 (短期信号)
    if oi_change_1h >= T["oi_change_1h_alert"]:
        score += 30
    elif oi_change_1h >= 1:
        score += 15 + (oi_change_1h - 1) / (T["oi_change_1h_alert"] - 1) * 15
    elif oi_change_1h >= 0:
        score += oi_change_1h / 1 * 15

    return min(100, score)


def score_volume_oi_ratio(vol_oi: float) -> float:
    """成交量/OI比评分 (0-100)"""
    T = Config.THRESHOLDS
    if vol_oi >= T["vol_oi_hot"]:
        return 100
    elif vol_oi >= T["vol_oi_active"]:
        return 70 + (vol_oi - T["vol_oi_active"]) / (T["vol_oi_hot"] - T["vol_oi_active"]) * 30
    elif vol_oi >= T["vol_oi_normal"]:
        return 40 + (vol_oi - T["vol_oi_normal"]) / (T["vol_oi_active"] - T["vol_oi_normal"]) * 30
    else:
        return vol_oi / T["vol_oi_normal"] * 40


def score_funding_rate(avg_fr: float) -> float:
    """资金费率评分 (0-100) - 最优费率区间得分最高"""
    T = Config.THRESHOLDS
    fr_pct = avg_fr * 100  # 转换为百分比

    if T["fr_optimal_low"] <= fr_pct <= T["fr_optimal_high"]:
        return 100  # 最优区间
    elif 0 <= fr_pct < T["fr_optimal_low"]:
        return 80 + fr_pct / T["fr_optimal_low"] * 20
    elif T["fr_optimal_high"] < fr_pct <= T["fr_danger_high"]:
        return 80 - (fr_pct - T["fr_optimal_high"]) / (T["fr_danger_high"] - T["fr_optimal_high"]) * 30
    elif fr_pct > T["fr_danger_high"]:
        return max(20, 50 - fr_pct * 100)  # 过热扣分
    elif T["fr_danger_low"] <= fr_pct < 0:
        return 60 + fr_pct / T["fr_danger_low"] * 20
    else:
        return max(10, 40 + fr_pct * 10)  # 极度看空


def score_long_short_ratio(ls_ratio: float) -> float:
    """多空比评分 (0-100) - 1.5-2.5最优"""
    T = Config.THRESHOLDS
    if T["ls_optimal_low"] <= ls_ratio <= T["ls_optimal_high"]:
        return 100
    elif 1.0 <= ls_ratio < T["ls_optimal_low"]:
        return 60 + (ls_ratio - 1.0) / (T["ls_optimal_low"] - 1.0) * 40
    elif T["ls_optimal_high"] < ls_ratio <= T["ls_danger"]:
        return 80 - (ls_ratio - T["ls_optimal_high"]) / (T["ls_danger"] - T["ls_optimal_high"]) * 30
    elif ls_ratio > T["ls_danger"]:
        return max(20, 50 - (ls_ratio - T["ls_danger"]) * 10)
    else:
        return ls_ratio / 1.0 * 60


def score_market_cap(mcap: float) -> float:
    """市值评分 (0-100) - 小市值更容易被拉"""
    T = Config.THRESHOLDS
    if mcap <= 0:
        return 50  # 未知市值
    elif mcap <= T["mcap_small"]:
        return 100  # 小市值，容易拉
    elif mcap <= T["mcap_medium"]:
        return 70 + (T["mcap_medium"] - mcap) / (T["mcap_medium"] - T["mcap_small"]) * 30
    else:
        return max(30, 70 - mcap / 1e9 * 100)


def score_signal(signal: str) -> float:
    """信号标签评分 (0-100)"""
    if signal == "多开":
        return 100
    elif signal == "空平":
        return 70
    elif signal == "多平":
        return 40
    elif signal == "空开":
        return 20
    else:
        return 50


# ============================================================
# 妖币检测器
# ============================================================

class DemonCoinDetector:
    """妖币检测器"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results = []

    def scan(self, top: int = 50) -> list:
        """扫描市场，返回评分结果"""
        print(f"\n🔍 扫描 Binance USDT 永续合约市场 (Top {top})...")
        board = fetch_perp_board(top)
        if not board:
            print("❌ 无法获取市场数据")
            return []

        print(f"📊 获取到 {len(board)} 个合约")

        self.results = []
        for i, row in enumerate(board):
            symbol = row.get("symbol", "")
            if self.verbose:
                print(f"  [{i+1}/{len(board)}] 分析 {symbol}...")

            result = self._analyze_coin(row)
            if result:
                self.results.append(result)

            # 限速: 避免API限制
            if i % 10 == 9:
                time.sleep(0.5)

        # 按总分排序
        self.results.sort(key=lambda x: x["total_score"], reverse=True)
        return self.results

    def _analyze_coin(self, board_row: dict) -> Optional[dict]:
        """分析单个币种"""
        symbol = board_row.get("symbol", "")
        change_24h = board_row.get("price_change_percent", 0)
        volume = board_row.get("quote_volume", 0)
        oi_value = board_row.get("oi_value") or 0
        oi_change_24h = board_row.get("oi_change_24h_pct") or 0
        oi_change_1h = board_row.get("oi_change_1h_pct") or 0
        signal = board_row.get("signal_label", "")
        mcap = board_row.get("market_cap_value") or 0

        # 计算成交量/OI比
        vol_oi_ratio = volume / oi_value if oi_value > 0 else 0

        # 获取资金费率
        fr_data = fetch_binance_funding(symbol, limit=3)
        rates = [float(f["fundingRate"]) for f in fr_data] if fr_data else []
        avg_fr = sum(rates) / len(rates) if rates else 0

        # 获取多空比
        ls_data = fetch_binance_ls_ratio(symbol)
        ls_ratio = float(ls_data["longShortRatio"]) if ls_data else 0

        # 各维度评分
        scores = {
            "price_momentum": score_price_momentum(change_24h),
            "oi_surge": score_oi_surge(oi_change_24h, oi_change_1h),
            "volume_oi_ratio": score_volume_oi_ratio(vol_oi_ratio),
            "funding_rate": score_funding_rate(avg_fr),
            "long_short_ratio": score_long_short_ratio(ls_ratio),
            "market_cap": score_market_cap(mcap),
            "signal": score_signal(signal),
        }

        # 加权总分
        total = sum(
            scores[k] * Config.WEIGHTS[k] / 100
            for k in scores
        )

        # 风险评估
        risk_flags = []
        if avg_fr * 100 > Config.THRESHOLDS["fr_danger_high"]:
            risk_flags.append("费率过热")
        if ls_ratio > Config.THRESHOLDS["ls_danger"]:
            risk_flags.append("多空比极端")
        if oi_change_1h > 10:
            risk_flags.append("1h OI暴增")
        if change_24h > 30:
            risk_flags.append("涨幅过大")

        # 洞察
        insights = []
        if change_24h > 5 and oi_change_24h > 15:
            insights.append("📈 价格+OI同步上涨，新资金涌入")
        if vol_oi_ratio > 5:
            insights.append("🔥 成交活跃度极高")
        if 0.005 <= avg_fr * 100 <= 0.03:
            insights.append("💰 费率温和看多，不过热")
        if 1.5 <= ls_ratio <= 2.5:
            insights.append("👥 多头占优但不拥挤")
        if mcap and mcap < 50e6:
            insights.append("🎯 小市值，容易被拉")

        return {
            "symbol": symbol,
            "price": board_row.get("last_price", 0),
            "change_24h": change_24h,
            "volume": volume,
            "oi_value": oi_value,
            "oi_change_24h": oi_change_24h,
            "oi_change_1h": oi_change_1h,
            "vol_oi_ratio": vol_oi_ratio,
            "avg_fr": avg_fr,
            "ls_ratio": ls_ratio,
            "mcap": mcap,
            "signal": signal,
            "scores": scores,
            "total_score": total,
            "risk_flags": risk_flags,
            "insights": insights,
        }

    def print_report(self, top_n: int = 20):
        """打印检测报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "=" * 140)
        print("🔥 妖币检测器 - Demon Coin Detector v1.0")
        print("=" * 140)
        print(f"⏰ 扫描时间: {now}")
        print(f"📊 扫描范围: Binance USDT 永续合约")
        print(f"🧬 检测模型: 基于 RIVER/RAVE/BEAT/MAVIA 等妖币案例提取")
        print("=" * 140)

        # 评分权重说明
        print("\n📐 评分权重:")
        for k, v in Config.WEIGHTS.items():
            print(f"  • {k}: {v}%")

        # TOP N 结果
        print(f"\n🏆 TOP {top_n} 潜在妖币:")
        print("-" * 140)
        print(f"{'排名':<4} {'合约':<14} {'总分':>6} {'价格':>10} {'24h涨跌':>8} {'OI变化':>8} {'成交/OI':>8} {'费率':>8} {'多空比':>8} {'信号':>6} {'风险':>12} {'建议':>10}")
        print("-" * 140)

        for i, r in enumerate(self.results[:top_n], 1):
            # 评级
            if r["total_score"] >= 80:
                rating = "🔥 强烈关注"
            elif r["total_score"] >= 65:
                rating = "✅ 推荐"
            elif r["total_score"] >= 50:
                rating = "🟡 观察"
            else:
                rating = "⚪ 暂缓"

            # 格式化
            vol_str = f"{r['volume']/1e6:.1f}M"
            risk_str = ",".join(r["risk_flags"]) if r["risk_flags"] else "✅正常"

            print(f"{i:<4} {r['symbol']:<14} {r['total_score']:>6.1f} {r['price']:>10.4f} {r['change_24h']:>+7.2f}% {r['oi_change_24h']:>+7.2f}% {r['vol_oi_ratio']:>8.2f} {r['avg_fr']*100:>+7.4f}% {r['ls_ratio']:>8.2f} {r['signal']:>6} {risk_str:>12} {rating:>10}")

        # 详细分析 TOP 5
        print("\n" + "=" * 140)
        print("📋 TOP 5 详细分析:")
        print("=" * 140)

        for i, r in enumerate(self.results[:5], 1):
            print(f"\n{'='*80}")
            print(f" #{i} {r['symbol']} - 综合评分: {r['total_score']:.1f}/100")
            print(f"{'='*80}")
            print(f"  📈 价格动量: {r['scores']['price_momentum']:.0f}/100 (24h涨幅: {r['change_24h']:+.2f}%)")
            print(f"  📊 OI暴增: {r['scores']['oi_surge']:.0f}/100 (24h: {r['oi_change_24h']:+.2f}%, 1h: {r['oi_change_1h']:+.2f}%)")
            print(f"  💰 成交/OI比: {r['scores']['volume_oi_ratio']:.0f}/100 ({r['vol_oi_ratio']:.2f})")
            print(f"  💵 资金费率: {r['scores']['funding_rate']:.0f}/100 ({r['avg_fr']*100:+.4f}%)")
            print(f"  👥 多空比: {r['scores']['long_short_ratio']:.0f}/100 ({r['ls_ratio']:.2f})")
            print(f"  🏷️ 市值: {r['scores']['market_cap']:.0f}/100 ({r['mcap']/1e6:.1f}M)")
            print(f"  🚦 信号: {r['signal']} ({r['scores']['signal']:.0f}/100)")

            if r["insights"]:
                print(f"  💡 洞察:")
                for insight in r["insights"]:
                    print(f"     {insight}")

            if r["risk_flags"]:
                print(f"  ⚠️ 风险: {', '.join(r['risk_flags'])}")

        # 妖币 DNA 总结
        print("\n" + "=" * 140)
        print("🧬 妖币 DNA 特征总结:")
        print("=" * 140)
        print("""
  ✅ 拉盘初期信号 (入场机会):
     • 24h涨幅 5-15% (刚开始动)
     • OI 24h变化 > 15% (新资金涌入)
     • 成交量/OI比 > 3.0 (交易活跃)
     • 资金费率 0.005%-0.03% (温和看多)
     • 多空比 1.5-2.5 (多头占优)
     • 市值 < $100M (容易被拉)
     • 信号: "多开" (新多头入场)

  ⚠️ 拉盘末期信号 (谨慎/回避):
     • 资金费率 > 0.05% (过热)
     • 多空比 > 3.0 (极度拥挤)
     • OI 1h暴增 > 10% (最后一冲)
     • 24h涨幅 > 30% (可能见顶)
""")

        print("=" * 140)
        print("⚠️ 风险提示: 合约交易具有高风险，以上分析仅供参考，不构成投资建议")
        print("=" * 140)

    def get_alerts(self, min_score: float = 70) -> list:
        """获取高分警报"""
        return [r for r in self.results if r["total_score"] >= min_score]


# ============================================================
# 主程序
# ============================================================

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description="🔥 妖币检测器 - Demon Coin Detector")
    parser.add_argument("--top", type=int, default=50, help="扫描前N个合约 (默认50)")
    parser.add_argument("--show", type=int, default=20, help="显示前N个结果 (默认20)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    args = parser.parse_args()

    detector = DemonCoinDetector(verbose=args.verbose)
    results = detector.scan(top=args.top)

    if args.json:
        # JSON输出
        print(json.dumps(results[:args.show], indent=2, ensure_ascii=False))
    else:
        # 格式化报告
        detector.print_report(top_n=args.show)

    return results


if __name__ == "__main__":
    main()
