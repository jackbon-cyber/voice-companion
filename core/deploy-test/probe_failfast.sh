#!/bin/bash
# 验证"协议 schema 缺失时启动必须失败"。
#
# 这个 fail-fast 是本次部署实测加进去的：
# 过去 schema 缺失只会让每条上行消息被判"未知协议 schema"而丢弃，
# 云端退回降级话术继续对话 —— 看起来一切正常，实际协议校验从未生效。
#
# 做法：从 jar 里剔除 protocol/schema 下的文件，模拟"构建漏配 resources"，
# 再启动，看是不是明确报错退出。

set -uo pipefail

WORK=/tmp/noschema
rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

cp /opt/voice-companion/core/cloud/voice-cloud.jar app.jar

echo "--- 从 jar 中剔除 protocol/schema ---"
python3 - <<'PY'
import shutil
import zipfile

src = "app.jar"
dst = "app-noschema.jar"

with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    removed = 0
    for item in zin.infolist():
        if item.filename.startswith("BOOT-INF/classes/protocol/schema/"):
            removed += 1
            continue
        zout.writestr(item, zin.read(item.filename))
print(f"剔除 {removed} 个 schema 文件")
PY

echo "--- jar 内剩余 schema 数 ---"
python3 -c "
import zipfile
with zipfile.ZipFile('app-noschema.jar') as z:
    print(sum(1 for n in z.namelist() if 'protocol/schema' in n))
"

echo
echo "--- 启动（应当明确失败并退出）---"
timeout 120 java -jar app-noschema.jar --server.port=18081 > out.log 2>&1
echo "exit code = $?"
echo
echo "--- 关键日志 ---"
grep -iE "协议 schema|IllegalStateException|APPLICATION FAILED" out.log | head -5
