#!/usr/bin/env python3
"""v4.1 吸收思想+保留原止盈 vs v3.0"""
import json, time
from urllib.request import urlopen

BASE_URL = "https://fapi.binance.com"
COINS = [
    "RAVEUSDT","LABUSDT","STOUSDT","SKYAIUSDT","BSBUSDT","SIRENUSDT","PLAYUSDT","GUAUSDT","ESPORTSUSDT",
    "XRPUSDT","SOLUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","NEARUSDT","ARBUSDT",
    "WIFUSDT","ORDIUSDT","1000SHIBUSDT","1000PEPEUSDT","JUPUSDT","TIAUSDT","SUIUSDT",
]

def fetch_klines(symbol, interval="1h", limit=750):
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

def calc_ema(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    m = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for p in closes[period:]: e = (p - e) * m + e
    return e

def calc_indicators(klines):
    c=[float(k[4]) for k in klines]; v=[float(k[5]) for k in klines]
    st=calc_supertrend(klines); oi=calc_oi_proxy(c,v); rsi_arr=calc_rsi(c)
    ind=[]
    for i in range(len(klines)):
        if i<72: ind.append(None); continue
        o1=oi[i] if i<len(oi) else 0; o4=sum(oi[max(0,i-4):i])
        streak=0
        for j in range(i,max(0,i-5),-1):
            if j<len(oi) and oi[j]>0: streak+=1
            else: break
        vs=v[max(0,i-24):i]; vm=sorted(vs)[len(vs)//2] if vs else 1; vr=v[i]/max(vm,1)
        vs5=v[max(0,i-120):i]; vm5=sorted(vs5)[len(vs5)//2] if vs5 else 1; vr5=v[i]/max(vm5,1)
        c1=(c[i]-c[i-1])/max(c[i-1],0.001)*100 if i>=1 else 0
        c4=(c[i]-c[i-4])/max(c[i-4],0.001)*100 if i>=4 else 0
        ema7 = calc_ema(c[max(0,i-7):i+1], 7)
        ema25 = calc_ema(c[max(0,i-25):i+1], 25)
        ind.append({"close":c[i],"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"rsi":rsi_arr[i],
            "ema7":ema7,"ema25":ema25})
    return ind, c, v, st

def score_v3(d, st_dir):
    """v3.0 当前评分"""
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

def score_v41(d, st_dir):
    """v4.1 吸收OI资金流+均线共振"""
    s=0
    hard=0; soft=0
    
    # SuperTrend
    if st_dir>0: s+=15; hard+=1
    elif st_dir<0: s-=10
    
    # 均线共振
    if d["ema7"] > d["ema25"]: s+=10; hard+=1
    else: s-=5
    
    # OI资金流判断 (核心改进)
    if d["chg_1h"] > 0 and d["oi_chg_1h"] > 0:
        s+=20; soft+=1  # 价格涨+OI涨 = 新资金进场
    elif d["chg_1h"] > 0 and d["oi_chg_1h"] < 0:
        s-=8  # 价格涨+OI降 = 空头回补
    elif d["chg_1h"] < 0 and d["oi_chg_1h"] > 0:
        s-=12  # 价格跌+OI涨 = 新空头压盘
    elif d["chg_1h"] < 0 and d["oi_chg_1h"] < 0:
        s-=5  # 价格跌+OI降 = 多头爆仓
    
    # OI 4h
    if d["oi_chg_4h"]>8: s+=15; soft+=1
    elif d["oi_chg_4h"]>4: s+=10
    elif d["oi_chg_4h"]>0: s+=5
    elif d["oi_chg_4h"]<0: s-=8
    
    # OI连续
    if d["oi_up_streak"]>=3: s+=10; soft+=1
    elif d["oi_up_streak"]>=2: s+=5
    
    # 成交量
    if d["vol_ratio"]>2.0: s+=10; soft+=1
    elif d["vol_ratio"]>1.4: s+=5
    
    # 价格变化
    if d["chg_4h"]>2: s+=10
    elif d["chg_4h"]>0: s+=5
    elif d["chg_4h"]<0: s-=8
    
    if d["chg_1h"]>0.2: s+=8
    elif d["chg_1h"]>0: s+=4
    
    return s, hard, soft

def sim_v3(symbol, klines):
    """v3.0 当前策略 (分批止盈)"""
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    stop_loss=0.05
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            score=score_v3(d, st[i])
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
            if not first_half_closed and pnl>=0.50:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp1","peak":peak*100})
                first_half_closed=True
            if first_half_closed and peak>=0.10 and (peak-pnl)>=0.15:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp2","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            if i-pos["entry_bar"]>=168:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"to"})
                pos=None; cooldown_until=i+2
    return trades

def sim_v41(symbol, klines, hard_min=1, soft_min=1, score_min=55):
    """v4.1 吸收思想+保留原止盈"""
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    stop_loss=0.05
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            score, hard, soft = score_v41(d, st[i])
            rsi=d["rsi"]
            if st[i]<0 or rsi<30 or d["chg_4h"]<0: continue
            if rsi>80: pass
            elif rsi>70: score-=10
            # 多证据共振
            if hard<1 or soft<1: continue
            if score>=score_min:
                pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                peak=0; first_half_closed=False
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            if pnl<=-stop_loss:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"sl","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            if not first_half_closed and pnl>=0.50:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp1","peak":peak*100})
                first_half_closed=True
            if first_half_closed and peak>=0.10 and (peak-pnl)>=0.15:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"tp2","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            if i-pos["entry_bar"]>=168:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"to"})
                pos=None; cooldown_until=i+2
    return trades

