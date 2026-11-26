"""核对远程的发布指引是否含凭据泄漏审计章节。

**为什么要单独写脚本**：raw.githubusercontent.com 有 CDN 缓存，
API 写完立刻读 raw 可能拿到旧版本 —— 2026-11-26 就因此误判过
"文件没推上去"。所以改从 API 读（内容与 sha 一起返回，无缓存歧义）。
"""

import base64
import json
import pathlib
import urllib.request

env: dict[str, str] = {}
for raw in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

headers = {
    "Authorization": f"Bearer {env['GITHUB_TOKEN']}",
    "User-Agent": "check",
    "Accept": "application/vnd.github+json",
}

base = (
    f"https://api.github.com/repos/{env['GITHUB_USERNAME']}/{env['GITHUB_REPO']}"
)

for path in [
    "docs/github-publish-guide.md",
    "tools/audit_secrets.py",
    "tools/audit_github_secrets.py",
    "tools/api_push.py",
]:
    url = f"{base}/contents/{path}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30
        ) as response:
            data = json.loads(response.read())
    except Exception as error:  # noqa: BLE001
        print(f"  ✗ {path}  {error}")
        continue

    content = base64.b64decode(data["content"]).decode("utf-8")
    print(f"  ✓ {path}  {data['size']} B  sha={data['sha'][:8]}")
    if path.endswith("github-publish-guide.md"):
        for marker in [
            "凭据泄漏审计",
            "audit_secrets.py",
            "audit_github_secrets.py",
            "Secret Scanning",
            "0 命中",
        ]:
            print(f"      含 {marker:<26}: {marker in content}")
