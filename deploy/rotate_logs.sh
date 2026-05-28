#!/bin/bash
# 岛屿铃钱记 — 日志轮转脚本
# 每 15 分钟由 cron 调用，轮转当前日志文件，删除 1 小时前的旧日志
#
# 安装:
#   chmod +x /opt/island_bells/deploy/rotate_logs.sh
#   crontab -e
#   # 添加: */15 * * * * /opt/island_bells/deploy/rotate_logs.sh
#
# 手动执行: bash /opt/island_bells/deploy/rotate_logs.sh

LOG_DIR="/opt/island_bells/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M)

# 确保日志目录存在
mkdir -p "$LOG_DIR"

# ========== 1. 删除 1 小时前的旧日志 ==========
find "$LOG_DIR" -name "*.log.*" -mmin +60 -delete 2>/dev/null

# ========== 2. 轮转后端日志 ==========
if [ -f "$LOG_DIR/backend.log" ] && [ -s "$LOG_DIR/backend.log" ]; then
    cp "$LOG_DIR/backend.log" "$LOG_DIR/backend.log.$TIMESTAMP"
    truncate -s 0 "$LOG_DIR/backend.log"
fi

if [ -f "$LOG_DIR/backend-error.log" ] && [ -s "$LOG_DIR/backend-error.log" ]; then
    cp "$LOG_DIR/backend-error.log" "$LOG_DIR/backend-error.log.$TIMESTAMP"
    truncate -s 0 "$LOG_DIR/backend-error.log"
fi

# ========== 3. 轮转 Nginx 日志 ==========
if [ -f "$LOG_DIR/nginx-access.log" ] && [ -s "$LOG_DIR/nginx-access.log" ]; then
    cp "$LOG_DIR/nginx-access.log" "$LOG_DIR/nginx-access.log.$TIMESTAMP"
    truncate -s 0 "$LOG_DIR/nginx-access.log"
    # 通知 Nginx 重新打开日志文件
    nginx -s reopen 2>/dev/null
fi

if [ -f "$LOG_DIR/nginx-error.log" ] && [ -s "$LOG_DIR/nginx-error.log" ]; then
    cp "$LOG_DIR/nginx-error.log" "$LOG_DIR/nginx-error.log.$TIMESTAMP"
    truncate -s 0 "$LOG_DIR/nginx-error.log"
fi
