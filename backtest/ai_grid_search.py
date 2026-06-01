#!/usr/bin/env python3
"""AI策略参数网格搜索"""
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

def score_signal(d, st_dir, short_squeeze_bonus=15):
    """可配置的评分函数"""
    s=0
    if d["oi_chg_4h"]>8: s+=25
    elif d["oi_chg_4h"]>4: s+=15
    elif d["oi_chg_4h"]>0: s+=8
    if d["oi_chg_1h"]>0.4: s+=15
    elif d["oi_chg_1h"]>0: s+=8
    if d["oi_up_streak"]>=3: s+=10
    elif d["oi_up_streak"]>=2: s+=5
    
    # 逼空信号 (OI下降+价格上涨)
    if d["oi_chg_4h"] < -5 and d["chg_4h"] > 5:
        s += short_squeeze_bonus
    
    if d["vol_ratio"]>2.0: s+=15
    elif d["vol_ratio"]>1.4: s+=10
    if d["vol_ratio_5"]>2: s+=10
    elif d["vol_ratio_5"]>1.5: s+=5
    
    if d["chg_4h"]>5: s+=20
    elif d["chg_4h"]>2: s+=15
    elif d["chg_4h"]>0: s+=8
    if d["chg_1h"]>0.5: s+=15
    elif d["chg_1h"]>0.2: s+=10
    elif d["chg_1h"]>0: s+=5
    
    if st_dir>0: s+=15
    elif st_dir<0: s-=10
    return s

def sim(symbol, klines, params):
    """参数化模拟"""
    entry_score = params["entry_score"]
    sl_lock_trigger = params["sl_lock_trigger"]  # 盈利多少后锁止损
    sl_lock_target = params["sl_lock_target"]    # 锁定的止损位置
    score_exit = params["score_exit"]            # 评分低于此值离场
    sq_bonus = params["sq_bonus"]               # 逼空信号加分
    
    if len(klines)<100: return []
    ind,closes,volumes,st = calc_indicators(klines)
    trades=[]; pos=None; peak=0; first_half_closed=False; cooldown_until=0
    base_sl=0.06; current_sl=base_sl; sl_moved=False
    
    for i in range(72, len(klines)):
        if ind[i] is None: continue
        d=ind[i]
        if pos is None and i>=cooldown_until:
            score=score_signal(d, st[i], sq_bonus)
            rsi=d["rsi"]
            if st[i]<0 or rsi<30 or d["chg_4h"]<0: continue
            if rsi>80: pass
            elif rsi>70: score-=10
            if score>=entry_score:
                pos={"entry_price":closes[i],"entry_bar":i,"peak":0,"entry_score":score}
                peak=0; first_half_closed=False; sl_moved=False; current_sl=base_sl
        
        if pos:
            pnl=(closes[i]-pos["entry_price"])/max(pos["entry_price"],0.001)
            peak=max(peak,pnl)
            
            # 评分离场
            if score_exit > 0:
                current_score = score_signal(d, st[i], sq_bonus)
                if current_score < score_exit and pnl > 0:
                    remaining=1.0 if not first_half_closed else 0.5
                    trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"score_drop","peak":peak*100})
                    pos=None; cooldown_until=i+2; continue
            
            # 利润锁定
            if peak >= sl_lock_trigger:
                current_sl = -sl_lock_target; sl_moved = True
            
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
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"sl":0}
    wins=[t for t in trades if t["pnl"]>0]
    sl=sum(1 for t in trades if t.get("reason") in ["sl","sl_trail"])
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),"sl":sl}

# 加载数据
print("加载数据...")
all_klines = {}
for coin in COINS:
    kl = fetch_klines(coin, "1h", 750)
    if kl and len(kl) >= 100:
        all_klines[coin] = kl
    time.sleep(0.1)
print(f"加载 {len(all_klines)} 个币")

# 参数组合
configs = [
    # 基准
    {"name": "v3.0基准", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    
    # 入场评分测试
    {"name": "评分60", "entry_score": 60, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    {"name": "评分65", "entry_score": 65, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    {"name": "评分70", "entry_score": 70, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    
    # 利润锁定测试
    {"name": "锁8%→5%", "entry_score": 55, "sl_lock_trigger": 0.08, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    {"name": "锁15%→5%", "entry_score": 55, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    {"name": "锁20%→5%", "entry_score": 55, "sl_lock_trigger": 0.20, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 0},
    {"name": "锁15%→8%", "entry_score": 55, "sl_lock_trigger": 0.15, "sl_lock_target": 0.08, "score_exit": 0, "sq_bonus": 0},
    
    # 评分离场测试
    {"name": "评分<50离场", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 50, "sq_bonus": 0},
    {"name": "评分<55离场", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 55, "sq_bonus": 0},
    {"name": "评分<60离场", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 60, "sq_bonus": 0},
    
    # 逼空信号测试
    {"name": "逼空+10", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 10},
    {"name": "逼空+15", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 15},
    {"name": "逼空+20", "entry_score": 55, "sl_lock_trigger": 0.30, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 20},
    
    # 组合最优
    {"name": "组合A: 评分65+锁15%+评分离场55", "entry_score": 65, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 55, "sq_bonus": 0},
    {"name": "组合B: 评分70+锁15%+评分离场55", "entry_score": 70, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 55, "sq_bonus": 0},
    {"name": "组合C: 评分65+锁15%+逼空15", "entry_score": 65, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 0, "sq_bonus": 15},
    {"name": "组合D: 评分70+锁15%+评分离场55+逼空15", "entry_score": 70, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 55, "sq_bonus": 15},
]

print()
print(f"{'配置':<40} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5}")
print("-"*80)

results = []
for cfg in configs:
    all_trades = []
    for coin, kl in all_klines.items():
        all_trades.extend(sim(coin, kl, cfg))
    s = stats(all_trades)
    results.append((cfg["name"], s))
    print(f"{cfg['name']:<40} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5}")

# 找最优
print()
print("="*80)
print("TOP 5 配置 (按累计收益):")
results.sort(key=lambda x: x[1]["tot"], reverse=True)
for i, (name, s) in enumerate(results[:5]):
    print(f"  {i+1}. {name}: {s['tot']:.1f}% | 胜率{s['wr']:.1f}% | {s['n']}笔")

print()
print("TOP 5 配置 (按胜率):")
results.sort(key=lambda x: x[1]["wr"], reverse=True)
for i, (name, s) in enumerate(results[:5]):
    if s['n'] >= 50:  # 至少50笔交易
        print(f"  {i+1}. {name}: 胜率{s['wr']:.1f}% | {s['tot']:.1f}% | {s['n']}笔")

print()
print("TOP 5 配置 (按效率 = 累计/止损):")
results_eff = [(name, s, s['tot']/max(s['sl'],1)) for name, s in results if s['n'] >= 50]
results_eff.sort(key=lambda x: x[2], reverse=True)
for i, (name, s, eff) in enumerate(results_eff[:5]):
    print(f"  {i+1}. {name}: 效率{eff:.1f} | {s['tot']:.1f}% | 胜率{s['wr']:.1f}% | 止损{s['sl']}")
