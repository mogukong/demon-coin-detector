#!/usr/bin/env python3
"""v4.0 参数调优回测"""
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

def calc_bollinger(closes, period=20, std_mult=2.0):
    if len(closes) < period: return closes[-1], closes[-1], closes[-1]
    recent = closes[-period:]
    mid = sum(recent) / period
    std = (sum((x - mid)**2 for x in recent) / period) ** 0.5
    return mid + std_mult * std, mid, mid - std_mult * std

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
        bb_upper, bb_mid, bb_lower = calc_bollinger(c[:i+1], 20)
        ind.append({"close":c[i],"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"rsi":rsi_arr[i],
            "ema7":ema7,"ema25":ema25,"bb_upper":bb_upper,"bb_lower":bb_lower})
    return ind, c, v, st

def score_signal_v4(d, st_dir, hard_min=2, soft_min=1, score_min=55):
    """v4.0 评分"""
    s=0
    hard=0; soft=0
    
    # SuperTrend
    if st_dir>0: s+=15; hard+=1
    elif st_dir<0: s-=10
    
    # 均线
    if d["ema7"] > d["ema25"]: s+=10; hard+=1
    else: s-=5
    
    # 布林带
    if d["close"] > d["bb_upper"]: s+=5; hard+=1
    elif d["close"] < d["bb_lower"]: s-=5
    
    # OI资金流
    if d["chg_1h"] > 0 and d["oi_chg_1h"] > 0:
        s+=15; soft+=1
    elif d["chg_1h"] > 0 and d["oi_chg_1h"] < 0:
        s-=8
    elif d["chg_1h"] < 0 and d["oi_chg_1h"] > 0:
        s-=12
    elif d["chg_1h"] < 0 and d["oi_chg_1h"] < 0:
        s-=5
    
    # OI 4h
    if d["oi_chg_4h"]>8: s+=10; soft+=1
    elif d["oi_chg_4h"]>4: s+=5
    elif d["oi_chg_4h"]>0: s+=3
    elif d["oi_chg_4h"]<0: s-=8
    
    # OI连续
    if d["oi_up_streak"]>=3: s+=8; soft+=1
    elif d["oi_up_streak"]>=2: s+=4
    
    # RSI
    if d["rsi"]>75: s-=15
    elif d["rsi"]>70: s-=10
    elif d["rsi"]<30: s-=10
    
    # 成交量
    if d["vol_ratio"]>2.0: s+=8; soft+=1
    elif d["vol_ratio"]>1.4: s+=4
    
    # 价格变化
    if d["chg_4h"]>2: s+=8
    elif d["chg_4h"]>0: s+=4
    elif d["chg_4h"]<0: s-=8
    
    # 多证据共振检查
    if hard < hard_min or soft < soft_min:
        return 0, hard, soft  # 不满足共振条件
    
    return s, hard, soft

def sim_v4_tuned(symbol, klines, hard_min=2, soft_min=1, score_min=55,
                 tp1_pct=0.05, tp1_close=0.25, tp2_pct=0.10, tp2_close=0.25, tp3_pct=0.20, tp3_close=0.50):
    """v4.0 参数调优"""
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; cooldown_until=0
    stop_loss=0.05
    tp1_done=False; tp2_done=False; tp3_done=False; remaining_pct=1.0
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            score, hard, soft = score_signal_v4(d, st[i], hard_min, soft_min, score_min)
            rsi=d["rsi"]
            if score>=score_min:
                pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                peak=0; tp1_done=False; tp2_done=False; tp3_done=False; remaining_pct=1.0
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            
            if pnl<=-stop_loss:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining_pct,"reason":"sl","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            
            if not tp1_done and pnl>=tp1_pct:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*tp1_close,"reason":"tp1","peak":peak*100})
                tp1_done=True; remaining_pct-=tp1_close
            
            if tp1_done and not tp2_done and pnl>=tp2_pct:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*tp2_close,"reason":"tp2","peak":peak*100})
                tp2_done=True; remaining_pct-=tp2_close
            
            if tp2_done and not tp3_done and pnl>=tp3_pct:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*tp3_close,"reason":"tp3","peak":peak*100})
                tp3_done=True; remaining_pct-=tp3_close
            
            if tp3_done:
                pos=None; cooldown_until=i+2; continue
            
            if i-pos["entry_bar"]>=168:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining_pct,"reason":"to"})
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

