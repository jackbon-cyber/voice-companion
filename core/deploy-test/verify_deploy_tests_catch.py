"""验证新增的部署回归测试**真的会失败**（反证）。

测试的价值在于"坏了能报"。这里故意破坏三处，
确认对应的测试会红 —— 而不是绿着放行。

做法：临时改文件 → 跑测试 → 恢复 → 确认恢复后绿。

**为什么值得单独做这一步**：这三条测试钉的都是**文档与配置**，
而文档漂移恰恰是"改了没人发现"的典型。钉子钉歪了（钉到了不相关的地方）
比不钉更糟 —— 它会给出虚假的安心感。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = "core/tests/protocol/test_delivery_docs.py"


def _run_tests() -> tuple[bool, str]:
    """跑交付文档测试。

    @return: (是否全绿, 输出摘要)
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "--no-header", "-x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return result.returncode == 0, result.stdout[-2000:]


def _check_breaks_it(relative_path: str, old: str, new: str, expected_test: str) -> None:
    """破坏一处内容，确认对应测试会失败，然后恢复。

    @param relative_path 相对仓库根的文件路径
    @param old 被替换的内容
    @param new 替换成的内容
    @param expected_test 预期会失败的测试名
    """
    target = REPO_ROOT / relative_path
    original = target.read_text(encoding="utf-8")

    if old not in original:
        raise SystemExit(f"★ 未找到待破坏内容：{relative_path} 中的 {old!r}")

    try:
        target.write_text(original.replace(old, new, 1), encoding="utf-8")
        passed, output = _run_tests()
        if passed:
            raise SystemExit(
                f"★ 破坏 {relative_path} 后测试仍然全绿 —— "
                f"{expected_test} 没咬住这个缺陷"
            )
        if expected_test not in output:
            raise SystemExit(
                f"★ 破坏 {relative_path} 后失败的不是预期测试 {expected_test}，输出：\n{output}"
            )
        print(f"✓ {expected_test} 咬住了 {relative_path} 的缺陷")
    finally:
        target.write_text(original, encoding="utf-8")


def main() -> None:
    print("=== 反证：确认新增的部署回归测试真的会失败 ===")
    print()

    # 基线：不动任何东西时必须全绿
    passed, output = _run_tests()
    if not passed:
        raise SystemExit(f"★ 基线就不绿，无法做反证：\n{output}")
    print("✓ 基线全绿")
    print()

    # 反证 1：把 pom.xml 的 resources 声明去掉 → schema 不进 jar
    _check_breaks_it(
        "core/cloud/pom.xml",
        "<resources>",
        "<resources_DISABLED>",
        "test_protocol_schemas_are_packaged_into_the_jar",
    )

    # 反证 2：把启动顺序里的嵌入服务删掉
    _check_breaks_it(
        "docs/deployment.md",
        "ChromaDB → 嵌入服务 → 云端后端 → 端侧模拟端",
        "ChromaDB → 云端后端 → 端侧模拟端",
        "test_deployment_docs_cover_embedding_service",
    )

    # 反证 3：把 Python 3.13 的要求删掉
    _check_breaks_it(
        "docs/deployment.md",
        "Python | **3.13**",
        "Python | **3.8**",
        "test_deployment_docs_state_target_machine_prerequisites",
    )

    print()
    # 恢复后必须重新变绿
    passed, output = _run_tests()
    if not passed:
        raise SystemExit(f"★ 恢复后仍然不绿：\n{output}")
    print("✓ 全部恢复后测试重新全绿")


if __name__ == "__main__":
    main()

