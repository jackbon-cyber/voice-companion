"""核对 GitHub 上的仓库内容与本地是否一致。

**为什么需要**：push 返回 0 只说明 git 协议层面成功 ——
但 GitHub 侧可能对某些路径做了额外处理（比如 workflow 文件的权限校验），
也可能仓库设置（Issues / Descriptions / Topics / 默认分支）
没有按预期生效。这些都得**从 GitHub 侧读回来**才算数。

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
username = env.get("GITHUB_USERNAME", "")
repo_name = env.get("GITHUB_REPO", "voice-companion")

HEADERS = {
    "Authorization": f"Bearer {token}",
    "User-Agent": "verify-push",
    "Accept": "application/vnd.github+json",
}


def get(path: str):
    request = urllib.request.Request(
        f"https://api.github.com{path}", headers=HEADERS
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


print("=== 仓库基本信息 ===")
repo = get(f"/repos/{username}/{repo_name}")
print(f"  URL           : {repo['html_url']}")
print(f"  可见性        : {'private' if repo['private'] else 'public'}")
print(f"  默认分支      : {repo['default_branch']}")
print(f"  Issues        : {repo['has_issues']}")
print(f"  Discussions   : {repo['has_discussions']}")
print(f"  Wiki          : {repo['has_wiki']}")
print(f"  Stars/Forks   : {repo['stargazers_count']} / {repo['forks_count']}")
print(f"  描述          : {repo.get('description')}")
print(f"  Topics        : {repo.get('topics')}")

print("\n=== ★ workflow 文件是否真的在 GitHub 上 ===")
# ★ 这是之前被拒的那个文件 —— 必须单独确认它落地了，
# 否则仓库有 CI 文件但 GitHub 上没有，Actions 永远不会触发。
try:
    content = get(f"/repos/{username}/{repo_name}/contents/.github/workflows/ci.yml")
    print(f"  ✓ ci.yml 存在，size={content['size']} B  sha={content['sha'][:7]}")
except urllib.error.HTTPError as error:
    print(f"  ✗ ci.yml 不存在（HTTP {error.code}）")

print("\n=== 其他 GitHub 原生件是否落地 ===")
for path in [
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "docs/architecture/README.md",
    "docs/adr/README.md",
    "docs/interface-contract/README.md",
    "docs/known-limitations.md",
    "docs/operations-manual.md",
    "docs/deployment.md",
    "docs/secondary-development.md",
    "docs/github-publish-guide.md",
]:
    try:
        item = get(f"/repos/{username}/{repo_name}/contents/{path}")
        print(f"  ✓ {path}  ({item['size']} B)")
    except urllib.error.HTTPError:
        print(f"  ✗ {path}  缺失")

print("\n=== 远程 commit 与本地 HEAD 对比 ===")
local_head = subprocess_run = pathlib.Path(".git/refs/heads/main").read_text().strip() if pathlib.Path(".git/refs/heads/main").exists() else ""
commits = get(f"/repos/{username}/{repo_name}/commits?per_page=1")
remote_head = commits[0]["sha"]
print(f"  远程 HEAD : {remote_head}")
print(f"  远程提交数: {get(f'/repos/{username}/{repo_name}/commits?per_page=1')[0]['sha'][:7]} (取最新一条)")
print(f"  最新提交信息: {commits[0]['commit']['message'].splitlines()[0]}")
