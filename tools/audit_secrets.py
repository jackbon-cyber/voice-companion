"""审计已推送的 git 历史里有没有**真实**凭据泄漏。

**为什么要区分"前缀字符串"与"真凭据"**：
安全扫描工具对 `ghp_` 这类前缀一律报警，
但文档里写"Token 形如 `ghp_xxx`"是**正常的说明**，
不是泄漏。真凭据的特征是：**前缀 + 至少 36 位 base62 字符**。

所以本脚本按"前缀 + 长度 + 字符集"判定，
避免把说明文字误报成泄漏（那样会让人对真问题麻木）。

**扫的是 git 历史**（所有分支的所有提交），
而不只是当前工作区 —— 泄漏更常发生在"先提交、后删除"的路径上。
"""

import re
import subprocess
import sys

# (正则, 说明, 是否只在历史里扫)
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub classic PAT: ghp_ + 36 位
    (re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"), "GitHub classic PAT"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "GitHub 各类 token"),
    # GitHub fine-grained PAT: github_pat_ + 22+ 位下划线分隔
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "GitHub fine-grained PAT"),
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
    # AWS secret access key（40 位 base64）
    (re.compile(r"(?i)\baws_secret_access_key\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})\b"), "AWS Secret Key"),
    # Slack
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    # Google API key
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API Key"),
    # OpenAI
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "OpenAI style key"),
    # 阿里云 DashScope（本次项目真实用到的 provider）
    (re.compile(r"\bsk-[a-f0-9]{32}\b"), "DashScope key (sk- + 32 hex)"),
    # 私钥块
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "私钥文件内容"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "JWT"),
    # Azure / Google 云平台通用 API key 形态
    (re.compile(r"(?i)\bapi[_-]?key\s*[=:]\s*['\"]([A-Za-z0-9_\-]{32,})['\"]"), "硬编码 api key"),
]


def scan(text: str, source: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for pattern, label in PATTERNS:
        for match in pattern.finditer(text):
            hits.append((label, match.group(0)[:24] + "…"))
    return hits


def git(*args: str) -> str:
    """跑 git 并取 stdout。

    **为什么显式指定编码**：Windows 上 git 的输出里含中文文件名，
    默认的 GBK 解码会抛 UnicodeDecodeError —— 而这恰恰会让审计脚本
    在最需要它的地方（扫历史）中途挂掉。强制 UTF-8 + errors="replace"
    保证扫描能跑完，跑不完的审计等于没有审计。
    """
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
    print("=== A. 扫全部历史提交里的文件内容 ===")
    # 用 git grep 扫所有提交 —— 比 checkout 每个版本快得多，且覆盖全历史。
    commits = git("rev-list", "--all").split()
    print(f"  待扫提交数：{len(commits)}")

    findings: dict[str, list[str]] = {}
    for index, commit in enumerate(commits, start=1):
        if index % 20 == 0:
            print(f"    ...{index}/{len(commits)}")
        # git grep 该提交下的所有文件
        output = git("grep", "-I", "-n", "-E",
                     "|".join(p.pattern for p, _ in PATTERNS), commit)
        for line in output.splitlines():
            for pattern, label in PATTERNS:
                if pattern.search(line):
                    findings.setdefault(label, []).append(
                        f"{commit[:8]} {line.split(':', 2)[-1][:110]}"
                    )

    if not findings:
        print("  ✓ 全历史未发现真实凭据形态的字符串")
    else:
        for label, items in findings.items():
            print(f"  ⚠️ {label}：{len(items)} 处")
            for item in items[:5]:
                print(f"      {item}")

    print("\n=== B. 扫提交信息 ===")
    messages = git("log", "--all", "--format=%H%n%B%n---") or ""
    message_hits = False
    for pattern, label in PATTERNS:
        if pattern.search(messages):
            message_hits = True
            print(f"  ⚠️ {label} 出现在提交信息里")
    if not message_hits:
        print("  ✓ 提交信息干净")

    print("\n=== C. 扫当前工作区未跟踪文件 ===")
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    for path in untracked:
        try:
            content = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for label, _ in scan(content, path):
            findings.setdefault(f"{label}（未跟踪文件）", []).append(path)
    if any("未跟踪文件" in k for k in findings):
        for label, items in findings.items():
            if "未跟踪文件" in label:
                print(f"  ⚠️ {label}：{items}")
    else:
        print("  ✓ 未跟踪文件干净")

    print("\n=== D. 已入库文件里是否含 .env 形态的凭据 ===")
    for path in git("ls-files").split():
        if path.endswith((".env", ".env.local")) or "/.env" in path:
            print(f"  ⚠️ {path} 已入库")
    tracked_env = [p for p in git("ls-files").split() if p.endswith(".env")]
    if not tracked_env:
        print("  ✓ 没有任何 .env 形态的文件入库")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
