<#
.SYNOPSIS
    端到端验证：跨用户记忆隔离与离线降级。

.DESCRIPTION
    这是"一键复现"的入口 —— 从零依赖到出报告，一条命令跑完。

    步骤：
    1. 启动依赖（ChromaDB、本地嵌入服务、云端后端）；
    2. 跑端到端断言（跨用户记忆隔离 + 离线降级）；
    3. 跑评测与协议门禁；
    4. 汇总产出报告。

    **不自动停止依赖**：依赖是共享资源，跑完就停会让"连着跑几次看稳定性"
    变得很慢。用 `-StopOnExit` 显式要求停止。

.PARAMETER SkipServices
    假定依赖已在运行，跳过启动步骤。

.PARAMETER SkipEval
    跳过评测步骤，只跑端到端断言。

.PARAMETER StopOnExit
    结束时停止依赖服务。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/e2e.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipServices,
    [switch]$SkipEval,
    [switch]$StopOnExit
)

$ErrorActionPreference = 'Stop'

# 退出码。
$ExitPassed = 0
$ExitFailed = 1
$ExitEnvUnavailable = 2

$CoreRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $CoreRoot

# 本地嵌入服务地址。
$EmbeddingBaseUrl = 'http://127.0.0.1:8766'

# Chroma 地址。
$ChromaBaseUrl = 'http://127.0.0.1:8765'

# 云端上行地址。
$UplinkUrl = 'ws://127.0.0.1:8080/voice/uplink'

# 报告输出目录。
$ReportDir = Join-Path $ProjectRoot 'data\reports'

# 最终指标报告（三份产物合成的可交付报告）。
$FinalReportPath = Join-Path $ReportDir 'final-report.md'

# Python 解释器。
$PythonExe = 'F:\tools\python313\python.exe'

function Resolve-Executable {
    <#
    .SYNOPSIS
        解析可执行文件路径。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$FallbackPaths = @()
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -ne $resolved) {
        return $resolved.Source
    }
    foreach ($candidate in $FallbackPaths) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Wait-ForHttpOk {
    <#
    .SYNOPSIS
        轮询等待某个地址返回 200。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 90,
        [int]$IntervalSeconds = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            # 未就绪，继续等待。
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
    return $false
}

$python = Resolve-Executable -Command 'python' -FallbackPaths @($PythonExe)
if ($null -eq $python) {
    Write-Host "环境不可用：找不到 Python 解释器（需要 3.10+）。" -ForegroundColor Red
    exit $ExitEnvUnavailable
}

if (-not $SkipServices) {
    Write-Host '=== 1/4 启动依赖服务 ==='
    & (Join-Path $PSScriptRoot 'start.ps1')

    # 本地嵌入服务：记忆召回依赖它。缺失时端到端隔离无法判定。
    $EmbeddingModelPath = Join-Path $ProjectRoot 'core\models\embedding\model.onnx'
    if (Test-Path $EmbeddingModelPath) {
        $embeddingLog = Join-Path $ProjectRoot 'data\embedding.out.log'
        $embeddingErrLog = Join-Path $ProjectRoot 'data\embedding.err.log'
        if (-not (Test-Path (Split-Path -Parent $embeddingLog))) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $embeddingLog) -Force | Out-Null
        }
        Start-Process -FilePath $python `
            -ArgumentList '-m', 'core.edge.embedding.service', '--port', '8766', `
            '--model-dir', 'core/models/embedding' `
            -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $embeddingLog -RedirectStandardError $embeddingErrLog | Out-Null
        if (-not (Wait-ForHttpOk -Uri "$EmbeddingBaseUrl/v1/health" -TimeoutSeconds 90)) {
            Write-Host '本地嵌入服务未就绪 —— 记忆召回不可用，端到端隔离无法判定。' -ForegroundColor Red
            exit $ExitEnvUnavailable
        }
        Write-Host "本地嵌入服务已就绪：$EmbeddingBaseUrl"
    } else {
        Write-Host '本地嵌入模型缺失 —— 记忆召回不可用，端到端隔离无法判定。' -ForegroundColor Red
        Write-Host "请先运行：powershell -File core/scripts/fetch-models.ps1" -ForegroundColor Yellow
        exit $ExitEnvUnavailable
    }
} else {
    Write-Host '=== 1/4 跳过依赖服务启动 ==='
}

Write-Host ''
Write-Host '=== 2/4 协议门禁 ==='
try {
    & (Join-Path $PSScriptRoot 'validate-protocol.ps1')
} catch {
    Write-Host "协议门禁未通过：$_" -ForegroundColor Red
    exit $ExitFailed
}

Write-Host ''
Write-Host '=== 3/4 端到端断言 ==='
$e2eReport = Join-Path $ReportDir 'e2e-report.json'
Push-Location $ProjectRoot
try {
    & $python -m core.e2e.isolation --url $UplinkUrl --report $e2eReport
    $e2eExit = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($e2eExit -eq $ExitEnvUnavailable) {
    Write-Host '端到端环境不可用。' -ForegroundColor Red
    exit $ExitEnvUnavailable
}
if ($e2eExit -ne $ExitPassed) {
    Write-Host '端到端断言未通过。' -ForegroundColor Red
    if (-not $SkipEval) {
        Write-Host '（评测仍然执行 —— 端到端失败与评测结果要分开看）' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '=== 4/4 评测 ==='
$evalExit = $ExitPassed
if (-not $SkipEval) {
    & (Join-Path $PSScriptRoot 'eval.ps1')
    $evalExit = $LASTEXITCODE
    if ($evalExit -ne $ExitPassed) {
        Write-Host '评测未通过。' -ForegroundColor Red
    }
} else {
    Write-Host '跳过评测'
}

if ($StopOnExit) {
    Write-Host ''
    Write-Host '=== 停止依赖服务 ==='
    & (Join-Path $PSScriptRoot 'stop.ps1')
}

    Write-Host ''
    Write-Host '=== 汇总 ==='
    Write-Host "端到端报告：$e2eReport"

    # 最终指标报告：三份产物（云端评测 / 端侧评测 / 端到端断言）合成一份。
    #
    # **为什么放在端到端脚本而不是评测脚本**：评测脚本产出云端与端侧两份，
    # 但没有端到端断言结果 —— 而"跨用户泄漏 0 条"这种结论必须与
    # "记忆召回 100%"放在同一份报告里，读者才能判断这两件事是否自洽。
    # 放在一起，也避免出现"三份报告各自通过，合起来不知道行不行"的情况。
    if ($e2eExit -ne $ExitEnvUnavailable) {
        Write-Host ''
        Write-Host '=== 最终指标报告 ==='
        Push-Location $ProjectRoot
        try {
            & $python -m core.e2e.final_report --output $FinalReportPath
            if ($LASTEXITCODE -ne 0) {
                Write-Host '最终报告不完整 —— 存在未产出报告的维度。' -ForegroundColor Red
            }
        } finally {
            Pop-Location
        }
        Write-Host "最终报告：$FinalReportPath"
    }

    if ($e2eExit -ne $ExitPassed -or $evalExit -ne $ExitPassed) {
        Write-Host '端到端验证未全部通过。' -ForegroundColor Red
        exit $ExitFailed
    }

    Write-Host '端到端验证全部通过。' -ForegroundColor Green
    exit $ExitPassed
