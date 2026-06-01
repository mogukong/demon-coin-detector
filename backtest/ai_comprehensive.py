#!/usr/bin/env python3
"""吸收AI策略综合回测 - EMA回踩+评分动态+多周期共振"""
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

def calc_ema(data, period):
    """计算EMA"""
    if len(data) < period: return [0]*len(data)
    ema = [0]*len(data)
    ema[period-1] = sum(data[:period]) / period
    mult = 2 / (period + 1)
    for i in range(period, len(data)):
        ema[i] = data[i] * mult + ema[i-1] * (1 - mult)
    return ema

def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD"""
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = calc_ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram

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
    ema10=calc_ema(c, 10); ema20=calc_ema(c, 20)
    macd_line, signal_line, histogram = calc_macd(c)
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
            "vol_ratio":vr,"vol_ratio_5":vr5,"chg_1h":c1,"chg_4h":c4,"rsi":rsi_arr[i],
            "ema10":ema10[i],"ema20":ema20[i],"macd":macd_line[i],"macd_signal":signal_line[i],"macd_hist":histogram[i]})
    return ind, c, v, st

def score_signal(d, st_dir, sq_bonus=0):
    s=0
    if d["oi_chg_4h"]>8: s+=25
    elif d["oi_chg_4h"]>4: s+=15
    elif d["oi_chg_4h"]>0: s+=8
    if d["oi_chg_1h"]>0.4: s+=15
    elif d["oi_chg_1h"]>0: s+=8
    if d["oi_up_streak"]>=3: s+=10
    elif d["oi_up_streak"]>=2: s+=5
    if d["oi_chg_4h"] < -5 and d["chg_4h"] > 5:
        s += sq_bonus
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
    
    # MACD多周期共振加分
    if d["macd_hist"] > 0:
        s += 10  # MACD金叉加分
    
    return s

def sim(symbol, klines, params):
    entry_score = params.get("entry_score", 70)
    sl_lock_trigger = params.get("sl_lock_trigger", 0.15)
    sl_lock_target = params.get("sl_lock_target", 0.05)
    score_exit = params.get("score_exit", 55)
    sq_bonus = params.get("sq_bonus", 0)
    tp1_pct = params.get("tp1_pct", 0.40)
    tp1_sell = params.get("tp1_sell", 0.50)
    trail_activate = params.get("trail_activate", 0.10)
    trail_drawdown = params.get("trail_drawdown", 0.15)
    max_hold = params.get("max_hold", 168)
    use_ema_pullback = params.get("use_ema_pullback", False)
    use_macd_filter = params.get("use_macd_filter", False)
    allow_st_down = params.get("allow_st_down", False)
    
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
            
            # 基础过滤
            if rsi<30 or d["chg_4h"]<0: continue
            
            # SuperTrend过滤
            if st[i]<0 and not allow_st_down:
                continue
            
            # RSI处理
            if rsi>80: pass
            elif rsi>70: score-=10
            
            # EMA回踩入场
            if use_ema_pullback:
                # 价格必须在EMA20之上
                if d["close"] < d["ema20"]:
                    continue
                # 价格回踩EMA10附近(±2%)
                ema10_dist = abs(d["close"] - d["ema10"]) / d["ema10"]
                if ema10_dist > 0.02:
                    continue  # 不在EMA10附近，跳过
            
            # MACD过滤
            if use_macd_filter:
                if d["macd_hist"] <= 0:
                    continue  # MACD死叉，跳过
            
            # 评分阈值
            min_score = entry_score
            if allow_st_down and st[i]<0:
                min_score = entry_score + 10  # SuperTrend下降时需要更高评分
            
            if score>=min_score:
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
            
            # 第一批止盈
            if not first_half_closed and pnl>=tp1_pct:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*tp1_sell*100,"reason":"tp1","peak":peak*100})
                first_half_closed=True
            # 追踪止盈
            if first_half_closed and peak>=trail_activate and (peak-pnl)>=trail_drawdown:
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*(1-tp1_sell)*100,"reason":"tp2","peak":peak*100})
                pos=None; cooldown_until=i+2; continue
            
            # 超时
            if i-pos["entry_bar"]>=max_hold:
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

# 基准配置
base = {"entry_score": 70, "sl_lock_trigger": 0.15, "sl_lock_target": 0.05, "score_exit": 55, "sq_bonus": 0, "tp1_pct": 0.40, "tp1_sell": 0.50, "trail_activate": 0.10, "trail_drawdown": 0.15}

# 测试配置
configs = [
    # 基准
    {"name": "v3.1基准", **base},
    
    # EMA回踩入场
    {"name": "EMA回踩入场", **base, "use_ema_pullback": True},
    
    # MACD过滤
    {"name": "MACD金叉过滤", **base, "use_macd_filter": True},
    
    # 允许SuperTrend下降(高评分)
    {"name": "允许ST下降+评分80", **base, "allow_st_down": True, "entry_score": 80},
    {"name": "允许ST下降+评分85", **base, "allow_st_down": True, "entry_score": 85},
    
    # 组合: EMA回踩+MACD
    {"name": "EMA回踩+MACD", **base, "use_ema_pullback": True, "use_macd_filter": True},
    
    # 组合: 允许ST下降+MACD
    {"name": "允许ST下降+MACD+评分80", **base, "allow_st_down": True, "entry_score": 80, "use_macd_filter": True},
    
    # 更早止盈 (10-15%)
    {"name": "TP1@15%", **base, "tp1_pct": 0.15},
    {"name": "TP1@20%", **base, "tp1_pct": 0.20},
    
    # 组合: 允许ST下降+更早止盈
    {"name": "允许ST下降+TP1@15%+评分80", **base, "allow_st_down": True, "entry_score": 80, "tp1_pct": 0.15},
    
    # 最优组合
    {"name": "最优: 允许ST下降+MACD+TP1@15%+评分80", **base, "allow_st_down": True, "entry_score": 80, "use_macd_filter": True, "tp1_pct": 0.15},
]

print()
print(f"{'配置':<45} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5}")
print("-"*85)

results = []
for cfg in configs:
    all_trades = []
    for coin, kl in all_klines.items():
        all_trades.extend(sim(coin, kl, cfg))
    s = stats(all_trades)
    results.append((cfg["name"], s, cfg))
    print(f"{cfg['name']:<45} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5}")

# 找最优
print()
print("="*85)
print("TOP 5 配置 (按累计收益):")
results.sort(key=lambda x: x[1]["tot"], reverse=True)
for i, (name, s, cfg) in enumerate(results[:5]):
    print(f"  {i+1}. {name}: {s['tot']:.1f}% | 胜率{s['wr']:.1f}% | {s['n']}笔 | 止损{s['sl']}")

print()
print("TOP 5 配置 (按效率 = 累计/止损):")
results_eff = [(name, s, cfg, s['tot']/max(s['sl'],1)) for name, s, cfg in results if s['n'] >= 50]
results_eff.sort(key=lambda x: x[3], reverse=True)
for i, (name, s, cfg, eff) in enumerate(results_eff[:5]):
    print(f"  {i+1}. {name}: 效率{eff:.1f} | {s['tot']:.1f}% | 胜率{s['wr']:.1f}% | 止损{s['sl']}")
