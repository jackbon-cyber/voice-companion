"""用环境变量里的凭据在 GitHub 上创建仓库并关联本地远程。

**为什么写成脚本而不是一行命令**：
把 Token 写进命令行参数会进入 shell 历史与进程列表。
脚本从 .env 读凭据，Token 不出现在任何命令行里。

用法（仓库根目录）：
    python tools/create_github_repo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

API_ROOT = "https://api.github.com"


def load_env(path: Path) -> dict[str, str]:
    """从 .env 读键值对。

    **只认最简单的 KEY=VALUE 形式** —— .env 只装本脚本要用的三样东西，
    不值得为它引入 python-dotenv 依赖。
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def api_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
) -> tuple[int, dict | str]:
    """调用 GitHub API，返回状态码与响应体。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("User-Agent", "voice-companion-setup")
    request.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def main() -> int:
    env = load_env(ENV_FILE)
    token = env.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    username = env.get("GITHUB_USERNAME", "")
    repo_name = env.get("GITHUB_REPO", "voice-companion")

    if not token:
        print("缺少 GITHUB_TOKEN：请在 .env 里填写，或设置同名环境变量。", file=sys.stderr)
        return 2
    if not username:
        print("缺少 GITHUB_USERNAME：请在 .env 里填写。", file=sys.stderr)
        return 2

    # --- 第一步：确认 token 有效并核对其身份 ---
    status, text = api_request("GET", f"{API_ROOT}/user", token)
    if status != 200:
        print(f"token 校验失败（HTTP {status}）：{text[:200]}", file=sys.stderr)
        return 1
    identity = json.loads(text)
    print(f"token 有效，身份 = {identity.get('login')}")
    if identity.get("login") != username:
        print(f"⚠️  token 身份是 {identity.get('login')}，与 .env 里的 {username} 不一致。")
        return 1

    # --- 第二步：查仓库是否已存在 ---
    status, text = api_request("GET", f"{API_ROOT}/repos/{username}/{repo_name}", token)
    if status == 200:
        repo_url = json.loads(text)["html_url"]
        print(f"仓库已存在：{repo_url}")
    else:
        print(f"仓库不存在（HTTP {status}），开始创建……")

        # ★ 仓库描述与 Topics 都在**建仓时**设好 ——
        # Topics 直接影响仓库的可发现性（搜"语音助手"能不能搜到它），
        # 事后在网页上补很容易忘。
        payload = {
            "name": repo_name,
            "description": (
                "端云全链路的语音情感陪伴机器人：协议契约、记忆能力、评测门禁。MIT 许可。"
            ),
            "private": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
            "has_discussions": True,
            "auto_init": False,
            "topics": [
                "voice-assistant",
                "speech-recognition",
                "memory",
                "chroma",
                "spring-boot",
                "faster-whisper",
                "json-schema",
                "evaluation-gate",
            ],
        }
        status, text = api_request("POST", f"{API_ROOT}/user/repos", token, payload)
        if status != 201:
            print(f"创建失败（HTTP {status}）：{text[:400]}", file=sys.stderr)
            return 1
        repo = json.loads(text)
        repo_url = repo["html_url"]
        print(f"创建成功：{repo_url}")
        print(f"  默认分支：{repo.get('default_branch')}")
        print(f"  Issues={repo.get('has_issues')}  Discussions={repo.get('has_discussions')}")

    # --- 第三步：关联本地远程 ---
    remote_url = f"https://github.com/{username}/{repo_name}.git"
    existing = subprocess.run(
        ["git", "remote"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    if "origin" in existing:
        subprocess.run(
            ["git", "remote", "set-url", "origin", remote_url],
            cwd=REPO_ROOT,
            check=True,
        )
        print(f"远程 origin 已更新为 {remote_url}")
    else:
        subprocess.run(
            ["git", "remote", "add", "origin", remote_url], cwd=REPO_ROOT, check=True
        )
        print(f"远程 origin 已添加：{remote_url}")

    print("\n下一步：")
    print(f"  git push -u origin {subprocess.run(['git','branch','--show-current'], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
