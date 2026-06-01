#!/usr/bin/env python3
"""山寨币整体表现过滤回测"""
import json, time
from urllib.request import urlopen

BASE_URL = "https://fapi.binance.com"
COINS = [
    "RAVEUSDT","LABUSDT","STOUSDT","SKYAIUSDT","BSBUSDT","SIRENUSDT","PLAYUSDT","GUAUSDT","ESPORTSUSDT",
    "XRPUSDT","SOLUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","NEARUSDT","ARBUSDT",
    "WIFUSDT","ORDIUSDT","1000SHIBUSDT","1000PEPEUSDT","JUPUSDT","TIAUSDT","SUIUSDT",
]

def fetch_klines(symbol, interval="1h", limit=72):
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

def get_altcoin_sentiment(all_klines_data, i):
    """获取山寨币整体情绪"""
    if i < 4:
        return "neutral", 0
    
    chg_4h_list = []
    chg_1h_list = []
    
    for coin, klines in all_klines_data.items():
        if len(klines) > i:
            c = [float(k[4]) for k in klines]
            if i >= 4 and c[i-4] > 0:
                chg_4h = (c[i] / c[i-4] - 1) * 100
                chg_4h_list.append(chg_4h)
            if i >= 1 and c[i-1] > 0:
                chg_1h = (c[i] / c[i-1] - 1) * 100
                chg_1h_list.append(chg_1h)
    
    if not chg_4h_list:
        return "neutral", 0
    
    avg_4h = sum(chg_4h_list) / len(chg_4h_list)
    avg_1h = sum(chg_1h_list) / len(chg_1h_list) if chg_1h_list else 0
    
    # 计算下跌币比例
    down_count = sum(1 for x in chg_4h_list if x < 0)
    down_ratio = down_count / len(chg_4h_list)
    
    # 山寨币情绪判断
    if avg_4h < -5 and down_ratio > 0.7:
        return "crash", avg_4h  # 山寨币崩盘
    elif avg_4h < -3 and down_ratio > 0.6:
        return "bear", avg_4h  # 山寨币熊市
    elif avg_4h < -1 and down_ratio > 0.5:
        return "weak", avg_4h  # 山寨币弱势
    elif avg_4h > 3 and down_ratio < 0.3:
        return "bull", avg_4h  # 山寨币牛市
    else:
        return "neutral", avg_4h

def sim(symbol, klines, all_klines_data, mode="no_filter"):
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
            
            # 山寨币情绪过滤
            alt_sentiment, alt_chg = get_altcoin_sentiment(all_klines_data, i)
            
            if mode == "no_filter":
                if score>=55:
                    pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                    peak=0; first_half_closed=False
            
            elif mode == "crash_filter":
                # 山寨币崩盘不开仓
                if alt_sentiment == "crash":
                    continue
                if score>=55:
                    pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                    peak=0; first_half_closed=False
            
            elif mode == "bear_filter":
                # 山寨币熊市不开仓
                if alt_sentiment in ["crash", "bear"]:
                    continue
                if score>=55:
                    pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                    peak=0; first_half_closed=False
            
            elif mode == "weak_filter":
                # 山寨币弱势不开仓
                if alt_sentiment in ["crash", "bear", "weak"]:
                    continue
                if score>=55:
                    pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                    peak=0; first_half_closed=False
            
            elif mode == "score_adjust":
                # 山寨币情绪调整评分
                if alt_sentiment == "crash":
                    score -= 30
                elif alt_sentiment == "bear":
                    score -= 20
                elif alt_sentiment == "weak":
                    score -= 10
                elif alt_sentiment == "bull":
                    score += 10
                
                if score>=55:
                    pos={"entry_price":closes[i],"entry_bar":i,"peak":0}
                    peak=0; first_half_closed=False
            
            elif mode == "combined":
                # 组合过滤: 山寨币熊市+大盘弱
                if alt_sentiment in ["crash", "bear"]:
                    continue
                if alt_sentiment == "weak" and score < 65:
                    continue
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
            if i-pos["entry_bar"]>=72:
                remaining=1.0 if not first_half_closed else 0.5
                trades.append({**pos,"exit_price":closes[i],"exit_bar":i,"pnl":pnl*100*remaining,"reason":"to"})
                pos=None; cooldown_until=i+2
    return trades

def stats(trades):
    if not trades: return {"n":0,"wr":0,"avg":0,"tot":0,"sl":0}
    wins=[t for t in trades if t["pnl"]>0]
    sl=sum(1 for t in trades if t.get("reason")=="sl")
    return {"n":len(trades),"wr":len(wins)/len(trades)*100,
        "avg":sum(t["pnl"] for t in trades)/len(trades),
        "tot":sum(t["pnl"] for t in trades),"sl":sl}

# 加载数据
print("加载数据...")
all_klines = {}
for coin in COINS:
    kl = fetch_klines(coin, "1h", 72)
    if kl and len(kl) >= 20:
        all_klines[coin] = kl
    time.sleep(0.1)

print(f"加载 {len(all_klines)} 个币")
print()

# 显示山寨币情绪
print("最近3天山寨币情绪:")
for i in range(10, 72):
    sentiment, avg_chg = get_altcoin_sentiment(all_klines, i)
    if i % 6 == 0:  # 每6小时显示一次
        print(f"  {i}: {sentiment:<8} 平均4h: {avg_chg:+.1f}%")
print()

# 测试不同过滤模式
modes = [
    ("no_filter", "无过滤"),
    ("crash_filter", "崩盘不开仓"),
    ("bear_filter", "熊市不开仓"),
    ("weak_filter", "弱势不开仓"),
    ("score_adjust", "情绪调整评分"),
    ("combined", "组合过滤"),
]

print(f"{'过滤模式':<15} {'交易':<6} {'胜率':<7} {'均PnL':<8} {'累计%':<9} {'止损':<5}")
print("-"*55)

for mode, name in modes:
    all_trades = []
    for coin, kl in all_klines.items():
        all_trades.extend(sim(coin, kl, all_klines, mode))
    s = stats(all_trades)
    print(f"{name:<15} {s['n']:<6} {s['wr']:<7.1f} {s['avg']:<8.1f} {s['tot']:<9.1f} {s['sl']:<5}")

print()
print("山寨币情绪说明:")
print("  崩盘: 平均4h跌>5%且70%币下跌")
print("  熊市: 平均4h跌>3%且60%币下跌")
print("  弱势: 平均4h跌>1%且50%币下跌")
print("  牛市: 平均4h涨>3%且70%币上涨")