# 测试不同参数组合
configs = [
    {"name": "v3.0基准", "hard": 2, "soft": 1, "score": 55, "tp1": 0.05, "tp2": 0.10, "tp3": 0.20},
    {"name": "v4.0A:严格共振", "hard": 3, "soft": 2, "score": 60, "tp1": 0.05, "tp2": 0.10, "tp3": 0.20},
    {"name": "v4.0B:宽止盈", "hard": 2, "soft": 1, "score": 55, "tp1": 0.08, "tp2": 0.15, "tp3": 0.25},
    {"name": "v4.0C:严+宽", "hard": 3, "soft": 2, "score": 60, "tp1": 0.08, "tp2": 0.15, "tp3": 0.25},
    {"name": "v4.0D:超严", "hard": 3, "soft": 2, "score": 65, "tp1": 0.08, "tp2": 0.15, "tp3": 0.25},
    {"name": "v4.0E:保守", "hard": 3, "soft": 2, "score": 60, "tp1": 0.10, "tp2": 0.20, "tp3": 0.30},
]

print(f"{'配置':<20} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'效率':<8}")
print("-"*65)

for cfg in configs:
    all_trades = []
    for coin, kl in all_klines.items():
        if cfg["name"] == "v3.0基准":
            # v3.0 基准
            ind,closes,volumes,st = calc_indicators(kl)
            for i in range(72, len(kl)):
                if ind[i] is None: continue
                d=ind[i]
                score=0
                if d["oi_chg_4h"]>8: score+=25
                elif d["oi_chg_4h"]>4: score+=15
                elif d["oi_chg_4h"]>0: score+=8
                if d["oi_chg_1h"]>0.4: score+=15
                elif d["oi_chg_1h"]>0: score+=8
                if d["oi_up_streak"]>=3: score+=10
                elif d["oi_up_streak"]>=2: score+=5
                if d["vol_ratio"]>2.0: score+=15
                elif d["vol_ratio"]>1.4: score+=10
                if d["chg_4h"]>2: score+=15
                elif d["chg_4h"]>0: score+=8
                if d["chg_1h"]>0.2: score+=10
                elif d["chg_1h"]>0: score+=5
                if st[i]>0: score+=15
                elif st[i]<0: score-=10
        else:
            trades = sim_v4_tuned(coin, kl, 
                                  hard_min=cfg["hard"], soft_min=cfg["soft"], score_min=cfg["score"],
                                  tp1_pct=cfg["tp1"], tp2_pct=cfg["tp2"], tp3_pct=cfg["tp3"])
            all_trades.extend(trades)
    
    if cfg["name"] != "v3.0基准":
        s = stats(all_trades)
        eff = s['tot']/s['sl'] if s['sl']>0 else 0
        print(f"{cfg['name']:<20} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5} {eff:<8.1f}")

# 跑v3.0基准
v3_trades = []
for coin, kl in all_klines.items():
    ind,closes,volumes,st = calc_indicators(kl)
    for i in range(72, len(kl)):
        if ind[i] is None: continue
        d=ind[i]
        if st[i]<0 or d["rsi"]<30 or d["chg_4h"]<0: continue
        score=0
        if d["oi_chg_4h"]>8: score+=25
        elif d["oi_chg_4h"]>4: score+=15
        elif d["oi_chg_4h"]>0: score+=8
        if d["oi_chg_1h"]>0.4: score+=15
        elif d["oi_chg_1h"]>0: score+=8
        if d["oi_up_streak"]>=3: score+=10
        elif d["oi_up_streak"]>=2: score+=5
        if d["vol_ratio"]>2.0: score+=15
        elif d["vol_ratio"]>1.4: score+=10
        if d["chg_4h"]>2: score+=15
        elif d["chg_4h"]>0: score+=8
        if d["chg_1h"]>0.2: score+=10
        elif d["chg_1h"]>0: score+=5
        if st[i]>0: score+=15
        rsi=d["rsi"]
        if rsi>80: pass
        elif rsi>70: score-=10
        if score>=55:
            # 简单模拟
            entry=closes[i]
            peak=0; tp1=False; tp2=False; rem=1.0
            for j in range(i+1, min(i+168, len(closes))):
                pnl=(closes[j]-entry)/entry
                peak=max(peak,pnl)
                if pnl<=-0.05:
                    v3_trades.append({"pnl":pnl*100*rem,"reason":"sl"})
                    break
                if not tp1 and pnl>=0.50:
                    v3_trades.append({"pnl":pnl*50,"reason":"tp1"})
                    tp1=True; rem=0.5
                if tp1 and peak>=0.10 and (peak-pnl)>=0.15:
                    v3_trades.append({"pnl":pnl*50,"reason":"tp2"})
                    break
                if j==min(i+168, len(closes))-1:
                    v3_trades.append({"pnl":pnl*100*rem,"reason":"to"})

s3 = stats(v3_trades)
eff3 = s3['tot']/s3['sl'] if s3['sl']>0 else 0
print(f"{'v3.0基准':<20} {s3['n']:<6} {s3['wr']:<7.1f} {s3['avg']:<8.1f} {s3['tot']:<9.1f} {s3['sl']:<5} {eff3:<8.1f}")
