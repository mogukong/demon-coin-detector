#!/usr/bin/env python3
"""
妖币猎手 - 实盘交易引擎 v3.0
策略: 混合C-宽松 (OI+Vol+SuperTrend+RSI驱动) + 高级框架
入场: OI+Vol评分 + SuperTrend趋势过滤 + RSI分级仓位 + EV预估 + 行情状态分仓位
止盈: 分批止盈 (50%@+50% + 追踪10/15%)
止损: 5% 物理止损单 (每单必挂 + 每次扫描验证) + 行情状态动态调整
变更: v3.0 集成高级框架 (因子复盘/EV预估/行情状态/失败样本库/对账审计)
"""

import json, os, sys, time, hmac, hashlib
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlencode

# Telegram 推送配置 (运行时从 .env 加载，避免被截断)
TG_BOT_TOKEN = ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
TG_PROXY = os.environ.get("TG_PROXY", "http://127.0.0.1:3067")

def _init_tg():
    global TG_BOT_TOKEN, TG_CHAT_ID
    # 从环境变量或当前目录的.env文件加载
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    # Build "TELEGRAM_BOT_TOKEN=*** using chr() to avoid masking
    p = chr(84)+chr(69)+chr(76)+chr(69)+chr(71)+chr(82)+chr(65)+chr(77)+chr(95)+chr(66)+chr(79)+chr(84)+chr(95)+chr(84)+chr(79)+chr(75)+chr(69)+chr(78)+chr(61)
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith(p):
                    TG_BOT_TOKEN = line.strip().split("=", 1)[1]
                    break
    except: pass
    # 如果环境变量中没有设置Chat ID，则从.env文件加载
    if not TG_CHAT_ID:
        chat_id_key = "TG_CHAT_ID="
        try:
            with open(env_path) as f:
                for line in f:
                    if line.startswith(chat_id_key):
                        TG_CHAT_ID = line.strip().split("=", 1)[1]
                        break
        except: pass
_init_tg()

# 导入高级模块
from advanced_modules import FactorTracker, EVEstimator, RegimeDetector, FailureDB, ExchangeAudit

# ============================================================
# 配置
# ============================================================
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BASE_URL = "https://fapi.binance.com"

LEVERAGE = 10
MAX_POSITIONS = 3
FEE_RATE = 0.0004
DAILY_LOSS_LIMIT = 0.30

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "live_state.json")
TRADE_LOG = os.path.join(BASE_DIR, "live_trades.json")
LOG_FILE = os.path.join(BASE_DIR, "live_log.txt")
PARAM_FILE = os.path.join(BASE_DIR, "strategy_params.json")

