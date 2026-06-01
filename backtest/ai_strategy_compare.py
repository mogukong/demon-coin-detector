#!/usr/bin/env python3
"""吸收AI策略改进回测"""
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
        ind.append({"close":c[i],"oi_chg_1h":o1,"oi_chg_4h":o4,"oi_up_streak":streak,
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"rsi":rsi_arr[i]})
    return ind, c, v, st

def score_signal_v3(d, st_dir):
    """当前v3.0评分"""
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

def score_signal_v4(d, st_dir):
    """v4.0评分 - 吸收AI策略"""
    s=0
    # OI信号
    if d["oi_chg_4h"]>8: s+=25
    elif d["oi_chg_4h"]>4: s+=15
    elif d["oi_chg_4h"]>0: s+=8
    if d["oi_chg_1h"]>0.4: s+=15
    elif d["oi_chg_1h"]>0: s+=8
    if d["oi_up_streak"]>=3: s+=10
    elif d["oi_up_streak"]>=2: s+=5
    
    # 逼空信号 (OI下降+价格上涨) - 新增
    if d["oi_chg_4h"] < -5 and d["chg_4h"] > 5:
        s += 20  # 逼空信号加分
    
    # 成交量
    if d["vol_ratio"]>2.0: s+=15
    elif d["vol_ratio"]>1.4: s+=10
    if d["vol_ratio_5"]>2: s+=10
    elif d["vol_ratio_5"]>1.5: s+=5
    
    # 价格动能
    if d["chg_4h"]>5: s+=20  # 更高阈值
    elif d["chg_4h"]>2: s+=15
    elif d["chg_4h"]>0: s+=8
    if d["chg_1h"]>0.5: s+=15  # 更高阈值
    elif d["chg_1h"]>0.2: s+=10
    elif d["chg_1h"]>0: s+=5
    
    # SuperTrend
    if st_dir>0: s+=15
    elif st_dir<0: s-=10
    
    return s

def sim(symbol, klines, mode="v3"):
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    base_sl=0.06; current_sl=base_sl; sl_moved=False
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            if mode == "v3":
                score=score_signal_v3(d, st[i])
                entry_threshold = 55
            else:
                score=score_signal_v4(d, st[i])
                entry_threshold = 75
            
            rsi=d["rsi"]
            if st[i]<0 or rsi<30 or d["chg_4h"]<0: continue
            if rsi>80: pass
            elif rsi>70: score-=10
            
            if score>=entry_threshold:
                pos={"entry_price":closes[i],"entry_bar":i,"peak":0,"entry_score":score}
                peak=0; first_half_closed=False; sl_moved=False; current_sl=base_sl
        
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            
            # v4.0: 评分跌破60立即离场
            if mode == "v4":
                current_score = score_signal_v4(d, st[i])
                if current_score < 60 and pnl > 0:
                    remaining=1.0 if not first_half_closed else 0.5
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"score_drop","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            # 移动止损逻辑
            if mode == "v3":
                if peak >= 0.30:
                    current_sl = -0.05; sl_moved = True
            else:  # v4
                # 盈利8%后止损锁5%
                if peak >= 0.08:
                    current_sl = -0.05; sl_moved = True
            
            if pnl <= -current_sl:
                remaining=1.0 if not first_half_closed else 0.5
                reason = "sl_trail" if sl_moved else "sl"
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":reason,"peak":peak*100})
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
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"sl":0,"sl_trail":0,"score_drop":0}
    wins=[t for t in trades if t["pnl"]>0]
    sl=sum(1 for t in trades if t.get("reason")=="sl")
    sl_trail=sum(1 for t in trades if t.get("reason")=="sl_trail")
    score_drop=sum(1 for t in trades if t.get("reason")=="score_drop")
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),"sl":sl,"sl_trail":sl_trail,"score_drop":score_drop}

print("加载数据...")
all_klines = {}
for coin in COINS:
    kl = fetch_klines(coin, "1h", 750)
    if kl and len(kl) >= 100:
        all_klines[coin] = kl
    time.sleep(0.1)

print(f"加载 {len(all_klines)} 个币")
print()

modes = [
    ("v3", "v3.0 (当前: Score≥55, 盈利30%移止损)"),
    ("v4", "v4.0 (AI改进: Score≥75, 盈利8%锁5%, 评分<60离场)"),
]

print(f"{'模式':<45} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'移动SL':<7} {'评分离场':<8}")
print("-"*95)

for mode, name in modes:
    all_trades = []
    for coin, kl in all_klines.items():
        all_trades.extend(sim(coin, kl, mode))
    s = stats(all_trades)
    print(f"{name:<45} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5} {s['sl_trail']:<7} {s['score_drop']:<8}")

print()
print("改进说明:")
print("  v4.0: 入场评分55→75 (更严格)")
print("  v4.0: 盈利8%后止损锁5% (更早保护利润)")
print("  v4.0: 评分<60立即离场 (动态风控)")
print("  v4.0: 逼空信号加分 (OI下降+价格上涨)")
