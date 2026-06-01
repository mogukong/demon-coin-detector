#!/bin/bash
# 妖币猎手 - 一键启动脚本
# 用法: ./start.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎯 妖币猎手 v2.3rsi 启动中..."

# 杀掉旧进程
pkill -f "live_trader.py --loop" 2>/dev/null
pkill -f "watchdog.py" 2>/dev/null
sleep 1

# 清理缓存
find . -name "*.pyc" -delete 2>/dev/null
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# 启动看门狗 (会自动启动交易引擎)
echo "🐕 启动看门狗..."
python3 watchdog.py &
WATCHDOG_PID=$!
echo "✅ 看门狗已启动 PID=$WATCHDOG_PID"

# 保存 PID
echo $WATCHDOG_PID > watchdog.pid

echo ""
echo "========================================="
echo "  妖币猎手 v2.3rsi 已启动"
echo "  看门狗 PID: $WATCHDOG_PID"
echo "  日志文件: live_log.txt"
echo "========================================="
echo ""
echo "查看日志: tail -f live_log.txt"
echo "停止运行: pkill -f watchdog.py && pkill -f live_trader.py"
