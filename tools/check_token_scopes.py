"""查当前 PAT 的类型、权限与有效期。

**为什么需要**：改 scope 之前，得先知道手里这个 Token 是
classic 还是 fine-grained —— 两者的加权限入口完全不同，
而且 classic 可以"编辑并重新生成"（会换新的 Token 值），
fine-grained 则要在仓库的 Permissions 里改。

**安全**：Token 只从 .env 读、只在内存里；输出不含 Token 本身。
"""

import json
import pathlib
import urllib.request

env: dict[str, str] = {}
for raw in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

token = env.get("GITHUB_TOKEN", "")
if not token:
    raise SystemExit(".env 里没有 GITHUB_TOKEN")

headers = {
    "Authorization": f"Bearer {token}",
    "User-Agent": "token-info",
    "Accept": "application/vnd.github+json",
}

print("=== Token 类型判定 ===")
print(f"  前缀 {token[:4]!r} => " + ("classic（ghp_）" if token.startswith("ghp_") else "fine-grained（github_pat_）"))

with urllib.request.urlopen(urllib.request.Request("https://api.github.com/user", headers=headers), timeout=30) as r:
    scopes = r.headers.get("X-OAuth-Scopes") or ""
    print(f"  身份：{json.loads(r.read())['login']}")
print(f"  现有 scopes：{scopes or '(空)'}")

print("\n=== 有效期（/application-tokens 仅 classic 可查）===")
try:
    req = urllib.request.Request(
        "https://api.github.com/application/tokens/ghp_placeholder",
        headers=headers,
    )
    # classic token 的自身信息通过 /user 拿不到到期时间，
    # 只能通过 OAuth 应用页面看 —— 这里改为提示用户去网页确认。
except urllib.error.HTTPError:
    pass
print("  classic token 的到期时间请在网页确认：")
print("    https://github.com/settings/tokens  →  你的 Token 右侧会显示 'Expires'")
