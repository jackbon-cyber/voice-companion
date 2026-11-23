"""云端大模型路径的端到端验证。

**为什么需要这个测试**

手工跑一次"接了 LLM 后端到端是否还成立"只能证明一次。
这个测试把它固化成可重复执行的检查：

1. 启动本地模拟 OpenAI 兼容网关；
2. 用带 LLM 配置启动云端（独立进程，独立端口）；
3. 跑隔离断言，确认**记忆选择仍由代码决定**、**引用来源仍由代码填充**；
4. 停掉网关，再跑一次，确认**大模型不可用时自动退回模板**且断言依然全过。

**为什么用真实子进程而不是 mock**

隔离断言的价值在于它读的是**协议里真实传输的字段**。
mock 掉云端或 mock 掉 HTTP 客户端，这条链路就断了，测不到真东西。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_SCRIPT = REPO_ROOT / "core" / "tests" / "fixtures" / "fake_llm_gateway.py"
CLOUD_ROOT = REPO_ROOT / "core" / "cloud"


def _free_port() -> int:
    """找一个空闲端口。

    @return 端口号
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """终止进程<b>及其全部子进程</b>。

    **为什么必须连子进程一起杀**：Windows 上 {@code mvn spring-boot:run}
    会 fork 出 java 子进程真正跑应用。只 terminate 掉 mvn 那个壳，
    java 子进程会**继续活着**并继续占用端口、继续往 Chroma 写数据。

    **这个 bug 的实际后果**（实测踩到过）：残留云端持续压 Chroma，
    下一个用例的写入被拖到超时，于是"记忆写入失败，已忽略"——
    表现为<b>用户 B 的记忆凭空消失</b>，端到端断言报"回复引用自己的记忆"失败。
    而失败的真正原因在几公里之外的进程清理上，极难定位。

    **为什么用 taskkill 而不是手工遍历**：手工遍历要处理
    "孙进程"和"进程已退出"两类边界，而 taskkill /T 直接按进程树杀。

    @param process 要终止的进程
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        # /T 终止整棵进程树，/F 强制（不弹确认框）。
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()


# 云端启动等待窗口（秒）。
#
# **为什么是 180 而不是 90**：实测 `mvn spring-boot:run` 冷启动耗时
# **66 秒**（Tomcat started 到 Started VoiceCloudApplication），
# 加上进程拉起约 73 秒。原来的 90 秒窗口只剩 17 秒余量 ——
# 在并行跑全量测试、或机器负载高时**会偶发超时**，
# 表现为"云端未能启动"，看起来像代码有问题，实际是窗口太紧。
#
# **为什么不是无限等待**：无限等待会让"云端根本起不来"（缺依赖、端口冲突）
# 这种真故障也变成漫长的等待，掩盖问题本身。
#
# **为什么留 2.5 倍余量**：冷启动耗时受磁盘速度与当时负载影响，
# 波动幅度实测可达 ±30%。窗口太贴实测值会在最需要它的时候失效。
CLOUD_STARTUP_TIMEOUT_SECONDS = 180.0


def _wait_http(url: str, timeout_seconds: float = CLOUD_STARTUP_TIMEOUT_SECONDS) -> bool:
    """等待 HTTP 服务就绪。

    @param url 健康检查地址
    @param timeout_seconds 最长等待秒数
    @return 就绪返回 True
    """
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    return False


def _wait_tcp(port: int, timeout_seconds: float = 20.0) -> bool:
    """等待 TCP 端口开始监听。

    @param port 端口
    @param timeout_seconds 最长等待秒数
    @return 监听返回 True
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


