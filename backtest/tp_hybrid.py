#!/usr/bin/env python3
"""
分批止盈方案对比 - 30天真实数据
固定止盈锁一部分 + 追踪止盈跑剩余
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
    rsi_arr = calc_rsi(c)
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
        ind.append({"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,
            "close":c[i],"rsi":rsi_arr[i]})
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

def sim(symbol, klines, tp_config):
    """分批止盈模拟: {fixed_pct, fixed_at, trail_activate, trail_draw}"""
    if len(klines) < 100: return []
    ind, closes, volumes, st = calc_indicators(klines)
    trades = []; pos = None; peak = 0; first_half_closed = False
    cooldown_until = 0
    
    fixed_pct = tp_config.get("fixed_pct", 0.5)  # 第一批止盈比例
    fixed_at = tp_config.get("fixed_at", 0.30)    # 第一批止盈触发点
    trail_activate = tp_config.get("trail_activate", 0.10)
    trail_draw = tp_config.get("trail_draw", 0.15)
    stop_loss = 0.08
    
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
                    peak = 0; first_half_closed = False
        
        # 持仓管理
        if pos:
            pnl = (closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak = max(peak, pnl)
            
            # 止损 8%
            if pnl <= -stop_loss:
                remaining = 1.0 if not first_half_closed else (1.0 - fixed_pct)
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":"stop_loss","pnl":pnl*100*remaining,"hours":i-pos["entry_bar"],
                    "peak":peak*100,"partial":first_half_closed})
                pos = None; cooldown_until = i + 2; continue
            
            # 第一批固定止盈
            if not first_half_closed and pnl >= fixed_at:
                # 记录第一批收益
                first_pnl = pnl * fixed_pct * 100
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":f"fixed_{int(fixed_at*100)}%_first","pnl":first_pnl,
                    "hours":i-pos["entry_bar"],"peak":peak*100,"partial":True})
                first_half_closed = True
            
            # 第二批追踪止盈
            if first_half_closed:
                remaining = 1.0 - fixed_pct
                if peak >= trail_activate:
                    drawdown = peak - pnl
                    if drawdown >= trail_draw:
                        second_pnl = pnl * remaining * 100
                        trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                            "reason":f"trail_{int(trail_activate*100)}_{int(trail_draw*100)}_second",
                            "pnl":second_pnl,"hours":i-pos["entry_bar"],
                            "peak":peak*100,"partial":True})
                        pos = None; cooldown_until = i + 2; continue
            
            # 超时 7天
            if i-pos["entry_bar"] >= 168:
                remaining = 1.0 if not first_half_closed else (1.0 - fixed_pct)
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],
                    "reason":"timeout","pnl":pnl*100*remaining,"hours":i-pos["entry_bar"]})
                pos = None; cooldown_until = i + 2
    return trades

def stats(trades):
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"mxw":0,"mxl":0,"sl":0}
    wins = [t for t in trades if t["pnl"]>0]
    sl = sum(1 for t in trades if "stop_loss" in t["reason"])
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),
        "mxw":max(t["pnl"] for t in trades),"mxl":min(t["pnl"] for t in trades),"sl":sl}

# 分批止盈方案
TP_CONFIGS = {
    "fixed50_only":     {"name":"固定50%全仓", "fixed_pct":0, "fixed_at":0.50, "trail_activate":0.10, "trail_draw":0.15, "desc":"纯固定50%止盈"},
    "trail_10_15":      {"name":"追踪10/15%全仓", "fixed_pct":0, "fixed_at":0.50, "trail_activate":0.10, "trail_draw":0.15, "desc":"纯追踪10/15% (当前)"},
    # 50% at +30%, 剩余追踪
    "S50_30_trail10_15":{"name":"50%@+30%+追踪10/15", "fixed_pct":0.5, "fixed_at":0.30, "trail_activate":0.10, "trail_draw":0.15, "desc":"50%在+30%止盈, 剩余追踪10/15%"},
    "S50_30_trail10_20":{"name":"50%@+30%+追踪10/20", "fixed_pct":0.5, "fixed_at":0.30, "trail_activate":0.10, "trail_draw":0.20, "desc":"50%在+30%止盈, 剩余追踪10/20%"},
    "S50_30_trail15_15":{"name":"50%@+30%+追踪15/15", "fixed_pct":0.5, "fixed_at":0.30, "trail_activate":0.15, "trail_draw":0.15, "desc":"50%在+30%止盈, 剩余追踪15/15%"},
    # 50% at +50%, 剩余追踪
    "S50_50_trail10_15":{"name":"50%@+50%+追踪10/15", "fixed_pct":0.5, "fixed_at":0.50, "trail_activate":0.10, "trail_draw":0.15, "desc":"50%在+50%止盈, 剩余追踪10/15%"},
    "S50_50_trail10_20":{"name":"50%@+50%+追踪10/20", "fixed_pct":0.5, "fixed_at":0.50, "trail_activate":0.10, "trail_draw":0.20, "desc":"50%在+50%止盈, 剩余追踪10/20%"},
    # 30% at +30%, 剩余追踪
    "S30_30_trail10_15":{"name":"30%@+30%+追踪10/15", "fixed_pct":0.3, "fixed_at":0.30, "trail_activate":0.10, "trail_draw":0.15, "desc":"30%在+30%止盈, 剩余追踪10/15%"},
    "S30_30_trail10_20":{"name":"30%@+30%+追踪10/20", "fixed_pct":0.3, "fixed_at":0.30, "trail_activate":0.10, "trail_draw":0.20, "desc":"30%在+30%止盈, 剩余追踪10/20%"},
    # 50% at +30%, 剩余固定50%
    "S50_30_fix50":     {"name":"50%@+30%+固定50%", "fixed_pct":0.5, "fixed_at":0.30, "trail_activate":99, "trail_draw":99, "desc":"50%在+30%止盈, 剩余固定50%止盈"},
    # 30% at +20%, 剩余追踪
    "S30_20_trail10_15":{"name":"30%@+20%+追踪10/15", "fixed_pct":0.3, "fixed_at":0.20, "trail_activate":0.10, "trail_draw":0.15, "desc":"30%在+20%止盈, 剩余追踪10/15%"},
}

def main():
    print("="*90)
    print("分批止盈方案对比 - 30天真实数据")
    print("="*90)
    
    all_trades = {k: [] for k in TP_CONFIGS}
    coin_count = 0
    
    for coin in COINS:
        print(f"  {coin}...", end=" ", flush=True)
        kl = fetch_klines(coin, "1h", 750)
        if not kl or len(kl) < 100: print("SKIP"); continue
        print(f"OK({len(kl)//24}d)")
        coin_count += 1
        
        for cfg_name, cfg in TP_CONFIGS.items():
            trades = sim(coin, kl, cfg)
            all_trades[cfg_name].extend(trades)
        
        time.sleep(0.1)
    
    # 统计
    print(f"\n{'='*90}")
    print(f"STATS ({coin_count} coins, ~30 days)")
    print("="*90)
    
    all_stats = {k: stats(v) for k, v in all_trades.items()}
    
    header = f"{'Strategy':<28} {'Trades':<7} {'WinR%':<7} {'AvgPnL':<8} {'Total%':<9} {'MaxWin':<8} {'MaxLoss':<9} {'SL#':<5}"
    print(header)
    print("-"*85)
    
    for cfg_name, cfg in TP_CONFIGS.items():
        st = all_stats[cfg_name]
        print(f"{cfg['name']:<28} {st['n']:<7} {st['wr']:<7.1f} {st['avg']:<8.1f} {st['tot']:<9.1f} {st['mxw']:<8.1f} {st['mxl']:<9.1f} {st['sl']:<5}")
    
    # 找基准: 固定50%全仓
    base = all_stats["fixed50_only"]
    current = all_stats["trail_10_15"]
    
    print(f"\n{'='*90}")
    print(f"vs 基准对比")
    print("="*90)
    print(f"{'Strategy':<28} {'PnL':<9} {'vs固定50%':<10} {'vs当前追踪':<12} {'WinR%':<7} {'SL#':<5} {'评价':<10}")
    print("-"*85)
    
    candidates = []
    for cfg_name, cfg in TP_CONFIGS.items():
        st = all_stats[cfg_name]
        vs_fixed = st["tot"] - base["tot"]
        vs_trail = st["tot"] - current["tot"]
        
        if st["tot"] > base["tot"]: verdict = "★★★ 最优"
        elif st["tot"] > current["tot"] + 50: verdict = "★★ 良好"
        elif st["tot"] > current["tot"]: verdict = "★ 可用"
        else: verdict = "❌ 差"
        
        candidates.append((cfg_name, cfg, st, vs_fixed, vs_trail, verdict))
        print(f"{cfg['name']:<28} {st['tot']:<9.1f} {vs_fixed:+<10.1f} {vs_trail:+<12.1f} {st['wr']:<7.1f} {st['sl']:<5} {verdict}")
    
    # 最终推荐
    print(f"\n{'='*90}")
    print("RECOMMENDATION")
    print("="*90)
    
    best = max(candidates, key=lambda x: x[2]["tot"])
    print(f"  最优: {best[1]['name']}")
    print(f"  总收益: {best[2]['tot']:.1f}%  胜率: {best[2]['wr']:.1f}%  止损: {best[2]['sl']}次")
    print(f"  vs 固定50%: {best[3]:+.1f}%  vs 当前追踪: {best[4]:+.1f}%")
    print(f"  说明: {best[1]['desc']}")

if __name__ == "__main__":
    main()
