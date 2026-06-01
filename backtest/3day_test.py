#!/usr/bin/env python3
"""v3.0 最近3天回测 + 止盈优化测试"""
import json, time
from urllib.request import urlopen
from datetime import datetime, timedelta

BASE_URL = "https://fapi.binance.com"
COINS = [
    "RAVEUSDT","LABUSDT","STOUSDT","SKYAIUSDT","BSBUSDT","SIRENUSDT","PLAYUSDT","GUAUSDT","ESPORTSUSDT",
    "XRPUSDT","SOLUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","NEARUSDT","ARBUSDT",
    "WIFUSDT","ORDIUSDT","1000SHIBUSDT","1000PEPEUSDT","JUPUSDT","TIAUSDT","SUIUSDT",
]

def fetch_klines(symbol, interval="1h", limit=72):
    """获取最近3天数据"""
    try:
        with urlopen(f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=10) as r:
            return json.loads(r.read().decode())
    except: return []

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
    h=[float(k[2]) for k in klines]; l=[float(k[3]) for k in klines]; c=[float(k[4]) for k in klines]
    d=[0]*n; atr=[0.0]*n; ub=[0.0]*n; lb=[0.0]*n
    for i in range(1,n):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        atr[i] = tr if i < period else (atr[i-1]*(period-1)+tr)/period
    for i in range(period,n):
        hl2=(h[i]+l[i])/2; u=hl2+multiplier*atr[i]; lo=hl2-multiplier*atr[i]
        if i>period: lb[i]=lo if(lb[i-1]>lo or c[i-1]<lb[i-1]) else lb[i-1]; ub[i]=u if(ub[i-1]<u or c[i-1]>ub[i-1]) else ub[i-1]
        else: ub[i]=u; lb[i]=lo
        if i>period:
            if c[i]>ub[i-1]: d[i]=1
            elif c[i]<lb[i-1]: d[i]=-1
            else: d[i]=d[i-1]
    return d

def calc_rsi(closes, period=14):
    rsi = [50.0]*len(closes)
    for i in range(period, len(closes)):
        gains=[]; losses=[]
        for j in range(i-period+1, i+1):
            diff=closes[j]-closes[j-1]
            if diff>0: gains.append(diff)
            else: losses.append(abs(diff))
        ag=sum(gains)/period if gains else 0
        al=sum(losses)/period if losses else 0.001
        rsi[i]=100-(100/(1+ag/max(al,0.001)))
    return rsi

def calc_indicators(klines):
    c=[float(k[4]) for k in klines]; v=[float(k[5]) for k in klines]
    st=calc_supertrend(klines); oi=calc_oi_proxy(c,v); rsi_arr=calc_rsi(c)
    ind=[]
    for i in range(len(klines)):
        if i<5: ind.append(None); continue
        o1=oi[i] if i<len(oi) else 0; o4=sum(oi[max(0,i-4):i])
        streak=0
        for j in range(i,max(0,i-5),-1):
            if j<len(oi) and oi[j]>0: streak+=1
            else: break
        vs=v[max(0,i-24):i]; vm=sorted(vs)[len(vs)//2] if vs else 1; vr=v[i]/max(vm,1)
        vs5=v[max(0,i-48):i]; vm5=sorted(vs5)[len(vs5)//2] if vs5 else 1; vr5=v[i]/max(vm5,1)
        c1=(c[i]-c[i-1])/max(c[i-1],0.001)*100 if i>=1 else 0
        c4=(c[i]-c[i-4])/max(c[i-4],0.001)*100 if i>=4 else 0
        ind.append({"close":c[i],"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"rsi":rsi_arr[i]})
    return ind, c, v, st

def score_signal(d, st_dir):
    s=0
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

def sim(symbol, klines, tp_mode="current"):
    """模拟交易"""
    if len(klines)<20: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    stop_loss=0.05
    
    for i in range(10, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            score=score_signal(d, st[i])
            rsi=d["rsi"]
            if st[i]<0 or rsi<30 or d["chg_4h"]<0: continue
            if rsi>80: pass
            elif rsi>70: score-=10
            if score>=55:
                pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                peak=0; first_half_closed=False
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            if pnl<=-stop_loss:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"sl","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            
            # 止盈模式
            if tp_mode == "current":
                # 当前: 50%@+50% + 追踪10/15%
                if not first_half_closed and pnl>=0.50:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp1","peak":peak*100})
                    first_half_closed=True
                if first_half_closed and peak>=0.10 and (peak-pnl)>=0.15:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp2","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            elif tp_mode == "tight":
                # 紧止盈: 25%@+30% + 追踪8/12%
                if not first_half_closed and pnl>=0.30:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*25,"reason":"tp1","peak":peak*100})
                    first_half_closed=True
                if first_half_closed and peak>=0.08 and (peak-pnl)>=0.12:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*75,"reason":"tp2","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            elif tp_mode == "wide":
                # 宽止盈: 50%@+70% + 追踪15/20%
                if not first_half_closed and pnl>=0.70:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp1","peak":peak*100})
                    first_half_closed=True
                if first_half_closed and peak>=0.15 and (peak-pnl)>=0.20:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp2","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            elif tp_mode == "fixed":
                # 固定止盈: 50%@+50% + 50%@+100%
                if not first_half_closed and pnl>=0.50:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp1","peak":peak*100})
                    first_half_closed=True
                if first_half_closed and pnl>=1.00:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp2","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            # 超时 (3天=72小时)
            if i-pos["entry_bar"]>=72:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"to"})
                pos=None; cooldown_until=i+2
    return trades

def stats(trades):
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"sl":0,"mxl":0,"mxw":0}
    wins=[t for t in trades if t["pnl"]>0]
    sl=sum(1 for t in trades if t.get("reason")=="sl")
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),"sl":sl,
        "mxl":min(t["pnl"] for t in trades),
        "mxw":max(t["pnl"] for t in trades) if wins else 0}

# 加载最近3天数据
print("加载最近3天数据...")
all_klines = {}
for coin in COINS:
    kl = fetch_klines(coin, "1h", 72)
    if kl and len(kl) >= 20:
        all_klines[coin] = kl
    time.sleep(0.1)

print(f"加载 {len(all_klines)} 个币")
print()

# 测试不同止盈模式
tp_modes = [
    ("current", "当前 (50%@+50%+追踪10/15%)"),
    ("tight", "紧止盈 (25%@+30%+追踪8/12%)"),
    ("wide", "宽止盈 (50%@+70%+追踪15/20%)"),
    ("fixed", "固定 (50%@+50%+50%@+100%)"),
]

print(f"{'止盈模式':<30} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'最大盈':<8} {'最大亏':<8}")
print("-"*85)

for mode, name in tp_modes:
    all_trades = []
    for coin, kl in all_klines.items():
        all_trades.extend(sim(coin, kl, mode))
    s = stats(all_trades)
    print(f"{name:<30} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5} {s['mxw']:<8.1f} {s['mxl']:<8.1f}")

print()
print("说明: 最近3天数据，超时设为72小时")