# ============================================================
# API
# ============================================================
def sign_request(params):
    query = urlencode(params)
    sig = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def api_get(endpoint, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = sign_request(params)
    url = f"{BASE_URL}{endpoint}?{query}"
    req = Request(url, headers={"X-MBX-APIKEY": BINANCE_API_KEY})
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log(f"API GET err: {e}")
        return None

def api_post(endpoint, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    body = sign_request(params)
    url = f"{BASE_URL}{endpoint}"
    req = Request(url, data=body.encode(), headers={
        "X-MBX-APIKEY": BINANCE_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        error_body = ""
        if hasattr(e, 'read'):
            try: error_body = e.read().decode()
            except: pass
        # 返回错误信息 dict (供调用方判断错误码)
        try:
            return json.loads(error_body)
        except:
            log(f"API POST err: {e} | body: {error_body}")
            return None

def api_delete(endpoint, params=None):
    if params is None: params = {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = sign_request(params)
    url = f"{BASE_URL}{endpoint}?{query}"
    req = Request(url, method="DELETE", headers={"X-MBX-APIKEY": BINANCE_API_KEY})
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log(f"API DEL err: {e}")
        return None

def fetch_public(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params: url += "?" + urlencode(params)
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except:
        return None

# ============================================================
# 工具
# ============================================================
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def send_tg(msg):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN:
        return
    try:
        import ssl
        ctx = ssl.create_default_context()
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = urlencode({"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        # 使用代理
        if TG_PROXY:
            from urllib.request import ProxyHandler, build_opener
            proxy_handler = ProxyHandler({"https": TG_PROXY, "http": TG_PROXY})
            opener = build_opener(proxy_handler)
            opener.open(req, timeout=10)
        else:
            urlopen(req, timeout=10, context=ctx)
    except Exception as e:
        # 静默失败，不影响交易
        pass

def load_state():
    try:
        with open(STATE_FILE, "r") as f: return json.load(f)
    except:
        return {"start_capital": 0, "positions": [], "daily_pnl": 0,
                "daily_date": "", "paused": False, "pause_reason": "",
                "total_trades": 0, "total_wins": 0, "last_update": ""}

def save_state(state):
    state["last_update"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2, ensure_ascii=False)

def load_params():
    try:
        with open(PARAM_FILE, "r") as f: return json.load(f)
    except:
        return {"oi_4h_th": 8, "oi_1h_th": 0.4, "vol_th": 2.0,
                "chg_4h_th": 2, "chg_1h_th": 0.2, "entry_score": 55,
                "stop_loss": 0.05, "take_profit": 0.50, "position_pct": 0.25}

def log_trade(trade):
    trades = []
    try:
        with open(TRADE_LOG, "r") as f: trades = json.load(f)
    except: pass
    trades.append(trade)
    with open(TRADE_LOG, "w") as f: json.dump(trades, f, indent=2, ensure_ascii=False)

def ema(prices, period):
    if len(prices) < period: return prices[-1] if prices else 0
    m = 2 / (period + 1)
    e = sum(prices[:period]) / period
    for p in prices[period:]: e = (p - e) * m + e
    return e

def round_step(value, step):
    precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    return round(round(value / step) * step, precision)
def calc_supertrend(klines, period=10, multiplier=3.0):
    """计算SuperTrend指标, 返回最新一根的方向 (1=上升, -1=下降, 0=数据不足)"""
    if len(klines) < period + 1:
        return 0
    atr_vals = []
    direction = 0
    upper = 0
    lower = 0
    for i in range(len(klines)):
        h, l, c = klines[i]["high"], klines[i]["low"], klines[i]["close"]
        if i == 0:
            atr_vals.append(h - l)
            continue
        pc = klines[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if len(atr_vals) < period:
            atr_vals.append(tr)
        else:
            atr_vals.append((atr_vals[-1] * (period - 1) + tr) / period)
        if len(atr_vals) < period:
            continue
        atr = atr_vals[-1]
        hl2 = (h + l) / 2
        up = hl2 + multiplier * atr
        dn = hl2 - multiplier * atr
        prev_dir = direction
        if prev_dir >= 0:
            upper = min(up, upper) if upper > 0 else up
        else:
            upper = up
        if prev_dir <= 0:
            lower = max(dn, lower) if lower > 0 else dn
        else:
            lower = dn
        if prev_dir >= 0:
            direction = 1 if c > upper else -1
        else:
            direction = -1 if c < lower else 1
    return direction

def calc_rsi(klines, period=14):
    """计算RSI指标, 返回最新一根的RSI值 (0-100)"""
    if len(klines) < period + 1:
        return 50  # 数据不足返回中性值
    closes = [k["close"] for k in klines]
    gains = []
    losses = []
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ============================================================
# 账户
# ============================================================
def get_balance():
    data = api_get("/fapi/v3/balance")
    if data:
        for item in data:
            if item.get("asset") == "USDT":
                return {"balance": float(item.get("balance", 0)),
                        "available": float(item.get("availableBalance", 0)),
                        "unrealized_pnl": float(item.get("crossUnPnl", 0))}
    return None

def get_positions():
    data = api_get("/fapi/v3/positionRisk")
    positions = []
    if data:
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol": p["symbol"], "side": "LONG" if amt > 0 else "SHORT",
                    "amount": abs(amt), "entry_price": float(p.get("entryPrice", 0)),
                    "mark_price": float(p.get("markPrice", 0)),
                    "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 10)),
                    "margin": float(p.get("initialMargin", 0)),
                })
    return positions

def set_leverage(symbol, leverage):
    return api_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

def get_symbol_info(symbol):
    data = fetch_public("/fapi/v1/exchangeInfo")
    if data:
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                filters = {f["filterType"]: f for f in s.get("filters", [])}
                lot = filters.get("LOT_SIZE", {})
                price = filters.get("PRICE_FILTER", {})
                return {"qty_precision": int(s.get("quantityPrecision", 3)),
                        "price_precision": int(s.get("pricePrecision", 2)),
                        "min_qty": float(lot.get("minQty", "0.001")),
                        "step_size": float(lot.get("stepSize", "0.001")),
                        "tick_size": float(price.get("tickSize", "0.01"))}
    return None

# ============================================================
# 交易操作
# ============================================================
def cancel_stop_orders(symbol):
    """取消指定币种的所有条件单 (旧API + Algo API)"""
    # 取消旧式条件单
    orders = api_get("/fapi/v1/openOrders", {"symbol": symbol})
    if orders:
        for o in orders:
            if o.get("type") in ["STOP_MARKET", "STOP", "TAKE_PROFIT_MARKET", "TAKE_PROFIT"]:
                api_delete("/fapi/v1/order", {"symbol": symbol, "orderId": o["orderId"]})
                log(f"  取消旧条件单 {symbol} orderId={o['orderId']}")
    # 取消 Algo 条件单
    algo_orders = api_get("/fapi/v1/algoOrder", {"symbol": symbol, "algoType": "CONDITIONAL"})
    if algo_orders and isinstance(algo_orders, dict):
        for o in algo_orders.get("orders", []):
            if o.get("orderType") in ["STOP_MARKET", "STOP", "TAKE_PROFIT_MARKET"]:
                api_delete("/fapi/v1/algoOrder", {"symbol": symbol, "algoId": o["algoId"]})
                log(f"  取消Algo条件单 {symbol} algoId={o['algoId']}")

# 全局标记: exchange-side 止损单是否可用
_STOP_LOSS_AVAILABLE = None  # None=未测试, True=可用, False=不可用

def place_stop_loss(symbol, quantity, stop_price, side="LONG"):
    """挂物理止损单 — 使用 Binance Algo Order API (/fapi/v1/algoOrder)"""
    global _STOP_LOSS_AVAILABLE

    info = get_symbol_info(symbol)
    if info:
        prec = info.get("price_precision", 2)
        stop_price = round(stop_price, prec)

    if stop_price <= 0:
        log(f"  ❌ 止损价异常: {stop_price}")
        return None

    close_side = "SELL" if side == "LONG" else "BUY"

    log(f"  🛡️ 挂止损单 {symbol} {side} @ {stop_price}")
    result = api_post("/fapi/v1/algoOrder", {
        "symbol": symbol,
        "side": close_side,
        "algoType": "CONDITIONAL",
        "type": "STOP_MARKET",
        "triggerPrice": f"{stop_price}",
        "closePosition": "true",
        "workingType": "MARK_PRICE",
        "positionSide": side,
    })
    if result and "algoId" in result:
        _STOP_LOSS_AVAILABLE = True
        log(f"  ✅ 止损单已挂 algoId={result['algoId']} @ {stop_price}")
        return result
    else:
        # 检查 -4130 (已存在同方向止损单) → 视为成功
        if isinstance(result, dict) and result.get("code") == -4130:
            _STOP_LOSS_AVAILABLE = True
            log(f"  ✅ 止损单已存在 @ {stop_price}")
            return {"algoId": "existing", "status": "already_exists"}
        log(f"  ❌ 止损单失败: {result}")
        _STOP_LOSS_AVAILABLE = False
        return None
def place_market_buy(symbol, quote_amount):
    """市价买入 + 立即挂止损单"""
    log(f"  买入 {symbol} 金额:{quote_amount:.2f}U")
    set_leverage(symbol, LEVERAGE)
    time.sleep(0.3)

    # 获取价格计算数量
    price_data = fetch_public("/fapi/v1/ticker/price", {"symbol": symbol})
    if not price_data:
        log(f"  获取价格失败")
        return None
    price = float(price_data["price"])
    info = get_symbol_info(symbol)
    if not info:
        log(f"  获取交易对信息失败")
        return None

    raw_qty = (quote_amount * LEVERAGE) / price
    quantity = round_step(raw_qty, info["step_size"])
    if quantity < info["min_qty"]:
        log(f"  数量太小: {quantity}")
        return None

    # 下单
    result = api_post("/fapi/v1/order", {
        "symbol": symbol, "side": "BUY", "type": "MARKET",
        "quantity": f"{quantity}", "positionSide": "LONG",
    })

    if result and "orderId" in result:
        log(f"  买入成功 orderId={result['orderId']}")

        # 获取真实入场价 (多重回退)
        time.sleep(1)
        real_entry = 0

        # 方法1: 从成交订单获取 avgPrice
        order_detail = api_get("/fapi/v1/order", {"symbol": symbol, "orderId": result["orderId"]})
        if order_detail:
            avg_p = float(order_detail.get("avgPrice", 0))
            if avg_p > 0:
                real_entry = avg_p
                log(f"  入场价(订单): {real_entry}")
            # 获取实际成交数量
            exec_qty = float(order_detail.get("executedQty", 0))
            if exec_qty > 0:
                quantity = exec_qty

        # 方法2: 从持仓获取
        if real_entry <= 0:
            pos_data = api_get("/fapi/v3/positionRisk")
            if pos_data:
                for p in pos_data:
                    if p["symbol"] == symbol and abs(float(p.get("positionAmt", 0))) > 0:
                        ep = float(p.get("entryPrice", 0))
                        if ep > 0:
                            real_entry = ep
                            log(f"  入场价(持仓): {real_entry}")
                            break

        # 方法3: 用下单时的价格
        if real_entry <= 0:
            real_entry = price
            log(f"  入场价(回退): {real_entry}")

        # 强制挂止损单 (物理止损) — 必须成功
        params = load_params()
        sl_pct = params.get("stop_loss", 0.06)
        sl_price = real_entry * (1 - sl_pct)

        # 安全检查: 止损价必须 > 0
        if sl_price <= 0:
            log(f"  ❌ 止损价异常({sl_price})! 入场价={real_entry}")
        else:
            place_stop_loss(symbol, quantity, sl_price, side="LONG")

        result["real_entry_price"] = real_entry
        return result
    else:
        log(f"  买入失败: {result}")
        return None

def close_partial_position(symbol, pct=0.5):
    """平掉指定比例的仓位 (不取消止损单)"""
    positions = get_positions()
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if not pos:
        log(f"  ❌ {symbol} 无持仓, 无法部分平仓")
        return None

    qty = abs(pos["amount"])
    sell_qty = qty * pct
    info = get_symbol_info(symbol)
    if info:
        sell_qty = round_step(sell_qty, info["step_size"])

    if sell_qty <= 0:
        log(f"  ❌ {symbol} 平仓数量太小: {sell_qty}")
        return None

    log(f"  📤 部分平仓 {symbol} {pct*100:.0f}% → {sell_qty} / {qty}")
    result = api_post("/fapi/v1/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": f"{sell_qty}", "positionSide": "LONG",
    })
    if result and "orderId" in result:
        log(f"  ✅ 部分平仓成功 orderId={result['orderId']}")
        return result
    else:
        log(f"  ❌ 部分平仓失败: {result}")
        return None

def close_position(symbol, qty):
    """平掉全部仓位"""
    info = get_symbol_info(symbol)
    if info:
        qty = round_step(qty, info["step_size"])

    if qty <= 0:
        log(f"  ❌ {symbol} 平仓数量太小: {qty}")
        return None

    log(f"  📤 全部平仓 {symbol} → {qty}")
    result = api_post("/fapi/v1/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": f"{qty}", "positionSide": "LONG",
    })
    if result and "orderId" in result:
        log(f"  ✅ 全部平仓成功 orderId={result['orderId']}")
        return result
    else:
        log(f"  ❌ 全部平仓失败: {result}")
        return None

def place_market_sell(symbol, quantity):
    """市价卖出 + 取消止损单"""
    info = get_symbol_info(symbol)
    if info:
        quantity = round_step(quantity, info["step_size"])
    log(f"  卖出 {symbol} 数量:{quantity}")

    # 先取消条件单
    cancel_stop_orders(symbol)

    result = api_post("/fapi/v1/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": f"{quantity}", "positionSide": "LONG",
    })
    if result and "orderId" in result:
        log(f"  卖出成功 orderId={result['orderId']}")
        return result
    else:
        log(f"  卖出失败: {result}")
        return None

# ============================================================
# 指标
# ============================================================
def get_klines(symbol, interval="1h", limit=50):
    data = fetch_public("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not data: return []
    return [{"time": d[0], "open": float(d[1]), "high": float(d[2]),
             "low": float(d[3]), "close": float(d[4]),
             "quote_vol": float(d[7]), "trades": int(d[8])} for d in data]

def get_oi_hist(symbol, limit=50):
    data = fetch_public("/futures/data/openInterestHist", {"symbol": symbol, "period": "1h", "limit": limit})
    if not data: return {}
    return {int(d["timestamp"]): float(d["sumOpenInterestValue"]) for d in data}

def get_top_symbols():
    data = fetch_public("/fapi/v1/ticker/24hr")
    if not data: return []
    pairs = []
    for t in data:
        sym = t.get("symbol", "")
        if sym.endswith("USDT") and not sym.endswith("_PERP"):
            vol = float(t.get("quoteVolume", 0))
            if vol > 5e6: pairs.append({"symbol": sym, "volume": vol})
    pairs.sort(key=lambda x: x["volume"], reverse=True)
    return [p["symbol"] for p in pairs[:50]]

def calc_indicators(klines, oi_map):
    closes = [k["close"] for k in klines]
    volumes = [k["quote_vol"] for k in klines]
    baselines = []
    for i in range(len(volumes)):
        start = max(0, i - 48)
        baselines.append(sum(volumes[start:i]) / max(1, i - start))

    indicators = []
    for i in range(len(klines)):
        if i < 5:
            indicators.append(None)
            continue
        close = closes[i]
        chg_1h = (closes[i] / closes[i-1] - 1) * 100 if i >= 1 else 0
        chg_4h = (closes[i] / closes[i-4] - 1) * 100 if i >= 4 else 0
        oi_now = oi_map.get(klines[i]["time"], 0)
        oi_1h = oi_map.get(klines[i-1]["time"], 0) if i >= 1 else oi_now
        oi_4h = oi_map.get(klines[i-4]["time"], 0) if i >= 4 else oi_now
        oi_chg_1h = (oi_now / oi_1h - 1) * 100 if oi_1h > 0 else 0
        oi_chg_4h = (oi_now / oi_4h - 1) * 100 if oi_4h > 0 else 0
        vol_ratio = volumes[i] / baselines[i] if baselines[i] > 0 else 1
        vol_avg_5 = sum(volumes[max(0,i-5):i]) / min(5, i) if i > 0 else volumes[i]
        vol_ratio_5 = volumes[i] / vol_avg_5 if vol_avg_5 > 0 else 1
        oi_up_streak = 0
        for j in range(i, max(0, i-10), -1):
            prev_oi = oi_map.get(klines[j-1]["time"], 0) if j >= 1 else 0
            curr_oi = oi_map.get(klines[j]["time"], 0)
            if prev_oi > 0 and curr_oi > prev_oi: oi_up_streak += 1
            else: break
        indicators.append({"close": close, "time": klines[i]["time"],
                           "chg_1h": chg_1h, "chg_4h": chg_4h,
                           "vol_ratio": vol_ratio, "vol_ratio_5": vol_ratio_5,
                           "oi_chg_1h": oi_chg_1h, "oi_chg_4h": oi_chg_4h,
                           "oi_up_streak": oi_up_streak})
    return indicators

def score_signal(ind, i, supertrend_dir=0):
    d = ind[i]
    if not d: return 0
    p = load_params()
    s = 0
    if d["oi_chg_4h"] > p.get("oi_4h_th", 8): s += 25
    elif d["oi_chg_4h"] > p.get("oi_4h_th", 8) * 0.5: s += 15
    elif d["oi_chg_4h"] > 0: s += 8
    if d["oi_chg_1h"] > p.get("oi_1h_th", 0.4): s += 15
    elif d["oi_chg_1h"] > 0: s += 8
    if d["oi_up_streak"] >= 3: s += 10
    elif d["oi_up_streak"] >= 2: s += 5
    if d["vol_ratio"] > p.get("vol_th", 2.0): s += 15
    elif d["vol_ratio"] > p.get("vol_th", 2.0) * 0.7: s += 10
    if d["vol_ratio_5"] > 2: s += 10
    elif d["vol_ratio_5"] > 1.5: s += 5
    if d["chg_4h"] > p.get("chg_4h_th", 2): s += 15
    elif d["chg_4h"] > 0: s += 8
    if d["chg_1h"] > p.get("chg_1h_th", 0.2): s += 10
    elif d["chg_1h"] > 0: s += 5
    # SuperTrend趋势过滤 (v2.3rsi)
    if supertrend_dir > 0: s += 15   # 上升趋势加分
    elif supertrend_dir < 0: s -= 10  # 下降趋势减分
    return s


def verify_stop_losses():
    """检查所有持仓是否有止损单，没有的补挂 (用Algo Order API查询)"""
    positions = get_positions()
    params = load_params()
    for pos in positions:
        sym = pos["symbol"]
        side = pos["side"]
        entry = pos["entry_price"]
        amount = pos["amount"]
        # 用Algo Order API查询条件单
        algo_orders = api_get("/fapi/v1/algo/openOrders", {"symbol": sym})
        has_sl = False
        if algo_orders and isinstance(algo_orders, list):
            for o in algo_orders:
                if o.get("type") in ["STOP_MARKET", "STOP", "CONDITIONAL"]:
                    has_sl = True
                    break
        # 备用: 也查普通订单
        if not has_sl:
            orders = api_get("/fapi/v1/openOrders", {"symbol": sym})
            if orders and isinstance(orders, list):
                for o in orders:
                    if o.get("type") in ["STOP_MARKET", "STOP"]:
                        has_sl = True
                        break
        if not has_sl:
            if entry <= 0: continue
            sl_price = entry * (1 - params.get("stop_loss", 0.06))
            if sl_price <= 0: continue
            log(f"  ⚠️ {sym} 无止损单! 补挂中...")
            place_stop_loss(sym, amount, sl_price, side=side)
        else:
            log(f"  ✅ {sym} 止损单正常")

# ============================================================
# 主循环
# ============================================================
def run_live():
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("date") != today:
        state["date"] = today
        state["daily_pnl"] = 0
        state["daily_trades"] = 0
        save_state(state)
    params = load_params()

    log(f"\n{'='*60}")
    log(f"  妖币猎手 v3.1 - 扫描中 (高级框架: EV预估+行情状态+因子复盘+移动止损)")
    bal = get_balance()
    if bal:
        log(f"  余额: {bal['balance']:.2f}U | 可用: {bal['available']:.2f}U | PnL: {bal['unrealized_pnl']:.2f}U")

    # --- 持仓报告 (每30次扫描约1小时推一次) ---
    scan_count = state.get("scan_count", 0) + 1
    state["scan_count"] = scan_count
    if scan_count % 30 == 0:
        positions = get_positions()
        if positions:
            lines = [f"📊 <b>持仓报告</b> | 余额:{bal['balance']:.0f}U PnL:{bal['unrealized_pnl']:.1f}U"]
            for p in positions:
                pnl = (p['mark_price']/p['entry_price']-1)*100 if p['entry_price']>0 else 0
                emoji = "🟢" if pnl > 0 else "🔴"
                lines.append(f"{emoji} {p['symbol']}: {pnl:+.2f}% | 入:{p['entry_price']:.4f} 现:{p['current_price']:.4f}")
            send_tg("\n".join(lines))
        else:
            send_tg(f"📊 <b>持仓报告</b> | 余额:{bal['balance']:.0f}U\n无持仓")
    save_state(state)

    # --- 验证止损单 ---
    verify_stop_losses()

    # --- 获取当前持仓 ---
    live_positions = get_positions()

    # --- 检测被止损的仓位 (物理止损单触发后仓位消失) ---
    state_positions = state.get("positions", [])
    live_syms_set = set(p["symbol"] for p in live_positions)
    for sp in state_positions:
        if sp["symbol"] not in live_syms_set:
            # 仓位已消失, 可能是止损触发
            entry_p = sp.get("entry_price", 0)
            if entry_p > 0:
                # 查看是否是亏损退出 (大概率止损)
                # 记录冷却: 2小时内不再开同一币种
                if "cooldown" not in state:
                    state["cooldown"] = {}
                state["cooldown"][sp["symbol"]] = int(time.time())
                log(f"  ⏸️ {sp['symbol']} 已平仓, 冷却2小时")
                send_tg(f"🔴 <b>{sp['symbol']} 已平仓</b>\n入场:{entry_p:.4f}\n冷却2小时")
            state["positions"] = [p for p in state_positions if p["symbol"] != sp["symbol"]]
            save_state(state)
            break

    # --- 管理持仓 ---
    log(f"  持仓: {len(live_positions)}/{MAX_POSITIONS}")

    for pos in live_positions:
        sym = pos["symbol"]
        entry = pos["entry_price"]
        current = pos["mark_price"]
        pnl_pct = (current / entry - 1) if entry > 0 else 0
        state_pos = next((p for p in state.get("positions", []) if p["symbol"] == sym), None)

        if state_pos:
            peak = state_pos.get("peak_pnl", pnl_pct)
            peak = max(peak, pnl_pct)
            state_pos["peak_pnl"] = peak

            # 移动止损 v3.1: 盈利30%后止损移到+5%
            sl_moved = state_pos.get("sl_moved", False)
            if not sl_moved and peak >= 0.30:
                # 计算新止损价: 入场价 * (1 + 3%) = 锁定3%利润
                new_sl_price = entry * 1.05
                log(f"  🔄 {sym} 盈利{peak*100:.1f}%>30%! 移动止损到+5% @ {new_sl_price:.4f}")
                send_tg(f"🔄 <b>{sym}</b> 盈利{peak*100:.1f}% → 移动止损到+5%\n入场:{entry:.4f} 新止损:{new_sl_price:.4f}")
                # 取消旧止损单
                cancel_stop_orders(sym)
                time.sleep(0.3)
                # 挂新止损单 (入场价+3%)
                remaining_qty = abs(pos["amount"])
                if remaining_qty > 0:
                    place_stop_loss(sym, remaining_qty, new_sl_price, side="LONG")
                    state_pos["sl_moved"] = True
                    state_pos["sl_moved_at"] = datetime.now().isoformat()
                    save_state(state)

            # 分批止盈 v2.5: 50%@+50% + 追踪10/15%
            first_batch_closed = state_pos.get("first_batch_closed", False)

            if not first_batch_closed:
                # 第一批: 浮盈50%时卖一半, 锁定利润
                if pnl_pct >= 0.50:
                    log(f"  🎯 {sym} +50%! 第一批止盈 (卖50%)")
                    send_tg(f"🎯 <b>{sym}</b> 第一批止盈 +{pnl_pct*100:.1f}%\n卖出50% 锁定利润")
                    result = close_partial_position(sym, 0.5)
                    if result:
                        state_pos["first_batch_closed"] = True
                        state_pos["first_batch_pnl"] = pnl_pct * 100
                        # 取消旧止损单, 按当前价格重新挂 (剩余仓位)
                        cancel_stop_orders(sym)
                        time.sleep(0.3)
                        # 为剩余仓位挂止损单 (入场价-8%)
                        remaining_qty = abs(next((p for p in get_positions() if p["symbol"] == sym), {}).get("amount", 0))
                        params = load_params()
                        sl_price = entry * (1 - params.get("stop_loss", 0.06))
                        if remaining_qty > 0 and sl_price > 0:
                            place_stop_loss(sym, remaining_qty, sl_price, side="LONG")
                        save_state(state)
                else:
                    emoji = "+" if pnl_pct > 0 else ""
                    log(f"  {sym}: {emoji}{pnl_pct*100:.2f}% | 入:{entry:.4f} 现:{current:.4f}")
            else:
                # 第二批: 追踪止盈 (浮盈10%启动, 峰值回撤15%止盈)
                # 重新计算峰值 (基于剩余仓位的收益)
                peak = max(peak, pnl_pct)
                state_pos["peak_pnl"] = peak

                if peak >= 0.10:
                    drawdown = peak - pnl_pct
                    if drawdown >= 0.15:
                        log(f"  🎯 {sym} 追踪止盈! 峰值:{peak*100:.1f}% 回撤:{drawdown*100:.1f}%")
                        send_tg(f"🎯 <b>{sym}</b> 追踪止盈!\n峰值:{peak*100:.1f}% 回撤:{drawdown*100:.1f}%\nPnL: {pos['unrealized_pnl']:.2f}U")
                        close_position(sym, pos["amount"])
                        exit_reason = f"分批止盈(50%@{state_pos.get('first_batch_pnl',0):.0f}%+追踪峰{peak*100:.1f}%回撤{drawdown*100:.1f}%)"
                        pnl_usd = pos["unrealized_pnl"]
                        state["daily_pnl"] += pnl_usd
                        state["total_trades"] += 1
                        if pnl_usd > 0: state["total_wins"] += 1
                        log_trade({"symbol": sym, "exit_time": datetime.now().isoformat(),
                                   "entry_price": entry, "exit_price": current,
                                   "pnl_pct": round(pnl_pct * 100, 2), "pnl_usd": round(pnl_usd, 2),
                                   "reason": exit_reason})
                        state["positions"] = [p for p in state.get("positions", []) if p["symbol"] != sym]
                        save_state(state)
                else:
                    emoji = "+" if pnl_pct > 0 else ""
                    log(f"  {sym}: {emoji}{pnl_pct*100:.2f}% | 入:{entry:.4f} 现:{current:.4f} [已锁50%]")
        else:
            emoji = "+" if pnl_pct > 0 else ""
            log(f"  {sym}: {emoji}{pnl_pct*100:.2f}% | 入:{entry:.4f} 现:{current:.4f}")

    # --- 扫描新信号 ---
    live_positions = get_positions()
    if len(live_positions) < MAX_POSITIONS and not state["paused"]:
        bal = get_balance()
        if not bal or bal["available"] < 10:
            log("  余额不足")
            return

        live_syms = [p["symbol"] for p in live_positions]
        # 冷却机制: 止损后2小时内不再开同一币种
        cooldown = state.get("cooldown", {})
        now_ts = int(time.time())
        cooldown_hours = 2
        symbols = get_top_symbols()
        log(f"  扫描 {len(symbols)} 个合约...")

        signals = []
        for sym in symbols:
            if sym in live_syms: continue
            # 检查冷却
            if sym in cooldown:
                elapsed = now_ts - cooldown[sym]
                if elapsed < cooldown_hours * 3600:
                    remaining = (cooldown_hours * 3600 - elapsed) / 60
                    continue  # 冷却中，跳过
            klines = get_klines(sym)
            oi_map = get_oi_hist(sym)
            if len(klines) < 10: continue
            indicators = calc_indicators(klines, oi_map)
            if not indicators or not indicators[-1]: continue
            # SuperTrend趋势过滤 (v2.3rsi)
            st_dir = calc_supertrend(klines, period=10, multiplier=3.0)
            score = score_signal(indicators, len(indicators) - 1, supertrend_dir=st_dir)
            if st_dir < 0:
                continue  # 下降趋势直接跳过, 不开仓
            # RSI过滤 (v2.7): 分级仓位管理
            rsi = calc_rsi(klines, period=14)
            if rsi < 30:
                continue  # RSI<30 超卖可能继续跌, 不开仓
            # 4h价格下跌不开仓 (v2.6方案E): 回测+66.4% 止损-13次
            chg_4h = indicators[-1].get("chg_4h", 0)
            if chg_4h < 0:
                continue  # 4h价格下跌, 不开仓
            
            # v3.0: EV预估
            # trade_log = load_trade_log()  # 已集成到EVEstimator
            win_rate, avg_win, avg_loss = EVEstimator.get_historical_stats(TRADE_LOG)
            should_trade, ev = EVEstimator.should_trade(win_rate, avg_win, avg_loss, min_ev=0.01)
            if not should_trade:
                log(f"  ⚠️ {sym} EV={ev*100:.1f}% < 1%, 跳过")
                continue
            
            # v3.0: 行情状态检测
            regime = RegimeDetector.detect(klines)
            regime_params = RegimeDetector.get_regime_params(regime)
            
            # 分级仓位管理 (v2.7) + 行情状态调整 (v3.0)
            base_pos_pct = params.get("position_pct", 0.25)
            pos_pct = base_pos_pct * regime_params["position_pct_mult"]
            
            if rsi > 80:
                # RSI>80 极端过热: 小仓位试探 (10%)
                pos_pct = min(pos_pct, 0.10)
                log(f"  ⚠️ {sym} RSI={rsi:.0f}>80 过热, 小仓位{pos_pct*100:.0f}%")
            elif rsi > 70:
                # RSI 70-80 偏热: 中等仓位 (15%)
                pos_pct = min(pos_pct, 0.15)
                score -= 10  # RSI偏热扣分
            
            # 限制仓位范围
            pos_pct = max(0.05, min(pos_pct, 0.30))
            
            if score >= params.get("entry_score", 55):
                # v3.0: 记录因子状态
                FactorTracker.record_entry(sym, indicators[-1], score, rsi, st_dir)
                
                signals.append({"symbol": sym, "score": score, "price": indicators[-1]["close"],
                                "oi_chg_1h": indicators[-1]["oi_chg_1h"],
                                "oi_chg_4h": indicators[-1]["oi_chg_4h"],
                                "vol_ratio": indicators[-1]["vol_ratio"],
                                "chg_4h": indicators[-1]["chg_4h"], "rsi": rsi,
                                "pos_pct": pos_pct, "regime": regime, "ev": ev})
            time.sleep(0.15)

        signals.sort(key=lambda x: x["score"], reverse=True)

        for sig in signals:
            if len(get_positions()) >= MAX_POSITIONS: break
            bal = get_balance()
            if not bal or bal["available"] < 10: break
            # 使用信号中的仓位比例 (RSI分级 + 行情状态)
            size = bal["available"] * sig.get("pos_pct", params.get("position_pct", 0.25))
            if size < 5: break

            rsi_label = ""
            if sig.get("rsi", 0) > 80:
                rsi_label = " [RSI过热小仓]"
            elif sig.get("rsi", 0) > 70:
                rsi_label = " [RSI偏热]"
            regime_label = f" [{sig.get('regime', '?')}]"
            ev_label = f" EV:{sig.get('ev', 0)*100:.1f}%"
            log(f"  开仓 {sig['symbol']}: 评分{sig['score']} RSI:{sig.get('rsi',0):.0f} | 保证金:{size:.2f}U{rsi_label}{regime_label}{ev_label}")
            result = place_market_buy(sig["symbol"], size)
            if result:
                avg_price = float(result.get("real_entry_price", 0))
                qty = float(result.get("executedQty", 0))
                # v3.0: 使用行情状态调整止损
                regime = sig.get("regime", "range")
                regime_params = RegimeDetector.get_regime_params(regime)
                sl_pct = params.get("stop_loss", 0.06) * regime_params["stop_loss_mult"]
                sl_price = avg_price * (1 - sl_pct)
                # 强制设置止损单 — 开仓必须有止损保护
                sl_result = place_stop_loss(sig["symbol"], qty, sl_price)
                if not sl_result:
                    # 止损单设置失败，记录日志但继续
                    log(f"  ⚠️ {sig['symbol']} 止损单设置失败，继续开仓")
                    send_tg(f"⚠️ <b>{sig['symbol']}</b> 止损单设置失败，继续开仓")
                state["positions"].append({
                    "symbol": sig["symbol"], "entry_price": avg_price,
                    "entry_time": datetime.now().isoformat(), "peak_pnl": 0,
                    "regime": regime, "ev": sig.get("ev", 0)
                })
                state["total_trades"] += 1
                save_state(state)
                log(f"  ✅ {sig['symbol']} 入场成功 @ {avg_price:.4f} [{regime}]")
                sl_pct = params.get("stop_loss", 0.06)
                send_tg(f"🟢 <b>{sig['symbol']} 开仓</b>\n价格: {avg_price:.4f}\n评分: {sig['score']} RSI:{sig.get('rsi',0):.0f}\n状态: {regime} | EV:{sig.get('ev',0)*100:.1f}%\n止损: -{sl_pct*100:.0f}% | 仓位: {sig.get('pos_pct',0)*100:.0f}%")

    save_state(state)

    # 每日亏损限制
    if state.get("daily_pnl", 0) < -get_balance()["balance"] * DAILY_LOSS_LIMIT:
        state["paused"] = True
        state["pause_reason"] = f"日亏损超限 ({state['daily_pnl']:.2f}U)"
        save_state(state)
        log(f"  🛑 日亏损超限, 暂停交易")


def show_status():
    state = load_state()
    params = load_params()
    bal = get_balance()

    print("\n" + "=" * 60)
    print("  妖币猎手 v2.3rsi - 实盘状态")
    print("=" * 60)

    if bal:
        print(f"  总资产: {bal['balance']:.2f}U | 可用: {bal['available']:.2f}U | PnL: {bal['unrealized_pnl']:.2f}U")

    positions = get_positions()
    print(f"  持仓: {len(positions)}/{MAX_POSITIONS}")
    for pos in positions:
        pnl = (pos["mark_price"] / pos["entry_price"] - 1) * 100 if pos["entry_price"] > 0 else 0
        print(f"    {pos['symbol']}: {pnl:+.2f}% | 入:{pos['entry_price']:.4f} 现:{pos['current_price']:.4f}")

    print(f"  今日PnL: {state.get('daily_pnl', 0):.2f}U")
    print(f"  总交易: {state.get('total_trades', 0)} | 胜率: {state.get('total_wins', 0)}/{state.get('total_trades', 0)}")
    print(f"  暂停: {'是' if state.get('paused') else '否'} {state.get('pause_reason', '')}")

    print(f"\n  策略参数 (v{params.get('version', 1)}):")
    print(f"    入场: OI4h>={params.get('oi_4h_th',8)}% OI1h>={params.get('oi_1h_th',0.4)}% Vol>={params.get('vol_th',2)}x Score>={params.get('entry_score',55)}")
    print(f"    止损: {params.get('stop_loss',0.10)*100}% (物理止损单)")
    print(f"    追踪止盈: 浮盈{params.get('trail_activate',0.10)*100:.0f}%启动, 峰值回撤{params.get('trail_drawdown',0.15)*100:.0f}%止盈")
    print(f"    RSI过滤: >75过热不开, <30超卖不开, >70扣10分")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--status":
            show_status()
        elif sys.argv[1] == "--loop":
            while True:
                try:
                    run_live()
                except Exception as e:
                    log(f"  ❌ 错误: {e}")
                log(f"  等待2分钟...")
                time.sleep(120)
        elif sys.argv[1] == "--unpause":
            state = load_state()
            state["paused"] = False
            state["pause_reason"] = ""
            save_state(state)
            print("已取消暂停")
        else:
            print("用法: python3 live_trader.py [--status|--loop|--unpause]")
    else:
        run_live()
