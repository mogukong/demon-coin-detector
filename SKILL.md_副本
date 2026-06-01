---
name: demon-coin-detector
description: 妖币猎手 - Binance期货量化交易机器人 (OI+Vol+SuperTrend+RSI+EV预估)
emoji: 👹
version: 3.1
author: miboy
---

# 妖币猎手 v3.1

全自动Binance期货交易机器人，基于多因子评分系统，严格风控，分批止盈。

## 策略核心

- **入场**: OI资金流 + 成交量 + SuperTrend趋势 + RSI分级 + EV预估
- **止损**: 物理止损单三层保护 + 利润锁定 + 动态评分离场
- **止盈**: 分批止盈(40%卖50%) + 追踪止盈(峰值回撤15%)
- **风控**: 仓位管理 + 日亏损限制 + 冷却机制

## 一键安装

### 1. 环境要求

```bash
# Python 3.9+
python3 --version

# 安装依赖 (无外部依赖，纯标准库)
# 无需安装任何包
```

### 2. 下载代码

```bash
cd ~/.hermes/skills/trading/
git clone https://github.com/YOUR_USERNAME/demon-coin-detector.git
cd demon-coin-detector
```

### 3. 配置API密钥

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env
```

填入你的Binance API密钥:

```env
# Binance API (必须开启期货权限)
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Telegram通知 (可选)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_PROXY=http://127.0.0.1:3067
```

### 4. 配置策略参数

```bash
# 编辑策略参数
nano strategy_params.json
```

默认参数(推荐):

```json
{
  "version": 13,
  "entry_score": 70,
  "stop_loss": 0.06,
  "sl_lock_trigger": 0.15,
  "sl_lock_target": 0.05,
  "score_exit": 55,
  "tp1_pct": 0.40,
  "tp1_sell": 0.50,
  "trail_activate": 0.10,
  "trail_drawdown": 0.15,
  "position_pct": 0.25,
  "max_positions": 3,
  "leverage": 10
}
```

### 5. 启动机器人

```bash
# 测试运行 (单次扫描)
python3 live_trader.py

# 查看状态
python3 live_trader.py --status

# 后台运行 (推荐)
python3 live_trader.py --loop

# 取消暂停
python3 live_trader.py --unpause
```

### 6. 使用Watchdog自动重启

```bash
# 启动watchdog (自动监控+重启)
python3 watchdog.py
```

## 策略参数说明

### 入场参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `entry_score` | 70 | 入场最低评分(0-130) |
| `position_pct` | 0.25 | 基础仓位比例(25%) |
| `max_positions` | 3 | 最大持仓数 |
| `leverage` | 10 | 杠杆倍数 |

### 止损参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `stop_loss` | 0.06 | 初始止损比例(6%) |
| `sl_lock_trigger` | 0.15 | 利润锁定触发点(15%) |
| `sl_lock_target` | 0.05 | 锁定的止损位置(5%) |
| `score_exit` | 55 | 评分低于此值离场 |

### 止盈参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `tp1_pct` | 0.40 | 第一批止盈触发点(40%) |
| `tp1_sell` | 0.50 | 第一批卖出比例(50%) |
| `trail_activate` | 0.10 | 追踪止盈启动点(10%) |
| `trail_drawdown` | 0.15 | 追踪止盈回撤幅度(15%) |

### RSI参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `rsi_period` | 14 | RSI周期 |
| `rsi_overbought` | 75 | RSI过热阈值 |
| `rsi_oversold` | 30 | RSI超卖阈值 |
| `rsi_warn` | 70 | RSI警告阈值 |
| `rsi_hot_pct` | 0.15 | RSI偏热仓位(15%) |
| `rsi_extreme_pct` | 0.10 | RSI过热仓位(10%) |

### 风控参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_hold_hours` | 168 | 最大持仓时间(7天) |
| `cooldown_hours` | 2 | 止损后冷却时间 |
| `daily_loss_limit` | 0.30 | 日亏损限制(30%) |
| `ev_threshold` | 0.01 | EV预估阈值(1%) |

## 评分系统

### 评分项 (满分130+)

| 指标 | 条件 | 分值 |
|------|------|------|
| OI 4h变化 | >8% / >4% / >0% | +25 / +15 / +8 |
| OI 1h变化 | >0.4% / >0% | +15 / +8 |
| OI连续上升 | ≥3次 / ≥2次 | +10 / +5 |
| 成交量比 | >2x / >1.4x | +15 / +10 |
| 成交量比(5h) | >2x / >1.5x | +10 / +5 |
| 4h涨幅 | >5% / >2% / >0% | +20 / +15 / +8 |
| 1h涨幅 | >0.5% / >0.2% / >0% | +15 / +10 / +5 |
| SuperTrend | 上升 / 下降 | +15 / -10 |
| RSI偏热 | 70-80 | -10 |

### 入场条件

1. 综合评分 ≥ 70
2. SuperTrend上升
3. RSI在30-80之间
4. 4h价格变化 > 0
5. EV预估 > 1%

## 仓位管理

### RSI分级仓位