class _Gateway:
    """模拟 OpenAI 兼容网关的生命周期管理。"""

    def __init__(self, port: int) -> None:
        """构造网关。

        @param port 监听端口
        """
        self.port = port
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        """启动网关进程。"""
        self.process = subprocess.Popen(
            [sys.executable, str(GATEWAY_SCRIPT), str(self.port)],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert _wait_tcp(self.port), "模拟网关未能启动"

    def stop(self) -> None:
        """停止网关进程。"""
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


@pytest.fixture()
def cloud_with_llm():
    """启动带大模型配置的云端进程，测试结束后停止。

    :return (云端上行地址, 网关控制对象)
    """
    gateway_port = _free_port()
    cloud_port = _free_port()
    gateway = _Gateway(gateway_port)
    gateway.start()

    env = dict(os.environ)
    env["VOICE_LLM_BASE_URL"] = f"http://127.0.0.1:{gateway_port}"
    env["VOICE_LLM_API_KEY"] = "local-fake-key"
    env["VOICE_LLM_MODEL"] = "test-model"
    env["VOICE_SERVER_PORT"] = str(cloud_port)

    maven = "mvn.cmd" if os.name == "nt" else "mvn"
    cloud_process = subprocess.Popen(
        [maven, "-o", "spring-boot:run", f"-Dspring-boot.run.arguments=--server.port={cloud_port}"],
        cwd=CLOUD_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=os.name == "nt",
    )
    try:
        assert _wait_http(f"http://127.0.0.1:{cloud_port}/api/health"), "云端未能启动"
        yield f"ws://127.0.0.1:{cloud_port}/voice/uplink", gateway
    finally:
        _terminate_process_tree(cloud_process)
        gateway.stop()


def _run_isolation(url: str, report_path: Path) -> dict:
    """跑端到端隔离断言并返回报告。

    @param url 云端上行地址
    @param report_path 报告输出路径
    @return 报告内容
    """
    result = subprocess.run(
        [sys.executable, "-m", "core.e2e.isolation", "--url", url, "--report", str(report_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        # 超时必须大于云端冷启动 + 隔离断言本身的耗时之和。
        # 云端已在 fixture 里起好了，这里只是跑断言 ——
        # 但断言过程要写记忆、召回、比对，机器负载高时会明显变慢。
        timeout=300,
    )
    assert report_path.is_file(), (
        f"端到端报告未生成：{result.stdout}\n{result.stderr}"
    )
    return json.loads(report_path.read_text(encoding="utf-8"))


def _format_failure(report: dict, label: str) -> str:
    """把端到端报告的失败项整理成可读的报错。

    **为什么要单独格式化**：报告里可能有十几条断言明细，
    直接把整个 JSON 塞进报错信息，真正失败的那一条被淹没了 ——
    排查时得先在几百字里找"passed: false"。
    这里只列出**失败项**的名字与细节。

    @param report 端到端报告
    @param label 场景标签
    @return: 报错信息
    """
    failed = [
        check
        for check in report.get("checks", [])
        if not check.get("passed", True)
    ]
    if not failed:
        return (
            f"{label}未通过，但报告里没有失败项 —— "
            f"完整报告：{json.dumps(report, ensure_ascii=False)}"
        )

    lines = [f"{label}未通过，以下 {len(failed)} 项断言失败："]
    for check in failed:
        lines.append(f"  - {check.get('name', '(未命名)')}：{check.get('detail', '')}")
    lines.append("")
    lines.append(f"完整报告：{json.dumps(report, ensure_ascii=False)}")
    return "\n".join(lines)


@pytest.mark.slow
def test_llm_path_keeps_isolation(cloud_with_llm, tmp_path: Path):
    """接入大模型后，隔离断言依然全部通过。

    **这是本次改造最关键的一条**：接大模型不能破坏隔离。
    """
    url, _gateway = cloud_with_llm

    report = _run_isolation(url, tmp_path / "e2e-llm.json")

    assert report.get("result") == "PASSED", _format_failure(report, "接入大模型后的隔离")

    # 隔离相关的四项必须全过。
    isolation_checks = [
        check for check in report["checks"]
        if "引用" in check["name"] or "泄漏" in check["name"]
    ]
    assert len(isolation_checks) == 4, "隔离断言数量异常"
    for check in isolation_checks:
        assert check["passed"], f"隔离断言未通过：{check['name']} —— {check['detail']}"


@pytest.mark.slow
def test_llm_failure_falls_back_to_template(cloud_with_llm, tmp_path: Path):
    """大模型不可用时自动退回模板，断言依然全部通过。

    **为什么这条重要**：陪伴场景里"说一句生硬的话"远好过"整轮对话中断"。
    """
    url, gateway = cloud_with_llm
    gateway.stop()

    report = _run_isolation(url, tmp_path / "e2e-llm-down.json")

    assert report.get("result") == "PASSED", _format_failure(report, "降级路径")
