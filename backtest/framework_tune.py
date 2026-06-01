#!/usr/bin/env python3
"""v3.0 参数调优回测"""
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

def detect_regime(klines_slice):
    if len(klines_slice) < 20: return "range"
    closes = [float(k[4]) for k in klines_slice[-20:]]
    highs = [float(k[2]) for k in klines_slice[-20:]]
    lows = [float(k[3]) for k in klines_slice[-20:]]
    up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    trend_strength = abs(up_count - (len(closes)-1-up_count)) / (len(closes)-1)
    atr_vals = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        atr_vals.append(tr)
    atr = sum(atr_vals) / len(atr_vals) if atr_vals else 0
    volatility = atr / closes[-1] if closes[-1] > 0 else 0
    max_spike = max((highs[i]-lows[i])/lows[i] for i in range(len(closes))) if lows else 0
    if max_spike > 0.08: return "spike"
    elif volatility > 0.03: return "trend" if trend_strength > 0.6 else "range"
    else: return "range"

def get_regime_params(regime, sl_mult_trend=1.5, sl_mult_range=0.8, trail_trend=0.12, trail_range=0.08):
    params = {
        "trend": {"sl_mult": sl_mult_trend, "trail_act": trail_trend, "trail_draw": 0.18, "timeout": 240},
        "range": {"sl_mult": sl_mult_range, "trail_act": trail_range, "trail_draw": 0.12, "timeout": 120},
        "spike": {"sl_mult": 0.6, "trail_act": 0.06, "trail_draw": 0.10, "timeout": 48},
    }
    return params.get(regime, params["range"])

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

def estimate_ev(win_rate, avg_win, avg_loss):
    cost = 0.0004*2 + 0.001 + 0.0001
    return win_rate * avg_win + (1-win_rate) * avg_loss - cost

def sim_v3_tuned(symbol, klines, ev_threshold=0.01, score_threshold=55, 
                 sl_mult_trend=1.2, sl_mult_range=0.9, trail_trend=0.10, trail_range=0.08):
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    base_sl=0.05
    recent_wins = 0; recent_total = 0
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        
        if pos is None and i>=cooldown_until:
            score=score_signal(d, st[i])
            rsi=d["rsi"]
            st_dir=st[i]
            pass_filter = True
            
            if st_dir<0: pass_filter=False
            elif rsi<30: pass_filter=False
            elif d["chg_4h"]<0: pass_filter=False
            else:
                if rsi>80: pass
                elif rsi>70: score-=10
                if score<score_threshold: pass_filter=False
            
            # EV预估
            if pass_filter and recent_total >= 5:
                win_rate = recent_wins / recent_total
                ev = estimate_ev(win_rate, 0.15, -0.05)
                if ev < ev_threshold:
                    pass_filter = False
            
            # 行情状态
            regime = "range"
            if pass_filter:
                regime = detect_regime(klines[max(0,i-20):i])
                rp = get_regime_params(regime, sl_mult_trend, sl_mult_range, trail_trend, trail_range)
                stop_loss = base_sl * rp["sl_mult"]
                trail_activate = rp["trail_act"]
                trail_draw = rp["trail_draw"]
                timeout = rp["timeout"]
            else:
                stop_loss = base_sl
                trail_activate = 0.10
                trail_draw = 0.15
                timeout = 168
            
            if pass_filter:
                pos={"entry_price":closes[i],"entry_bar":i,"entry_time":klines[i][0],"regime":regime,"peak":0}
                peak=0; first_half_closed=False
        
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            regime = pos.get("regime", "range")
            rp = get_regime_params(regime, sl_mult_trend, sl_mult_range, trail_trend, trail_range)
            sl = base_sl * rp["sl_mult"]
            ta = rp["trail_act"]
            td = rp["trail_draw"]
            to = rp["timeout"]
            
            if pnl<=-sl:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"sl","peak":peak*100})
                recent_total += 1
                pos=None; cooldown_until=i+2; continue
            if not first_half_closed and pnl>=0.50:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"fixed50_1st","peak":peak*100})
                first_half_closed=True
            if first_half_closed:
                if peak>=ta and (peak-pnl)>=td:
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*50,"reason":"trail_2nd","peak":peak*100})
                    if pnl > 0: recent_wins += 1
                    recent_total += 1
                    pos=None; cooldown_until=i+2; continue
            if i-pos["entry_bar"]>=to:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"timeout"})
                if pnl > 0: recent_wins += 1
                recent_total += 1
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
    {"name": "v2.7基准", "ev": 0.01, "score": 55, "sl_trend": 1.0, "sl_range": 1.0, "trail_trend": 0.10, "trail_range": 0.10},
    {"name": "v3.0保守", "ev": 0.02, "score": 55, "sl_trend": 1.5, "sl_range": 0.8, "trail_trend": 0.12, "trail_range": 0.08},
    {"name": "v3.0平衡", "ev": 0.01, "score": 55, "sl_trend": 1.2, "sl_range": 0.9, "trail_trend": 0.10, "trail_range": 0.08},
    {"name": "v3.0激进", "ev": 0.005, "score": 50, "sl_trend": 1.3, "sl_range": 1.0, "trail_trend": 0.10, "trail_range": 0.10},
    {"name": "v3.0宽松", "ev": 0.0, "score": 55, "sl_trend": 1.2, "sl_range": 0.9, "trail_trend": 0.10, "trail_range": 0.08},
]

print(f"{'配置':<15} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5} {'最大亏':<8} {'效率':<8}")
print("-"*75)

results = []
for cfg in configs:
    all_trades = []
    for coin, kl in all_klines.items():
        trades = sim_v3_tuned(coin, kl, 
                              ev_threshold=cfg["ev"], 
                              score_threshold=cfg["score"],
                              sl_mult_trend=cfg["sl_trend"],
                              sl_mult_range=cfg["sl_range"],
                              trail_trend=cfg["trail_trend"],
                              trail_range=cfg["trail_range"])
        all_trades.extend(trades)
    
    s = stats(all_trades)
    efficiency = s["tot"] / s["sl"] if s["sl"] > 0 else 0
    results.append((cfg["name"], s, efficiency))
    print(f"{cfg['name']:<15} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5} {s['mxl']:<8.1f} {efficiency:<8.1f}")

# 找最优
best = max(results, key=lambda x: x[1]["tot"])
best_eff = max(results, key=lambda x: x[2])

print()
print(f"🏆 最高收益: {best[0]} ({best[1]['tot']:.1f}%)")
print(f"⭐ 最高效率: {best_eff[0]} (每次止损赚{best_eff[2]:.1f}%)")
