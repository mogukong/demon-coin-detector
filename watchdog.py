#!/usr/bin/env python3
"""
妖币猎手 - 看门狗脚本
自动重启崩溃的交易引擎
用法: python3 watchdog.py
"""
import subprocess
import time
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADER_SCRIPT = os.path.join(SCRIPT_DIR, "live_trader.py")
LOG_FILE = os.path.join(SCRIPT_DIR, "watchdog.log")
PID_FILE = os.path.join(SCRIPT_DIR, "watchdog.pid")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [WATCHDOG] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def is_trader_running():
    """检查交易进程是否在运行"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "live_trader.py --loop"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False

def start_trader():
    """启动交易进程"""
    log("🚀 启动交易引擎...")
    # 不重定向 stdout，让 live_trader.py 自己写日志
    proc = subprocess.Popen(
        [sys.executable, "-u", TRADER_SCRIPT, "--loop"],
        cwd=SCRIPT_DIR
    )
    log(f"✅ 交易引擎已启动 PID={proc.pid}")
    return proc.pid

def main():
    # 写入 PID 文件
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    log("=" * 50)
    log("看门狗启动")
    log("=" * 50)
    
    restart_count = 0
    last_restart = 0
    
    while True:
        if not is_trader_running():
            # 防止频繁重启 (最少间隔30秒)
            now = time.time()
            if now - last_restart < 30:
                log("⚠️ 重启间隔太短，等待30秒...")
                time.sleep(30)
                continue
            
            restart_count += 1
            log(f"⚠️ 交易引擎未运行! 第{restart_count}次重启")
            start_trader()
            last_restart = time.time()
            
            # 等待5秒确认启动成功
            time.sleep(5)
            if is_trader_running():
                log("✅ 重启成功")
            else:
                log("❌ 重启失败，等待60秒后重试")
                time.sleep(60)
        else:
            # 正常运行中，每30秒检查一次
            time.sleep(30)

if __name__ == "__main__":
    main()
