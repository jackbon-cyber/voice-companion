"""通过 GitHub REST API 提交文件（绕过 git 协议）。

**为什么需要这条路径**：
本机到 `github.com:443` 的路由在某个时刻开始不通
（DNS 正常、`api.github.com` / `raw.githubusercontent.com` /
`codeload.github.com` 都通，只有 git 传输用的 `github.com:443` 被挡）。
git 协议必须走 `github.com`，所以 `git push` 会一直失败。

但 REST API 走的是 `api.github.com` —— **那条通路是通的**，
且同样是 GitHub 官方支持的方式。

**限制与取舍**：
- 一次只能提交一个文件，所以本脚本按文件逐个建 commit；
- commit 链与本地不完全一致（每个文件一个 commit），
  所以推完之后需要 `git fetch` + `git reset --hard origin/main` 让本地跟远程对齐。

**安全**：Token 从 .env 读，只在内存里；输出不含 Token。
"""

import base64
import json
import pathlib
import subprocess
import sys
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
    "User-Agent": "api-push",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/json",
}

API = f"https://api.github.com/repos/{username}/{repo_name}"


def api(method: str, url: str, payload: dict | None = None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout or ""


def main() -> int:
    # 待推送的文件：从本地 HEAD 与远程 HEAD 的差异里取。
    remote_head = api("GET", f"{API}/commits?per_page=1")[0]["sha"]
    local_head = git("rev-parse", "HEAD").strip()
    print(f"远程 HEAD：{remote_head[:8]}   本地 HEAD：{local_head[:8]}")

    if remote_head == local_head:
        print("本地与远程已一致，无需推送。")
        return 0

    # 列出远程还没有的文件
    remote_files = set()
    remote_blob_sha: dict[str, str] = {}
    for entry in api("GET", f"{API}/git/trees/{remote_head}?recursive=1").get("tree", []):
        if entry["type"] == "blob":
            remote_files.add(entry["path"])
            remote_blob_sha[entry["path"]] = entry["sha"]

    local_files = git("ls-tree", "-r", "--name-only", local_head).split("\n")
    missing = [p for p in local_files if p and p not in remote_files]

    # ★ 远程**已有**但本地内容不同的文件也要推 ——
    # 只推"远程没有的文件"会漏掉修改。2026-11-26 就漏过一次：
    # 发布指引里的审计章节因此没上去。
    modified: list[str] = []
    for path in local_files:
        if not path or path not in remote_files:
            continue
        local_blob = git("rev-parse", f"{local_head}:{path}").strip()
        if local_blob and local_blob != remote_blob_sha.get(path):
            modified.append(path)

    if not missing and not modified:
        print("所有文件都已在远程且内容一致。")
        return 0

    if missing:
        print(f"待提交（新增）{len(missing)} 个文件：")
        for path in missing:
            print(f"  {path}")
    if modified:
        print(f"待提交（修改）{len(modified)} 个文件：")
        for path in modified:
            print(f"  {path}")

    # 逐个文件建 commit
    parent = remote_head
    todo = [(p, "新增") for p in missing] + [(p, "修改") for p in modified]
    for index, (path, kind) in enumerate(todo, start=1):
        local_path = pathlib.Path(path)
        if not local_path.exists():
            print(f"  [{index}/{len(todo)}] 跳过（本地不存在）：{path}")
            continue
        content = base64.b64encode(local_path.read_bytes()).decode("ascii")
        payload: dict = {
            "message": f"chore: {kind} {path}",
            "content": content,
            "branch": "main",
        }
        # ★ 修改已有文件必须带 sha ——
        # GitHub 用它做并发检查：sha 不匹配说明你基于旧版本改的，会被拒。
        if kind == "修改":
            payload["sha"] = remote_blob_sha[path]
        try:
            created = api("PUT", f"{API}/contents/{path}", payload)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            print(f"  [{index}/{len(todo)}] ✗ {path} 失败：HTTP {error.code} {detail[:160]}")
            return 1
        parent = created["commit"]["sha"]
        print(f"  [{index}/{len(todo)}] ✓ {kind} {path}  → {parent[:8]}")

    print(f"\n完成。远程新 HEAD：{parent}")
    print("下一步（让本地与远程对齐）：")
    print("  git fetch origin && git reset --hard origin/main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
