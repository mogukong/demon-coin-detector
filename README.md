# 👹 妖币猎手 v3.1

**全自动Binance期货量化交易机器人**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## ✨ 特性

- 🎯 **多因子评分系统** - OI资金流 + 成交量 + SuperTrend + RSI + EV预估
- 🛡️ **三层止损保护** - 物理止损单 + 补挂机制 + 软件兜底
- 💰 **分批止盈策略** - 40%止盈50% + 追踪止盈 + 评分离场
- 📊 **动态仓位管理** - RSI分级 + 行情状态调整
- 📱 **Telegram推送** - 实时通知开仓/平仓/止盈
- 🔄 **自动重启** - Watchdog监控，故障自动恢复

## 📈 回测表现

| 指标 | 数值 |
|------|------|
| 累计收益 | **257.4%** |
| 胜率 | **71.9%** |
| 交易笔数 | 470 |
| 止损次数 | 133 |
| 效率 | 1.9 |

## 🚀 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/demon-coin-detector.git
cd demon-coin-detector

# 运行安装脚本
bash install.sh
```

### 2. 配置

```bash
# 编辑API配置
nano .env
```

填入你的Binance API密钥:

```env
BINANCE_API_KEY=your_a...n### 3. 启动

```bash
# 测试运行
python3 live_trader.py

# 后台运行
python3 live_trader.py --loop

# 使用watchdog
python3 watchdog.py
```

## 📖 文档

详细使用说明请查看 [SKILL.md](SKILL.md)

## 📁 文件结构

```
demon-coin-detector/
├── live_trader.py          # 主交易脚本
├── watchdog.py             # 自动重启监控
├── advanced_modules.py     # 高级模块
├── strategy_params.json    # 策略参数
├── install.sh              # 安装脚本
├── .env.example            # 配置模板
├── SKILL.md                # 详细文档
└── README.md               # 本文件
```

## ⚙️ 策略参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| entry_score | 70 | 入场最低评分 |
| stop_loss | 0.06 | 初始止损(6%) |
| sl_lock_trigger | 0.15 | 利润锁定触发(15%) |
| tp1_pct | 0.40 | 第一批止盈(40%) |
| score_exit | 55 | 评分离场阈值 |

更多参数请查看 [strategy_params.json](strategy_params.json)

## 📱 Telegram通知

配置Telegram后，机器人会自动推送:

- 🟢 开仓通知
- 🔴 平仓/止损通知
- 🎯 止盈通知
- 📊 每小时持仓报告

## ⚠️ 风险警告

**高风险警告 - 期货交易可能导致本金损失**

1. 本软件仅供学习和研究使用
2. 10倍杠杆意味着1%价格波动 = 10%盈亏
3. 历史收益不代表未来表现
4. 请只用闲置资金交易
5. 使用前请充分了解风险

## 🤝 贡献

欢迎提交Issue和Pull Request!

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 🙏 致谢

- Binance API
- Python社区
- 所有贡献者

---

**作者**: miboy
**版本**: v3.1
**更新**: 2026-06-01
