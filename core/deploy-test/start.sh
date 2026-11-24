#!/bin/bash
# 容器内的启动脚本 —— 等价于手册 4.6 的 systemd 编排。
#
# systemd 里是「After=network.target chromadb.service」+「Restart=on-failure」，
# 容器里没有 systemd，所以这里手写等价逻辑：
#   1. 起 ChromaDB
#   2. 等 Chroma 就绪（手册 4.4 的 until curl 循环）
#   3. 起嵌入服务
#   4. 等嵌入服务就绪
#   5. 起云端
#   6. 等云端就绪
#
# 每一步的等待逻辑与手册 4.4 逐字对应 —— 这正是要实测的部分。
#
# ★ 嵌入服务必须在云端之前就绪：
#   云端收到"用户说了什么"后会**同步**调嵌入服务算向量，
#   嵌入服务不可用时记忆写入和下行回复都会失败（不是降级，是直接不回复）。
#   实测日志："记忆写入失败，已忽略：local embedding connect failed"。

set -euo pipefail

CHROMA_URL="http://127.0.0.1:8765/api/v2/version"
EMBED_URL="http://127.0.0.1:8766/v1/health"
CLOUD_URL="http://127.0.0.1:8080/api/health"
LOG_DIR=/opt/voice-companion/core/cloud/logs
APP_DIR=/opt/voice-companion

mkdir -p "$LOG_DIR" "$APP_DIR/data/chroma"

echo "==> 起 ChromaDB"
chroma run --path "$APP_DIR/data/chroma" --host 127.0.0.1 --port 8765 \
    > "$LOG_DIR/chroma.out.log" 2>&1 &
CHROMA_PID=$!

echo "==> 等 ChromaDB 就绪"
until curl -sf "$CHROMA_URL" >/dev/null; do
    if ! kill -0 "$CHROMA_PID" 2>/dev/null; then
        echo "★ ChromaDB 进程已退出，日志："
        tail -30 "$LOG_DIR/chroma.out.log"
        exit 1
    fi
    sleep 2
done
echo "==> ChromaDB 已就绪"

echo "==> 起嵌入服务"
python3 -m core.edge.embedding.service \
    --port 8766 \
    --model-dir "$APP_DIR/core/models/embedding" \
    > "$LOG_DIR/embedding.out.log" 2>&1 &
EMBED_PID=$!

echo "==> 等嵌入服务就绪"
until curl -sf "$EMBED_URL" >/dev/null; do
    if ! kill -0 "$EMBED_PID" 2>/dev/null; then
        echo "★ 嵌入服务进程已退出，日志："
        tail -30 "$LOG_DIR/embedding.out.log"
        exit 1
    fi
    sleep 2
done
echo "==> 嵌入服务已就绪"

echo "==> 起云端后端"
java -jar "$APP_DIR/core/cloud/voice-cloud.jar" \
    > "$LOG_DIR/backend.out.log" 2>&1 &
CLOUD_PID=$!

echo "==> 等云端后端就绪"
until curl -sf "$CLOUD_URL" >/dev/null; do
    if ! kill -0 "$CLOUD_PID" 2>/dev/null; then
        echo "★ 云端后端进程已退出，日志："
        tail -40 "$LOG_DIR/backend.out.log"
        exit 1
    fi
    sleep 2
done
echo "==> 云端后端已就绪"

echo "==> 服务已就绪（Chroma :8765 / 嵌入 :8766 / 云端 :8080）"

# 保持前台
wait "$CLOUD_PID"
