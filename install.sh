#!/bin/bash
# 妖币猎手 - 一键安装脚本
# Usage: bash install.sh

set -e

echo "👹 妖币猎手 v3.1 安装脚本"
echo "========================"

# Check Python version
echo "检查Python版本..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python版本: $python_version"

# Create directory
INSTALL_DIR="$HOME/.hermes/skills/trading/demon-coin-detector"
echo "安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Download files (if not exists)
if [ ! -f "live_trader.py" ]; then
    echo "下载文件..."
    # TODO: Replace with actual download URLs
    # curl -sL https://raw.githubusercontent.com/.../live_trader.py -o live_trader.py
    # curl -sL https://raw.githubusercontent.com/.../watchdog.py -o watchdog.py
    # curl -sL https://raw.githubusercontent.com/.../advanced_modules.py -o advanced_modules.py
    # curl -sL https://raw.githubusercontent.com/.../strategy_params.json -o strategy_params.json
    echo "请手动下载文件到 $INSTALL_DIR"
    echo "需要的文件: live_trader.py, watchdog.py, advanced_modules.py, strategy_params.json"
    exit 1
fi

# Create .env if not exists
if [ ! -f ".env" ]; then
    echo "创建配置文件..."
    cp .env.example .env
    echo ""
    echo "⚠️  请编辑 .env 文件填入你的API密钥:"
    echo "   nano $INSTALL_DIR/.env"
    echo ""
fi

# Create necessary files
touch live_state.json live_trades.json live_log.txt

# Set permissions
chmod 600 .env
chmod +x live_trader.py watchdog.py

echo ""
echo "✅ 安装完成!"
echo ""
echo "下一步:"
echo "1. 编辑配置文件: nano $INSTALL_DIR/.env"
echo "2. 测试运行: cd $INSTALL_DIR && python3 live_trader.py"
echo "3. 后台运行: python3 live_trader.py --loop"
echo "4. 使用watchdog: python3 watchdog.py"
echo ""
echo "📖 详细文档: $INSTALL_DIR/SKILL.md"
echo ""
echo "⚠️  风险警告: 期货交易有高风险，请谨慎使用!"
