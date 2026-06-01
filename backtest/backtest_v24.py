#!/usr/bin/env python3
"""
v2.3 vs v2.4(吸收优化扣分) 回测对比
v2.4 = v2.3 + 强制扣分规则(过热/追高/OI背离)
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

def calc_indicators(klines):
    c = [float(k[4]) for k in klines]
    v = [float(k[5]) for k in klines]
    h = [float(k[2]) for k in klines]
    st = calc_supertrend(klines)
    oi = calc_oi_proxy(c, v)
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
        ind.append({"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,"vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"high":h[i],"close":c[i]})
    return ind, c, v, st

def score_v23(d, st_dir):
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

def score_v24(d, closes, volumes, i, st_dir):
    """v2.4 = v2.3基础分 + 优化策略的强制扣分"""
    # 先算v2.3基础分
    s = score_v23(d, st_dir)
    
    # === 吸收的强制扣分 ===
    # 1. 距7天低点已涨 > 300%: -15
    if i >= 168:
        low7 = min(closes[max(0,i-168):i])
        if low7 > 0 and (closes[i]-low7)/low7 > 3.0: s -= 15
    
    # 2. 距30天低点已涨 > 600%: -30
    if i >= 720:
        low30 = min(closes[max(0,i-720):i])
        if low30 > 0 and (closes[i]-low30)/low30 > 6.0: s -= 30
    
    # 3. 峰值后跌破EMA20: -20
    if i >= 25:
        peak = max(closes[max(0,i-24):i])
        ema20 = sum(closes[i-20:i])/20
        if peak > ema20*1.1 and closes[i] < ema20: s -= 20
    
    # 4. OI暴涨价格不涨: -20
    if d["oi_chg_1h"] > 5 and d["chg_1h"] < 0: s -= 20
    
    # 5. 放量收长上影: -15
    if i >= 2 and d["vol_ratio"] > 2:
        if d["high"] > closes[i]*1.05: s -= 15
    
    # 6. 距24h高点回撤>20%不开仓 (硬过滤)
    if i >= 24:
        high24 = max(closes[max(0,i-24):i])
        if high24 > 0 and closes[i] < high24 * 0.80:
            s = -999  # 硬拒
    
    # 7. 24h涨幅>80%禁止追
    if i >= 24:
        chg24 = (closes[i]-closes[i-24])/max(closes[i-24],0.001)*100
        if chg24 > 80: s = -999
    
    return max(s, 0) if s != -999 else -999

def sim(symbol, klines, strategy, threshold):
    if len(klines) < 100: return {"symbol":symbol,"trades":[]}
    ind, closes, volumes, st = calc_indicators(klines)
    trades = []; pos = None; peak = 0
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d = ind[i]
        if strategy == "v23":
            score = score_v23(d, st[i])
        else:
            score = score_v24(d, closes, volumes, i, st[i])
        
        if pos is None:
            can_open = False
            if score >= threshold:
                if strategy == "v23":
                    if st[i] >= 0: can_open = True
                else:
                    can_open = True  # v24的硬过滤已在score里处理
            if can_open:
                pos = {"entry_price":closes[i],"entry_bar":i,"entry_time":klines[i][0],"entry_score":score}
                peak = 0
        
        if pos:
            pnl = (closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak = max(peak, pnl)
            # 止损10%
            if pnl <= -0.10:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"stop_loss","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; continue
            # 追踪止盈: 浮盈10%启动, 峰值回撤15%
            if peak >= 0.10 and (peak-pnl) >= 0.15:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"trail","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None; continue
            # 超时72h
            if i-pos["entry_bar"] >= 72:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"exit_time":klines[i][0],"reason":"timeout","pnl":pnl*100,"hours":i-pos["entry_bar"]})
                pos = None
    return {"symbol":symbol,"trades":trades}

def stats(results):
    at = []
    for r in results: at.extend(r["trades"])
    if not at: return {"n":0,"wr":0,"avg":0,"tot":0,"mxw":0,"mxl":0,"sl":0,"trail":0,"to":0}
    wins = [t for t in at if t["pnl"]>0]
    return {
        "n":len(at),"wr":len(wins)/len(at)*100,
        "avg":sum(t["pnl"] for t in at)/len(at),
        "tot":sum(t["pnl"] for t in at),
        "mxw":max(t["pnl"] for t in at),"mxl":min(t["pnl"] for t in at),
        "sl":sum(1 for t in at if "stop" in t["reason"]),
        "trail":sum(1 for t in at if "trail" in t["reason"]),
        "to":sum(1 for t in at if "timeout" in t["reason"]),
    }

def main():
    print("="*70)
    print("v2.3 vs v2.4(吸收扣分) - 60天真实数据回测")
    print("="*70)
    r23=[]; r24=[]
    for coin in COINS:
        print(f"  {coin}...",end=" ",flush=True)
        kl = fetch_klines(coin,"1h",1500)
        if not kl or len(kl)<100: print("SKIP"); continue
        print(f"OK({len(kl)//24}d)")
        r23.append(sim(coin,kl,"v23",55))
        r24.append(sim(coin,kl,"v24",55))
        time.sleep(0.1)
    
    s23=stats(r23); s24=stats(r24)
    
    print(f"\n{'='*70}")
    print("CORE STATS")
    print("="*70)
    print(f"{'Metric':<18} {'v2.3':<14} {'v2.4(hybrid)':<14} {'Diff':<10}")
    print("-"*56)
    for lbl,k,fmt in [("Trades","n","d"),("WinRate","wr",".1f"),("AvgPnL","avg",".1f"),
                       ("TotalPnL","tot",".1f"),("MaxWin","mxw",".1f"),("MaxLoss","mxl",".1f"),
                       ("StopLoss","sl","d"),("TrailStop","trail","d"),("Timeout","to","d")]:
        a,b=s23[k],s24[k]; d=b-a
        if fmt=="d": print(f"{lbl:<18} {a:<14} {b:<14} {d:+d}")
        else: print(f"{lbl:<18} {a:<14.1f} {b:<14.1f} {d:+.1f}")
    
    # per coin
    print(f"\n{'='*70}")
    print("PER-COIN (sorted by v2.4 advantage)")
    print("="*70)
    rows=[]
    for rv,rc in zip(r23,r24):
        sym=rv["symbol"].replace("USDT","")
        vp=sum(t["pnl"] for t in rv["trades"])
        vc=len(rv["trades"])
        cp=sum(t["pnl"] for t in rc["trades"])
        cc=len(rc["trades"])
        rows.append((sym,vc,vp,cc,cp,cp-vp))
    rows.sort(key=lambda x:x[5])
    print(f"{'Coin':<10} {'v23#':<5} {'v23PnL':<9} {'v24#':<5} {'v24PnL':<9} {'Diff':<8}")
    print("-"*50)
    for sym,vn,vp,cn,cp,d in rows:
        m="+" if d>20 else "-" if d<-20 else "="
        print(f"{sym:<10} {vn:<5} {vp:<9.1f} {cn:<5} {cp:<9.1f} {m} {d:+.1f}")
    
    wc=sum(1 for _,_,vp,_,cp,_ in rows if cp>vp+10)
    lc=sum(1 for _,_,vp,_,cp,_ in rows if vp>cp+10)
    print(f"\nWin: v2.4 wins {wc} coins, v2.3 wins {lc} coins, similar {len(rows)-wc-lc}")
    
    print(f"\n{'='*70}")
    print("VERDICT")
    print("="*70)
    pdiff = s24["tot"]-s23["tot"]
    print(f"  v2.3 Total PnL: {s23['tot']:.1f}%  ({s23['n']} trades)")
    print(f"  v2.4 Total PnL: {s24['tot']:.1f}%  ({s24['n']} trades)")
    print(f"  Difference: {pdiff:+.1f}%")
    print(f"  Stop Losses: v2.3={s23['sl']} vs v2.4={s24['sl']}")
    if pdiff > 50:
        print(f"  >>> v2.4 HYBRID IS BETTER by {pdiff:.1f}% <<<")
    elif pdiff < -50:
        print(f"  >>> v2.3 STILL BETTER by {-pdiff:.1f}% <<<")
    else:
        print(f"  >>> SIMILAR PERFORMANCE <<<")

if __name__ == "__main__":
    main()
