#!/usr/bin/env python3
"""信号优化回测 v2 - 更严格的过滤方案"""
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

def sim(symbol, klines, strategy_name):
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    stop_loss=0.05
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        
        if pos is None and i>=cooldown_until:
            score=score_signal(d, st[i])
            rsi=d["rsi"]
            st_dir=st[i]
            pass_filter = True
            
            # v2.6当前: ST>=0 + score>=55 + RSI<75 + RSI>30 + chg_4h>=0
            if strategy_name == "v2.6_current":
                if st_dir<0: pass_filter=False
                elif rsi>75: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                else:
                    if rsi>70: score-=10
                    if score<55: pass_filter=False
            
            # G1: OI 1h必须上涨 (不能下跌)
            elif strategy_name == "G_oi1h_positive":
                if st_dir<0: pass_filter=False
                elif rsi>75: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                elif d["oi_chg_1h"]<=0: pass_filter=False
                else:
                    if rsi>70: score-=10
                    if score<55: pass_filter=False
            
            # G2: OI 4h必须上涨
            elif strategy_name == "G_oi4h_positive":
                if st_dir<0: pass_filter=False
                elif rsi>75: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                elif d["oi_chg_4h"]<=0: pass_filter=False
                else:
                    if rsi>70: score-=10
                    if score<55: pass_filter=False
            
            # G3: 成交量 >= 1.0 (不能低于均值)
            elif strategy_name == "G_vol_1x":
                if st_dir<0: pass_filter=False
                elif rsi>75: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                elif d["vol_ratio"]<1.0: pass_filter=False
                else:
                    if rsi>70: score-=10
                    if score<55: pass_filter=False
            
            # G4: RSI > 65不开
            elif strategy_name == "G_rsi65":
                if st_dir<0: pass_filter=False
                elif rsi>65: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                else:
                    if score<55: pass_filter=False
            
            # G5: 提高评分到65
            elif strategy_name == "G_score65":
                if st_dir<0: pass_filter=False
                elif rsi>75: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                else:
                    if rsi>70: score-=10
                    if score<65: pass_filter=False
            
            # G6: 组合 (OI 1h>0 + vol>=1.0 + RSI<65 + score>=60)
            elif strategy_name == "G_combo":
                if st_dir<0: pass_filter=False
                elif rsi>65: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                elif d["oi_chg_1h"]<=0: pass_filter=False
                elif d["vol_ratio"]<1.0: pass_filter=False
                elif score<60: pass_filter=False
            
            # G7: 组合2 (OI 1h>0 + OI 4h>0 + vol>=1.2 + RSI<65 + score>=60)
            elif strategy_name == "G_combo2":
                if st_dir<0: pass_filter=False
                elif rsi>65: pass_filter=False
                elif rsi<30: pass_filter=False
                elif d["chg_4h"]<0: pass_filter=False
                elif d["oi_chg_1h"]<=0: pass_filter=False
                elif d["oi_chg_4h"]<=0: pass_filter=False
                elif d["vol_ratio"]<1.2: pass_filter=False
                elif score<60: pass_filter=False
            
            if pass_filter:
                pos={"entry_price":closes[i],"entry_bar":i,"entry_time":klines[i][0]}
                peak=0; first_half_closed=False
        
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            if pnl<=-stop_loss:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"sl","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            if not first_half_closed and pnl>=0.50:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"fixed50_1st","peak":peak*100})
                first_half_closed=True
            if first_half_closed:
                if peak>=0.10 and (peak-pnl)>=0.15:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"trail_2nd","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            if i-pos["entry_bar"]>=168:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"timeout"})
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

STRATEGIES = [
    "v2.6_current", "G_oi1h_positive", "G_oi4h_positive",
    "G_vol_1x", "G_rsi65", "G_score65", "G_combo", "G_combo2"
]
STRAT_NAMES = {
    "v2.6_current":"v2.6当前(55分/RSI75/4h过滤)",
    "G_oi1h_positive":"G1:OI 1h必须上涨",
    "G_oi4h_positive":"G2:OI 4h必须上涨",
    "G_vol_1x":"G3:成交量>=1.0x",
    "G_rsi65":"G4:RSI<65",
    "G_score65":"G5:评分>=65",
    "G_combo":"G6:组合(OI1h+Vol+RSI+60分)",
    "G_combo2":"G7:严选(OI1h+OI4h+Vol1.2+RSI+60分)",
}

all_trades={s:[] for s in STRATEGIES}
coin_count=0

for coin in COINS:
    kl=fetch_klines(coin,"1h",750)
    if not kl or len(kl)<100: continue
    coin_count+=1
    for s in STRATEGIES:
        all_trades[s].extend(sim(coin,kl,s))
    time.sleep(0.1)

print(f"{'='*90}")
print(f"信号优化回测 v2 - {coin_count}个币 30天")
print(f"{'='*90}")
print(f"{'策略':<35} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'最大亏':<8}")
print("-"*90)

base_tot = 0
for s in STRATEGIES:
    st=stats(all_trades[s])
    nm=STRAT_NAMES[s]
    if s == "v2.6_current": base_tot = st['tot']
    diff = st['tot'] - base_tot
    marker = " ⭐" if st['tot'] > base_tot + 50 else ""
    print(f"{nm:<35} {st['n']:<6} {st['wr']:<7.1f} {st['avg']:<8.1f} {st['tot']:<9.1f} {st['sl']:<5} {st['mxl']:<8.1f}{marker}")
