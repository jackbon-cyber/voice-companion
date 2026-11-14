<#
.SYNOPSIS
    校验端云协议 schema 与样例。

.DESCRIPTION
    两层校验：
    1. **schema 自检** —— 每份 schema 本身是合法的 JSON Schema（Draft 2020-12）；
    2. **样例校验** —— 用共享样例集 `core/cloud/src/test/resources/protocol-samples/samples.json`
       逐条校验，并核对"期望结论"（valid / invalid）与实际结论一致。

    样例集是 Python 与 Java 两侧共用的：两侧对同一批消息的判定必须一致，
    不一致就说明有一侧解析 `$ref` 或类型约束的行为与 schema 不符。

    退出码：
    - 0  全部通过
    - 1  校验失败（有样例的实际结论与期望不符，或 schema 非法）

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/validate-protocol.ps1
#>

[CmdletBinding()]
param(
    # 只做 schema 自检，不校验样例。
    [switch]$SchemaOnly
)

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$SchemaDir = Join-Path $CoreRoot 'protocol\schema'
$SamplesPath = Join-Path $CoreRoot 'cloud\src\test\resources\protocol-samples\samples.json'
$PythonExe = 'F:\tools\python313\python.exe'

if (-not (Test-Path $SchemaDir)) {
    throw "找不到协议 schema 目录：$SchemaDir"
}

$schemas = Get-ChildItem -Path $SchemaDir -Filter '*.schema.json' | Sort-Object Name
if ($schemas.Count -eq 0) {
    throw "协议 schema 目录为空：$SchemaDir"
}

Write-Host "=== 校验 $($schemas.Count) 份 schema ==="

# 校验逻辑写在 Python 侧：协议校验的**唯一实现**在 `core.protocol.validator`，
# 脚本再写一份就出现了第二个实现，两处漂移会掩盖真实问题。
$script = @'
import json
import sys
from pathlib import Path

# 仓库根 = 本脚本所在目录的上一级（临时脚本生成在 core/ 下）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.protocol.loader import SCHEMA_NAMES, load_schema
from core.protocol.validator import build_validator, validation_errors

samples_path = Path(sys.argv[1])
schema_only = len(sys.argv) > 2 and sys.argv[2] == "schema-only"

failures = []

for name in SCHEMA_NAMES:
    try:
        load_schema(name)
        build_validator(name)
        print(f"  [OK]   schema {name}")
    except Exception as error:
        failures.append(f"schema {name} 非法：{error}")
        print(f"  [FAIL] schema {name}：{error}")

if schema_only:
    if failures:
        print(f"\n共 {len(failures)} 项失败。")
        sys.exit(1)
    print("\n全部 schema 通过。")
    sys.exit(0)

samples = json.loads(samples_path.read_text(encoding="utf-8"))["samples"]
for sample in samples:
    name = sample["schema"]
    expected = sample["valid"]
    actual = not validation_errors(name, sample["payload"])
    note = sample.get("note", "")
    if actual != expected:
        failures.append(f"样例 [{name}] {note}：期望 valid={expected}，实际 valid={actual}")
        print(f"  [FAIL] 样例 [{name}] {note}：期望 valid={expected}，实际 valid={actual}")
    else:
        print(f"  [OK]   样例 [{name}] {note}（valid={actual}）")

print(f"\n共校验 {len(samples)} 条样例。")
if failures:
    print(f"共 {len(failures)} 项失败：")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("全部通过。")
sys.exit(0)
'@

$tempScript = Join-Path $CoreRoot ('.validate_protocol_{0}.py' -f [guid]::NewGuid())
Set-Content -Path $tempScript -Value $script -Encoding UTF8

try {
    $argList = @($tempScript, $SamplesPath)
    if ($SchemaOnly) {
        $argList += 'schema-only'
    }
    Push-Location $CoreRoot
    try {
        & $PythonExe $argList
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item $tempScript -Force -ErrorAction SilentlyContinue
}

if ($exitCode -ne 0) {
    throw "协议校验未通过，退出码 $exitCode。"
}
Write-Host '协议校验通过。'
exit 0
