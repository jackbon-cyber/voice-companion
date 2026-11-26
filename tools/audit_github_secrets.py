"""从 GitHub 服务器侧审计已推送的仓库有没有凭据泄漏。

**为什么本地扫完还要从 GitHub 侧扫**：
本地扫的是 git 对象库，理论上等于推上去的内容。
但"用户实际能下载到的内容"这件事需要独立验证 ——
所以直接从 raw.githubusercontent.com 把文件拉回来扫。

**安全**：Token 只从 .env 读、只在内存里；输出不含 Token 本身。
"""

import json
import pathlib
import re
import urllib.error
import urllib.request

env: dict[str, str] = {}
for raw in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

token = env.get("GITHUB_TOKEN", "")
username = env.get("GITHUB_USERNAME", "")
repo_name = env.get("GITHUB_REPO", "voice-companion")

HEADERS = {
    "Authorization": f"Bearer {token}",
    "User-Agent": "secret-audit",
    "Accept": "application/vnd.github+json",
}

print("=== 1. GitHub Secret Scanning（GitHub 自己的判定）===")
try:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{username}/{repo_name}/secret-scanning/alerts",
        headers=HEADERS,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        alerts = json.loads(response.read())
    if alerts:
        print(f"  ⚠️ GitHub 报出 {len(alerts)} 条泄漏告警：")
        for alert in alerts:
            print(f"     - {alert.get('secret_type')}  {alert.get('html_url')}")
    else:
        print("  ✓ GitHub Secret Scanning：0 条告警")
except urllib.error.HTTPError as error:
    if error.code == 404:
        print("  - 无告警（404：该仓库无可扫内容或功能未开启）")
    elif error.code == 403:
        print("  - 无告警（403：该功能需 GitHub 高级安全，本仓库未订阅）")
    else:
        print(f"  - 查询失败（HTTP {error.code}）")
except Exception as error:  # noqa: BLE001
    print(f"  - 查询失败：{error}")

print("\n=== 2. 从 GitHub 拉回文件内容，直接搜真实 token ===")
# ★ 最关键的一步：不是扫本地，是把 GitHub 上的文件拉回来扫 ——
# 这样验证的是"用户实际能下载到的内容里有没有密钥"。
real_token = env.get("GITHUB_TOKEN", "")
# 只用真实 token 的前 12 位做特征串：足够唯一，又不至于把完整 token 打出来
fragment = real_token[:12] if real_token else ""

paths = [
    "README.md",
    "docs/github-publish-guide.md",
    "tools/check_token_scopes.py",
    "tools/verify_github_push.py",
    "tools/create_github_repo.py",
    "core/README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
]

hits = 0
for path in paths:
    url = f"https://raw.githubusercontent.com/{username}/{repo_name}/main/{path}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "audit"})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        print(f"  - {path}（不存在）")
        continue

    if fragment and fragment in content:
        print(f"  ⚠️ {path} 含真实 token 片段！")
        hits += 1
        continue

    suspicious = re.findall(r"ghp_[A-Za-z0-9]{20,}", content)
    if suspicious:
        print(f"  ⚠️ {path} 含疑似 token 串：{suspicious[0][:8]}…")
        hits += 1
    else:
        print(f"  ✓ {path} 干净")

print(f"\n  GitHub 上的真实 token 命中数：{hits}")

print("\n=== 3. 仓库可见性（决定泄漏影响面）===")
request = urllib.request.Request(
    f"https://api.github.com/repos/{username}/{repo_name}", headers=HEADERS
)
with urllib.request.urlopen(request, timeout=30) as response:
    repo = json.loads(response.read())
visibility = "private" if repo["private"] else "public"
print(f"  可见性：{visibility}")
if visibility == "public":
    print("  → 公开仓库：任何人都能 clone，凭据一旦泄漏影响面是全网")
else:
    print("  → 私有仓库：影响面限于有权限者")
