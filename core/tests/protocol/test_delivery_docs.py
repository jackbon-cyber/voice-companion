"""交付文档的完整性检查。

文档会漂移：代码改了、文档没改，接手的人按文档做就会踩坑。
这里把文档里**引用的代码符号**钉在实际代码上。
"""

from __future__ import annotations

import re
from pathlib import Path

# 仓库根。测试位于 core/tests/protocol/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 被检查的文档：(相对路径, 必须提到的标识集合)
DOCUMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "docs/known-limitations.md",
        (
            "FactualGuard",
            "DegradePolicy",
            "SessionRegistry",
        ),
    ),
    (
        "docs/secondary-development.md",
        (
            "SpeechRecognizer",
            "RecognitionResult",
            "LocalIntentModel",
            "LocalDialogEngine",
            "MetricsReporter",
            "validate-protocol.ps1",
            "speech_probability_threshold",
            "energy_threshold",
            "failure_threshold",
            "recovery_success_threshold",
        ),
    ),
)


def _doc_text(relative_path: str) -> str:
    """读取文档全文。

    @param relative_path 相对仓库根的路径
    @return 文档文本
    """
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_all_documents_exist():
    for relative_path, _ in DOCUMENTS:
        assert (REPO_ROOT / relative_path).exists(), f"文档缺失：{relative_path}"


def test_documents_reference_expected_symbols():
    for relative_path, symbols in DOCUMENTS:
        text = _doc_text(relative_path)
        missing = [symbol for symbol in symbols if symbol not in text]
        assert not missing, f"{relative_path} 未提到这些标识：{missing}"


def test_secondary_guide_mentions_validation_commands():
    """二次开发指南必须给出可执行的验证命令，否则等于没说。"""
    text = _doc_text("docs/secondary-development.md")

    assert "validate-protocol.ps1" in text
    assert "pytest" in text
    assert "mvn" in text


def test_known_limitations_distinguishes_designed_vs_unimplemented():
    """已知限制必须区分"设计上不支持"与"尚未实现"。"""
    text = _doc_text("docs/known-limitations.md")

    assert "设计上不支持" in text
    assert "尚未实现" in text


def test_known_limitations_lists_verification_methods():
    """每条限制都要有验证方式 —— 声称支持而实际不支持是最危险的。"""
    text = _doc_text("docs/known-limitations.md")

    assert text.count("验证方式") >= 3


def test_secondary_guide_has_self_check_list():
    text = _doc_text("docs/secondary-development.md")

    assert "自检清单" in text
    assert "- [ ]" in text


def test_secondary_guide_states_three_invariants():
    """二次开发指南要讲清最容易踩的坑。"""
    text = _doc_text("docs/secondary-development.md")

    for keyword in ("协议只改一处", "业务逻辑不进", "先搜再建"):
        assert keyword in text, f"二次开发指南缺少关键约束：{keyword}"


def test_no_undocumented_module_references():
    """文档里提到的 Python 模块路径必须真实存在。"""
    text = _doc_text("docs/secondary-development.md")
    pattern = re.compile(r"`(core/[a-z0-9_/]+\.py)`")
    referenced = set(pattern.findall(text))

    missing = [path for path in referenced if not (REPO_ROOT / path).exists()]

    assert not missing, f"二次开发指南引用了不存在的文件：{missing}"


def test_deployment_manual_lists_all_environment_variables():
    """部署手册必须覆盖 application.yml 里定义的每一个环境变量。"""
    manual = _doc_text("docs/deployment.md")
    config = (REPO_ROOT / "core" / "cloud" / "src" / "main" / "resources" / "application.yml").read_text(
        encoding="utf-8"
    )

    variables = set(re.findall(r"\$\{(VOICE_[A-Z_]+)", config))

    missing = sorted(name for name in variables if name not in manual)

    assert not missing, f"部署手册缺少这些环境变量：{missing}"


def test_deployment_manual_covers_all_ports():
    """部署手册要覆盖实际使用的端口。"""
    manual = _doc_text("docs/deployment.md")

    for port in ("8765", "8080", "1883"):
        assert port in manual, f"部署手册缺少端口 {port}"


def test_deployment_manual_has_troubleshooting_section():
    manual = _doc_text("docs/deployment.md")

    assert "排查路径" in manual
    assert "常见原因" in manual


def test_root_readme_points_to_all_docs():
    """根 README 是入口，必须能导航到全部交付文档。"""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for relative_path in (
        "docs/adr/README.md",
        "docs/interface-contract/README.md",
        "docs/deployment.md",
        "docs/known-limitations.md",
        "docs/secondary-development.md",
        "core/README.md",
    ):
        assert relative_path in readme, f"根 README 未链接 {relative_path}"


def test_root_readme_quickstart_command_is_runnable():
    """根 README 的启动命令必须与实际脚本一致 —— 拼错的命令没人会发现。"""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start_script = (REPO_ROOT / "core" / "scripts" / "start.ps1").read_text(encoding="utf-8")

    assert "core\\scripts\\start.ps1" in readme
    assert "core.edge.simulator" in readme
    # 启动脚本与 README 必须给出同一个模拟端命令。
    assert "core.edge.simulator" in start_script
