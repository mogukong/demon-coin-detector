#!/usr/bin/env python3
"""
v2.3 止损优化对比 - 多策略同时回测
目标: 减少止损触发次数，同时保持或提升总收益
"""
import json, time, os
from datetime import datetime
from urllib.request import urlopen

BASE_URL = "https://fapi.binance.com"

COINS = [
    "RAVEUSDT","LABUSDT","STOUSDT","SKYAIUSDT","BSBUSDT","SIRENUSDT","PLAYUSDT","GUAUSDT","ESPORTSUSDT",
    "XRPUSDT","SOLUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","NEARUSDT","ARBUSDT",
    "WIFUSDT","ORDIUSDT","1000SHIBUSDT","1000PEPEUSDT","JUPUSDT","TIAUSDT","SUIUSDT",
]

def fetch_klines(symbol, interval="1h", limit=1500):
    url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except:
        return []

def calc_oi_proxy(closes, volumes):
    if len(closes) < 5: return []
    res = [0]
    for i in range(1, len(closes)):
        pchg = (closes[i] - closes[i-1]) / closes[i-1] * 100
        vs = volumes[max(0,i-24):i]
        vm = sorted(vs)[len(vs)//2] if vs else volumes[i]
        vr = volumes[i] / max(vm, 0.001)
        res.append(pchg * min(vr, 5))
    return res

def calc_supertrend(klines, period=10, multiplier=3.0):
    n = len(klines)
    if n < period + 1: return [0]*n
    h = [float(k[2]) for k in klines]
    l = [float(k[3]) for k in klines]
    c = [float(k[4]) for k in klines]
    d = [0]*n; atr = [0.0]*n; ub = [0.0]*n; lb = [0.0]*n
    for i in range(1,n):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        atr[i] = tr if i < period else (atr[i-1]*(period-1)+tr)/period
    for i in range(period,n):
        hl2 = (h[i]+l[i])/2; u = hl2+multiplier*atr[i]; lo = hl2-multiplier*atr[i]
        if i > period:
            lb[i] = lo if (lb[i-1]>lo or c[i-1]<lb[i-1]) else lb[i-1]
            ub[i] = u if (ub[i-1]<u or c[i-1]>ub[i-1]) else ub[i-1]
        else: ub[i]=u; lb[i]=lo
        if i > period:
            if c[i]>ub[i-1]: d[i]=1
            elif c[i]<lb[i-1]: d[i]=-1
            else: d[i]=d[i-1]
    return d

def calc_rsi(closes, period=14):
    rsi = [50.0] * len(closes)
    for i in range(period, len(closes)):
        gains = []; losses = []
        for j in range(i-period+1, i+1):
            diff = closes[j] - closes[j-1]
            if diff > 0: gains.append(diff)
            else: losses.append(abs(diff))
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.001
        rs = avg_gain / max(avg_loss, 0.001)
        rsi[i] = 100 - (100 / (1 + rs))
    return rsi

def calc_ema(data, period):
    ema = [0.0] * len(data)
    if len(data) < period: return ema
    ema[period-1] = sum(data[:period]) / period
    mult = 2 / (period + 1)
    for i in range(period, len(data)):
        ema[i] = data[i] * mult + ema[i-1] * (1 - mult)
    return ema

def calc_indicators(klines):
    c = [float(k[4]) for k in klines]
    v = [float(k[5]) for k in klines]
    h = [float(k[2]) for k in klines]
    lo = [float(k[3]) for k in klines]
    st = calc_supertrend(klines)
    oi = calc_oi_proxy(c, v)
    rsi = calc_rsi(c)
    ema20 = calc_ema(c, 20)
    ema50 = calc_ema(c, 50)
    ind = []
    for i in range(len(klines)):
        if i < 72: ind.append(None); continue
        o1 = oi[i] if i < len(oi) else 0
        o4 = sum(oi[max(0,i-4):i])
        streak = 0
        for j in range(i,max(0,i-5),-1):
            if j<len(oi) and oi[j]>0: streak+=1
            else: break
        vs = v[max(0,i-24):i]; vm = sorted(vs)[len(vs)//2] if vs else 1
        vr = v[i]/max(vm,1)
        vs5 = v[max(0,i-120):i]; vm5 = sorted(vs5)[len(vs5)//2] if vs5 else 1
        vr5 = v[i]/max(vm5,1)
        c1 = (c[i]-c[i-1])/max(c[i-1],0.001)*100 if i>=1 else 0
        c4 = (c[i]-c[i-4])/max(c[i-4],0.001)*100 if i>=4 else 0
        c24 = (c[i]-c[i-24])/max(c[i-24],0.001)*100 if i>=24 else 0
        # ATR% (波动率)
        atr_pct = 0
        if i >= 14:
            trs = []
            for j in range(i-13,i+1):
                tr = max(h[j]-lo[j], abs(h[j]-c[j-1]), abs(lo[j]-c[j-1]))
                trs.append(tr)
            atr_val = sum(trs)/len(trs)
            atr_pct = atr_val / max(c[i], 0.001) * 100
        ind.append({
            "oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,
            "chg_1h":c1,"chg_4h":c4,"chg_24h":c24,
            "high":h[i],"close":c[i],"low":lo[i],
            "rsi":rsi[i],"ema20":ema20[i],"ema50":ema50[i],"atr_pct":atr_pct,
        })
    return ind, c, v, st

def score_base(d, st_dir):
    s = 0
    if d["oi_chg_4h"]>8: s+=25
    elif d["oi_chg_4h"]>4: s+=15
    elif d["oi_chg_4h"]>0: s+=8
    if d["oi_chg_1h"]>0.4: s+=15
    elif d["oi_chg_1h"]>0: s+=8
    if d["oi_up_streak"]>=3: s+=10
    elif d["oi_up_streak"]>=2: s+=5
    if d["vol_ratio"]>2.0: s+=15
    elif d["vol_ratio"]>1.4: s+=10
    if d["vol_ratio_5"]>2: s+=10
    elif d["vol_ratio_5"]>1.5: s+=5
    if d["chg_4h"]>2: s+=15
    elif d["chg_4h"]>0: s+=8
    if d["chg_1h"]>0.2: s+=10
    elif d["chg_1h"]>0: s+=5
    if st_dir>0: s+=15
    elif st_dir<0: s-=10
    return s

def strategy_filter(name, d, closes, i, st_dir, score):
    """各策略的额外过滤条件, 返回 (allowed, adjusted_score)"""
    
    if name == "v2.3":
        # 原版: 只看SuperTrend
        return st_dir >= 0, score
    
    elif name == "A_tight_entry":
        # 策略A: 提高准入阈值到65 + SuperTrend上升才开
        if st_dir < 0: return False, score
        return score >= 65, score
    
    elif name == "B_rsi_filter":
        # 策略B: RSI过滤 - RSI>75过热不开, RSI<30超卖不开(等反弹)
        if st_dir < 0: return False, score
        rsi = d["rsi"]
        if rsi > 75: return False, score  # 过热
        if rsi < 30: return False, score  # 超卖可能继续跌
        if rsi > 70: score -= 10  # 偏热扣分
        return score >= 55, score
    
    elif name == "C_ema_trend":
        # 策略C: EMA趋势确认 - 价格必须在EMA20上方, 且EMA20>EMA50
        if st_dir < 0: return False, score
        if d["ema20"] <= 0 or d["ema50"] <= 0: return False, score
        if d["close"] < d["ema20"]: return False, score  # 必须在EMA20上方
        if d["ema20"] < d["ema50"]: return False, score  # EMA20>EMA50(多头排列)
        # 距离EMA20太远(>15%)不开, 追高风险
        dev = (d["close"] - d["ema20"]) / max(d["ema20"], 0.001) * 100
        if dev > 15: return False, score
        return score >= 55, score
    
    elif name == "D_vol_confirm":
        # 策略D: 成交量持续确认 - 连续2根放量才开
        if st_dir < 0: return False, score
        if d["vol_ratio"] < 1.5: return False, score  # 当前成交量必须>1.5x中位数
        # 连续放量加分
        if d["vol_ratio"] > 2.0 and d["vol_ratio_5"] > 1.5:
            score += 5  # 双重放量加分
        return score >= 55, score
    
    elif name == "E_combo":
        # 策略E: 组合优化 - RSI + EMA + 24h涨幅限制
        if st_dir < 0: return False, score
        rsi = d["rsi"]
        # RSI过滤
        if rsi > 78: return False, score
        # EMA确认
        if d["ema20"] > 0 and d["close"] < d["ema20"] * 0.98: return False, score
        # 24h已涨太多不开
        if d["chg_24h"] > 30: return False, score
        # 偏热扣分
        if rsi > 70: score -= 8
        if d["chg_24h"] > 15: score -= 5
        return score >= 55, score
    
    elif name == "F_anti_chase":
        # 策略F: 反追高 - 只在回踩时开仓
        if st_dir < 0: return False, score
        # 必须在EMA20附近(±5%), 不追远离均线的
        if d["ema20"] > 0:
            dev = abs(d["close"] - d["ema20"]) / max(d["ema20"], 0.001) * 100
            if dev > 8: return False, score  # 距EMA20>8%不开
        # 最近4h必须有回踩(4h内有阴线)
        # 用chg_1h < 0.5% 模拟"不是在暴涨中"
        if d["chg_1h"] > 3: return False, score  # 1h涨>3%不开, 等回踩
        return score >= 55, score

def sim(symbol, klines, strategy):
    if len(klines) < 100: return {"symbol":symbol,"trades":[]}
    ind, closes, volumes, st = calc_indicators(klines)
    trades = []; pos = None; peak = 0
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d = ind[i]
        score = score_base(d, st[i])
        allowed, adj_score = strategy_filter(strategy, d, closes, i, st[i], score)
        
        if pos is None:
            if allowed and adj_score >= 55:
                pos = {"entry_price":closes[i],"entry_bar":i,"entry_time":klines[i][0],"entry_score":adj_score}
                peak = 0
        if pos:
            pnl = (closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak = max(peak, pnl)
            if pnl <= -0.10:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"stop_loss","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; continue
            if peak >= 0.10 and (peak-pnl) >= 0.15:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"trail","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; continue
            if i-pos["entry_bar"] >= 72:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"timeout","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None
    return {"symbol":symbol,"trades":trades}

def stats(results):
    at = []
    for r in results: at.extend(r["trades"])
    if not at: return {"n":0,"wr":0,"avg":0,"tot":0,"mxw":0,"mxl":0,"sl":0,"trail":0,"to":0,"sl_rate":0}
    wins = [t for t in at if t["pnl"]>0]
    sl = sum(1 for t in at if "stop" in t["reason"])
    return {
        "n":len(at),"wr":len(wins)/len(at)*100,
        "avg":sum(t["pnl"] for t in at)/len(at),
        "tot":sum(t["pnl"] for t in at),
        "mxw":max(t["pnl"] for t in at),"mxl":min(t["pnl"] for t in at),
        "sl":sl,"sl_rate":sl/len(at)*100,
        "trail":sum(1 for t in at if "trail" in t["reason"]),
        "to":sum(1 for t in at if "timeout" in t["reason"]),
    }

STRATEGIES = ["v2.3","A_tight_entry","B_rsi_filter","C_ema_trend","D_vol_confirm","E_combo","F_anti_chase"]

def main():
    print("="*80)
    print("止损优化对比 - 7个策略同时回测")
    print("="*80)
    all_results = {s: [] for s in STRATEGIES}
    for coin in COINS:
        print(f"  {coin}...",end=" ",flush=True)
        kl = fetch_klines(coin,"1h",1500)
        if not kl or len(kl)<100: print("SKIP"); continue
        print(f"OK({len(kl)//24}d)")
        for s in STRATEGIES:
            all_results[s].append(sim(coin,kl,s))
        time.sleep(0.1)
    
    # 统计
    all_stats = {s: stats(all_results[s]) for s in STRATEGIES}
    
    print(f"\n{'='*80}")
    print("CORE STATS")
    print("="*80)
    header = f"{'Strategy':<16} {'Trades':<7} {'WinR%':<7} {'AvgPnL':<8} {'Total%':<9} {'MaxLoss':<9} {'SL#':<6} {'SL%':<7} {'Trail#':<7}"
    print(header)
    print("-"*80)
    for s in STRATEGIES:
        st = all_stats[s]
        print(f"{s:<16} {st['n']:<7} {st['wr']:<7.1f} {st['avg']:<8.1f} {st['tot']:<9.1f} {st['mxl']:<9.1f} {st['sl']:<6} {st['sl_rate']:<7.1f} {st['trail']:<7}")
    
    # vs v2.3 对比
    base = all_stats["v2.3"]
    print(f"\n{'='*80}")
    print("vs v2.3 COMPARISON")
    print("="*80)
    print(f"{'Strategy':<16} {'PnL Diff':<10} {'SL减少':<8} {'SL率变化':<10} {'胜率变化':<10} {'评价':<10}")
    print("-"*65)
    for s in STRATEGIES[1:]:
        st = all_stats[s]
        pnl_d = st["tot"] - base["tot"]
        sl_d = base["sl"] - st["sl"]
        slr_d = st["sl_rate"] - base["sl_rate"]
        wr_d = st["wr"] - base["wr"]
        
        # 评价
        if pnl_d > 50 and sl_d > 20:
            verdict = "★★★ 优秀"
        elif pnl_d > 0 and sl_d > 10:
            verdict = "★★ 良好"
        elif pnl_d > -100 and sl_d > 30:
            verdict = "★ 可用"
        elif pnl_d < -200:
            verdict = "❌ 差"
        else:
            verdict = "⚪ 一般"
        
        print(f"{s:<16} {pnl_d:+<10.1f} {sl_d:<8} {slr_d:+<10.1f} {wr_d:+<10.1f} {verdict}")
    
    # 逐币最优策略
    print(f"\n{'='*80}")
    print("PER-COIN BEST STRATEGY")
    print("="*80)
    coins_list = list(set(r["symbol"] for r in all_results["v2.3"]))
    coins_list.sort()
    print(f"{'Coin':<10} {'Best':<16} {'PnL':<9} {'SL#':<5} {'v2.3PnL':<9} {'v2.3SL':<7} {'Gain':<8}")
    print("-"*65)
    for coin in coins_list:
        best_s = None; best_pnl = -9999
        for s in STRATEGIES:
            for r in all_results[s]:
                if r["symbol"] == coin:
                    tp = sum(t["pnl"] for t in r["trades"])
                    if tp > best_pnl:
                        best_pnl = tp; best_s = s
        # v2.3 stats for this coin
        v23_pnl = sum(t["pnl"] for t in [r for r in all_results["v2.3"] if r["symbol"]==coin][0]["trades"])
        v23_sl = sum(1 for t in [r for r in all_results["v2.3"] if r["symbol"]==coin][0]["trades"] if "stop" in t["reason"])
        best_sl = sum(1 for t in [r for r in all_results[best_s] if r["symbol"]==coin][0]["trades"] if "stop" in t["reason"])
        sym = coin.replace("USDT","")
        gain = best_pnl - v23_pnl
        print(f"{sym:<10} {best_s:<16} {best_pnl:<9.1f} {best_sl:<5} {v23_pnl:<9.1f} {v23_sl:<7} {gain:+.1f}")
    
    # 推荐
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print("="*80)
    # 找最优策略: PnL损失<100, SL减少最多的
    candidates = []
    for s in STRATEGIES[1:]:
        st = all_stats[s]
        pnl_d = st["tot"] - base["tot"]
        sl_d = base["sl"] - st["sl"]
        if pnl_d > -150 and sl_d > 10:
            candidates.append((s, st, pnl_d, sl_d))
    candidates.sort(key=lambda x: (-x[3], -x[2]))  # 按SL减少排序
    
    for s, st, pnl_d, sl_d in candidates:
        print(f"  {s}: SL减少{sl_d}个 ({st['sl_rate']:.1f}% vs {base['sl_rate']:.1f}%), PnL差异{pnl_d:+.1f}%")
    
    if not candidates:
        print("  无满足条件的策略(PnL损失<150%且SL减少>10)")
    
    # 最终推荐
    print(f"\n  >>> 最终推荐 <<<")
    if candidates:
        best = candidates[0]
        print(f"  策略 {best[0]}: 止损从{base['sl']}次降到{best[1]['sl']}次")
        print(f"  累计收益: {base['tot']:.1f}% → {best[1]['tot']:.1f}% ({best[2]:+.1f}%)")
        print(f"  胜率: {base['wr']:.1f}% → {best[1]['wr']:.1f}% ({best[1]['wr']-base['wr']:+.1f}%)")

if __name__ == "__main__":
    main()
