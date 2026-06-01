#!/usr/bin/env python3
"""
止盈方案对比 - 30天真实数据
对比7种止盈策略在相同入场条件下的表现
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

def fetch_klines(symbol, interval="1h", limit=750):
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

def calc_indicators(klines):
    c = [float(k[4]) for k in klines]
    v = [float(k[5]) for k in klines]
    st = calc_supertrend(klines)
    oi = calc_oi_proxy(c, v)
    rsi = calc_rsi(c)
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
        ind.append({
            "oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,
            "chg_1h":c1,"chg_4h":c4,
            "close":c[i],"rsi":rsi[i],
        })
    return ind, c, v, st

def score_signal(d, st_dir):
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

def sim(symbol, klines, tp_name, tp_params):
    """模拟交易, 返回trades列表"""
    if len(klines) < 100: return []
    ind, closes, volumes, st = calc_indicators(klines)
    trades = []; pos = None; peak = 0
    stop_loss = 0.08  # 8%止损
    cooldown_until = 0  # 冷却时间(bar index)
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d = ind[i]
        
        # 开仓
        if pos is None and i >= cooldown_until:
            score = score_signal(d, st[i])
            rsi = d["rsi"]
            if st[i] >= 0 and score >= 55 and rsi < 75 and rsi > 30:
                if rsi > 70: score -= 10
                if score >= 55:
                    pos = {"entry_price":closes[i],"entry_bar":i,"entry_time":klines[i][0],"entry_score":score}
                    peak = 0
        
        # 持仓管理
        if pos:
            pnl = (closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak = max(peak, pnl)
            
            # 止损 8%
            if pnl <= -stop_loss:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":"stop_loss","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; cooldown_until = i + 2; continue
            
            # 止盈逻辑 (按方案不同)
            triggered = False
            
            if tp_name == "fixed_30":
                if pnl >= 0.30:
                    triggered = True
            elif tp_name == "fixed_50":
                if pnl >= 0.50:
                    triggered = True
            elif tp_name == "trail_10_15":
                if peak >= 0.10 and (peak-pnl) >= 0.15:
                    triggered = True
            elif tp_name == "trail_10_10":
                if peak >= 0.10 and (peak-pnl) >= 0.10:
                    triggered = True
            elif tp_name == "trail_10_20":
                if peak >= 0.10 and (peak-pnl) >= 0.20:
                    triggered = True
            elif tp_name == "trail_15_15":
                if peak >= 0.15 and (peak-pnl) >= 0.15:
                    triggered = True
            elif tp_name == "trail_8_12":
                if peak >= 0.08 and (peak-pnl) >= 0.12:
                    triggered = True
            elif tp_name == "trail_10_12":
                if peak >= 0.10 and (peak-pnl) >= 0.12:
                    triggered = True
            
            if triggered:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":f"{tp_name}","pnl":pnl*100,"hours":i-pos["entry_bar"],
                    "peak":peak*100})
                pos = None; cooldown_until = i + 2; continue
            
            # 超时 7天
            if i-pos["entry_bar"] >= 168:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":"timeout","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; cooldown_until = i + 2
    return trades

def stats(trades):
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"mxw":0,"mxl":0,"sl":0,"tp":0,"to":0,"avg_peak":0}
    wins = [t for t in trades if t["pnl"]>0]
    sl = sum(1 for t in trades if "stop_loss" in t["reason"])
    tp = sum(1 for t in trades if "trail" in t["reason"] or "fixed" in t["reason"])
    to = sum(1 for t in trades if "timeout" in t["reason"])
    peaks = [t.get("peak",0) for t in trades if "peak" in t]
    return {
        "n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),
        "mxw":max(t["pnl"] for t in trades),"mxl":min(t["pnl"] for t in trades),
        "sl":sl,"tp":tp,"to":to,
        "avg_peak":sum(peaks)/len(peaks) if peaks else 0,
    }

# 7种止盈方案
TP_STRATEGIES = {
    "fixed_30":     {"name":"固定30%", "desc":"浮盈30%止盈"},
    "fixed_50":     {"name":"固定50%", "desc":"浮盈50%止盈"},
    "trail_10_15":  {"name":"追踪10/15%", "desc":"浮盈10%启动, 峰值回撤15%止盈 (当前)"},
    "trail_10_10":  {"name":"追踪10/10%", "desc":"浮盈10%启动, 峰值回撤10%止盈 (更紧)"},
    "trail_10_20":  {"name":"追踪10/20%", "desc":"浮盈10%启动, 峰值回撤20%止盈 (更宽)"},
    "trail_15_15":  {"name":"追踪15/15%", "desc":"浮盈15%启动, 峰值回撤15%止盈 (延迟启动)"},
    "trail_8_12":   {"name":"追踪8/12%",  "desc":"浮盈8%启动, 峰值回撤12%止盈 (早启动紧止盈)"},
    "trail_10_12":  {"name":"追踪10/12%", "desc":"浮盈10%启动, 峰值回撤12%止盈 (稍紧)"},
}

def main():
    print("="*80)
    print("止盈方案对比 - 30天真实数据")
    print("="*80)
    
    all_trades = {k: [] for k in TP_STRATEGIES}
    coin_count = 0
    
    for coin in COINS:
        print(f"  {coin}...", end=" ", flush=True)
        kl = fetch_klines(coin, "1h", 750)  # ~31天
        if not kl or len(kl) < 100: print("SKIP"); continue
        print(f"OK({len(kl)//24}d)")
        coin_count += 1
        
        for tp_name in TP_STRATEGIES:
            trades = sim(coin, kl, tp_name, {})
            all_trades[tp_name].extend(trades)
        
        time.sleep(0.1)
    
    # 统计
    print(f"\n{'='*80}")
    print(f"STATS ({coin_count} coins, ~30 days)")
    print("="*80)
    
    all_stats = {k: stats(v) for k, v in all_trades.items()}
    
    header = f"{'Strategy':<18} {'Trades':<7} {'WinR%':<7} {'AvgPnL':<8} {'Total%':<9} {'MaxWin':<8} {'MaxLoss':<9} {'SL#':<5} {'TP#':<5} {'TO#':<5}"
    print(header)
    print("-"*90)
    
    for tp_name, tp_info in TP_STRATEGIES.items():
        st = all_stats[tp_name]
        print(f"{tp_info['name']:<18} {st['n']:<7} {st['wr']:<7.1f} {st['avg']:<8.1f} {st['tot']:<9.1f} {st['mxw']:<8.1f} {st['mxl']:<9.1f} {st['sl']:<5} {st['tp']:<5} {st['to']:<5}")
    
    # vs 当前策略对比
    base = all_stats["trail_10_15"]
    print(f"\n{'='*80}")
    print("vs 当前策略 (trail_10_15) 对比")
    print("="*80)
    print(f"{'Strategy':<18} {'PnL Diff':<10} {'WinR Diff':<10} {'SL Diff':<8} {'AvgPeak%':<10} {'评价':<10}")
    print("-"*70)
    
    candidates = []
    for tp_name, tp_info in TP_STRATEGIES.items():
        if tp_name == "trail_10_15": continue
        st = all_stats[tp_name]
        pnl_d = st["tot"] - base["tot"]
        wr_d = st["wr"] - base["wr"]
        sl_d = st["sl"] - base["sl"]
        
        if pnl_d > 50 and sl_d <= 5: verdict = "★★★ 优秀"
        elif pnl_d > 0 and sl_d <= 0: verdict = "★★ 良好"
        elif pnl_d > -100: verdict = "★ 可用"
        else: verdict = "❌ 差"
        
        candidates.append((tp_name, tp_info, st, pnl_d, wr_d, sl_d, verdict))
        print(f"{tp_info['name']:<18} {pnl_d:+<10.1f} {wr_d:+<10.1f} {sl_d:+<8} {st['avg_peak']:<10.1f} {verdict}")
    
    # 最终推荐
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print("="*80)
    
    # 找最优: PnL最高且SL不增加太多
    best = max(candidates, key=lambda x: x[3])  # 按PnL差值排序
    print(f"  当前策略: trail_10_15 → 总收益{base['tot']:.1f}% 胜率{base['wr']:.1f}% 止损{base['sl']}次")
    print(f"  最优策略: {best[1]['name']} → 总收益{best[2]['tot']:.1f}% 胜率{best[2]['wr']:.1f}% 止损{best[2]['sl']}次")
    print(f"  差异: PnL {best[3]:+.1f}% 胜率 {best[4]:+.1f}% 止损 {best[5]:+d}次")
    print(f"  说明: {best[1]['desc']}")

if __name__ == "__main__":
    main()
