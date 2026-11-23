"""PowerShell 脚本的编码与语法守门测试。

**这个测试回答什么问题**

"脚本在 Windows 上能不能被 PowerShell 正确执行？"

这里守的是一条**真实踩过的坑**：Windows PowerShell 5.1 读取**无 BOM** 的
``.ps1`` 文件时，默认按系统 ANSI 代码页（中文机器上是 GBK）解码 ——
而不是按 UTF-8。文件里的中文注释会被解成乱码，
乱码里如果出现 ``{`` ``}`` ``"`` 等字符，**整个脚本的语法就崩了**。

**实际后果**：``chroma.ps1`` 因为去掉了 BOM，第 71 行的一句中文注释
被 GBK 误解后引入了未配对的引号，PowerShell 报
``ParserError: UnexpectedToken`` —— 脚本**整个无法执行**。

而这类失败的排查方向极具误导性：报错指向"某个中文 token"，
而真正的原因是"文件少了 3 个字节"。

**为什么不用"跑一遍脚本"来检测**：脚本会真的启动服务、占端口。
语法检查用 PowerShell 的解析器，**不执行任何语句**。

**为什么必须用 PowerShell 解析器而不是文本匹配**：文本匹配只能查括号配对，
查不出编码问题与未闭合的引号。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# 仓库根。测试位于 core/tests/scripts/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 全部 PowerShell 脚本。
SCRIPT_DIRS = ("core/scripts", "device-ref", "tools")

# Windows PowerShell 的 UTF-8 BOM 字节序。
UTF8_BOM = b"\xef\xbb\xbf"


def _all_scripts() -> list[Path]:
    """收集仓库里的全部 PowerShell 脚本。

    @return: 脚本路径列表
    """
    scripts: list[Path] = []
    for directory in SCRIPT_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        scripts.extend(base.rglob("*.ps1"))
    return sorted(scripts)


def _parse_errors(script: Path) -> list[str]:
    """用 PowerShell 解析器检查脚本语法（**不执行**）。

    @param script 脚本路径
    @return: 错误信息列表；无错误时为空
    """
    command = (
        "$errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors) { $errors | ForEach-Object { "
        "\"行 $($_.Extent.StartLineNumber): $($_.Message)\" } }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize(
    "script",
    _all_scripts(),
    ids=lambda path: path.name,
)
def test_script_has_utf8_bom(script: Path):
    """PowerShell 脚本必须带 UTF-8 BOM。

    为什么：Windows PowerShell 5.1 读取无 BOM 的 .ps1 时按 ANSI 代码页
    解码，中文注释会被解成乱码；乱码中的引号或括号会让整个脚本语法崩溃。
    实际踩过：chroma.ps1 去掉 BOM 后第 71 行中文注释引入未配对引号，
    脚本完全无法执行，而报错指向"某个中文 token"，极具误导性。

    **为什么 BOM 不算脏**：BOM 是这类文件格式的一部分，不是编码污染。
    Python 源码、C 源码都不需要它，但 .ps1 需要 ——
    这是工具链的约定，不是疏忽。
    """
    raw = script.read_bytes()

    assert raw.startswith(UTF8_BOM), (
        f"{script.name} 缺少 UTF-8 BOM —— "
        f"Windows PowerShell 会按 ANSI 代码页解码，中文注释将变成乱码，"
        f"并可能让脚本语法崩溃。修复：文件开头写入 EF BB BF 三字节。"
    )


@pytest.mark.parametrize(
    "script",
    _all_scripts(),
    ids=lambda path: path.name,
)
def test_script_parses_without_errors(script: Path):
    """脚本必须能被 PowerShell 解析器读通（**不执行**）。

    为什么：语法错误会让脚本整体不可用。而 PowerShell 的报错信息
    对中文脚本常常指向错误的行 —— 没有自动检查的话，
    这类问题要到实际运行时才暴露。
    """
    errors = _parse_errors(script)

    assert not errors, f"{script.name} 存在语法错误：\n" + "\n".join(errors)


def test_at_least_one_script_found():
    """必须真的找到脚本 —— 否则上面的参数化测试会空跑，假装全绿。

    为什么：路径写错时 pytest 的参数化会收集到 0 个用例，
    测试显示"通过"，实际什么都没检查。
    """
    assert _all_scripts(), "没有找到任何 PowerShell 脚本，测试路径可能写错了"
