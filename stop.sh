#!/bin/bash
# 妖币猎手 - 停止脚本
echo "🛑 停止妖币猎手..."

# 停止看门狗
pkill -f "watchdog.py" 2>/dev/null && echo "  ✅ 看门狗已停止" || echo "  ⚪ 看门狗未运行"

# 停止交易引擎
pkill -f "live_trader.py --loop" 2>/dev/null && echo "  ✅ 交易引擎已停止" || echo "  ⚪ 交易引擎未运行"

# 清理 PID 文件
rm -f watchdog.pid

echo "✅ 已全部停止"