def stats(trades):
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"sl":0,"mxl":0}
    wins=[t for t in trades if t["pnl"]>0]
    sl=sum(1 for t in trades if t.get("reason")=="sl")
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),"sl":sl,
        "mxl":min(t["pnl"] for t in trades)}

# 加载数据
print("加载数据...")
all_klines = {}
for coin in COINS:
    kl = fetch_klines(coin, "1h", 750)
    if kl and len(kl) >= 100:
        all_klines[coin] = kl
    time.sleep(0.1)

print(f"加载 {len(all_klines)} 个币")
print()

# 回测
v3_trades = []
v41_trades = []

for coin, kl in all_klines.items():
    v3_trades.extend(sim_v3(coin, kl))
    v41_trades.extend(sim_v41(coin, kl, hard_min=1, soft_min=1, score_min=55))

s3 = stats(v3_trades)
s41 = stats(v41_trades)

print("="*70)
print("v3.0 vs v4.1 吸收思想+保留原止盈 (26币 30天)")
print("="*70)
print(f"{'策略':<25} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'效率':<8}")
print("-"*70)
eff3 = s3['tot']/s3['sl'] if s3['sl']>0 else 0
eff41 = s41['tot']/s41['sl'] if s41['sl']>0 else 0
print(f"{'v3.0 当前':<25} {s3['n']:<6} {s3['wr']:<7.1f} {s3['avg']:<8.1f} {s3['tot']:<9.1f} {s3['sl']:<5} {eff3:<8.1f}")
print(f"{'v4.1 OI资金流+共振':<25} {s41['n']:<6} {s41['wr']:<7.1f} {s41['avg']:<8.1f} {s41['tot']:<9.1f} {s41['sl']:<5} {eff41:<8.1f}")

diff = s41['tot'] - s3['tot']
print()
print(f"收益差异: {diff:+.1f}% ({'v4.1更优' if diff > 0 else 'v3更优'})")
print(f"胜率差异: {s41['wr']-s3['wr']:+.1f}%")
print(f"止损差异: {s41['sl']-s3['sl']:+d}次")
print(f"效率差异: {eff41-eff3:+.1f}")
print()
print("v4.1改进:")
print("  ✅ OI资金流判断 (价格+OI组合)")
print("  ✅ 均线共振 (EMA7>EMA25)")
print("  ✅ 多证据共振 (1硬+1软)")
print("  ✅ 保留原止盈 (50%@+50%+追踪)")
