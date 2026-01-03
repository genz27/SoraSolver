#!/bin/bash

# 清理旧的 Xvfb 锁文件
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null

# 启动 Xvfb 虚拟显示器
Xvfb :99 -screen 0 1920x1080x24 -ac &
sleep 2

# 设置显示器
export DISPLAY=:99

# 验证 Xvfb 是否启动
if ! pgrep -x "Xvfb" > /dev/null; then
    echo "❌ Xvfb 启动失败"
    exit 1
fi

echo "✅ Xvfb 已启动，DISPLAY=$DISPLAY"

# 启动服务
exec python -m uvicorn server:app --host 0.0.0.0 --port 8005 --workers 1