| RSI | 仓位比例 | 说明 |
|-----|----------|------|
| <70 | 25% | 正常仓位 |
| 70-80 | 15% | RSI偏热，减仓 |
| >80 | 10% | 过热小仓试探 |

### 行情状态调整

| 状态 | 仓位倍数 | 止损倍数 | 说明 |
|------|----------|----------|------|
| trend | 1.0x | 1.0x | 正常趋势 |
| range | 0.8x | 0.8x | 震荡行情 |
| spike | 0.6x | 1.2x | 插针行情 |
| low_liquidity | 0.5x | 1.5x | 低流动性 |

## 止损策略

### 三层保护

```
第一层: 原生附带止损单 (开仓立即挂)
第二层: 补挂机制 (每次扫描验证)
第三层: 软件兜底 (代码强制平仓)
```

### 止损流程

```
开仓 → 止损-6%
  ↓
盈利15% → 止损移到+5% (锁定5%利润)
  ↓
盈利30% → 止损移到+5% (进一步保护)
```

## 止盈策略

### 分批止盈

```
浮盈+40% → 卖出50%仓位 (锁定利润)
  ↓
追踪止盈: 峰值10%启动, 回撤15%平仓
```

### 评分离场

```
评分跌破55 → 立即平仓 (动态风控)
```

## TG推送通知

### 推送事件

| 事件 | 消息格式 |
|------|----------|
| 🟢 开仓 | 币种 + 价格 + 评分 + RSI + 状态 + 止损 + 仓位 |
| 🔴 平仓/止损 | 币种 + 入场价 + 冷却时间 |
| 🎯 第一批止盈 | 币种 + 盈利% + 卖出比例 |
| 🎯 追踪止盈 | 币种 + 峰值 + 回撤 + PnL |
| 🔄 移动止损 | 币种 + 盈利% + 新止损价 |
| 📊 持仓报告 | 每小时推送所有持仓状态 |

### 配置Telegram

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_PROXY=http://127.0.0.1:3067
```

## 回测性能

### v3.1 优化版

| 指标 | 数值 |
|------|------|
| 累计收益 | 257.4% |
| 胜率 | 71.9% |
| 交易笔数 | 470 |
| 止损次数 | 133 |
| 效率 | 1.9 |

### 策略演进

| 版本 | 改进 | 收益 |
|------|------|------|
| v2.0 | 基础版 | +31.7% |
| v2.3 | SuperTrend过滤 | +87U |
| v2.5 | 分批止盈 | +222.9% |
| v2.6 | 4h过滤 | +66.4% |
| v2.7 | RSI分级仓位 | +91.9% |
| v3.0 | 高级框架 | +334.1% |
| v3.1 | 组合B优化 | +257.4% |

## 风险警告

⚠️ **高风险警告**

1. **杠杆交易**: 10倍杠杆意味着1%价格波动 = 10%盈亏
2. **止损保护**: 物理止损单可能因网络问题无法触发
3. **市场风险**: 极端行情可能导致滑点和穿仓
4. **技术风险**: API故障、网络中断可能影响交易
5. **资金风险**: 历史收益不代表未来表现

### 风险控制建议

1. **资金管理**: 只用闲置资金，不要借钱交易
2. **分散风险**: 不要投入全部资金，保留备用金
3. **监控运行**: 定期检查机器人状态
4. **及时止损**: 不要手动取消止损单
5. **持续优化**: 根据市场变化调整参数

## 文件结构

```
demon-coin-detector/
├── live_trader.py          # 主交易脚本
├── watchdog.py             # 自动重启监控
├── advanced_modules.py     # 高级模块
├── strategy_params.json    # 策略参数
├── live_state.json         # 运行状态
├── live_trades.json        # 交易记录
├── live_log.txt            # 运行日志
├── .env                    # API密钥 (不要提交)
├── .env.example            # 配置模板
├── SKILL.md                # 本文档
└── backtest/               # 回测脚本
```

## 常见问题

### Q: 如何修改止损比例?

A: 编辑 `strategy_params.json` 中的 `stop_loss` 参数 (默认0.06 = 6%)

### Q: 如何修改入场评分?

A: 编辑 `strategy_params.json` 中的 `entry_score` 参数 (默认70)

### Q: 如何查看当前状态?

A: 运行 `python3 live_trader.py --status`

### Q: 如何暂停交易?

A: 编辑 `live_state.json` 设置 `"paused": true`

### Q: 如何恢复交易?

A: 运行 `python3 live_trader.py --unpause`

### Q: 止损单没触发怎么办?

A: 机器人每次扫描会验证止损单，如果丢失会自动补挂

### Q: 如何更新到最新版本?

A: 
```bash
cd demon-coin-detector
git pull
# 重启机器人
pkill -f live_trader.py
python3 live_trader.py --loop
```

## 联系方式

- GitHub: https://github.com/YOUR_USERNAME/demon-coin-detector
- Issues: https://github.com/YOUR_USERNAME/demon-coin-detector/issues

## 免责声明

本软件仅供学习和研究使用。使用本软件进行交易的风险由用户自行承担。作者不对任何交易损失负责。

## 许可证

MIT License

---

**最后更新**: 2026-06-01
**版本**: v3.1
**作者**: miboy
