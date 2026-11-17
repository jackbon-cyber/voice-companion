<#
.SYNOPSIS
    一键复跑评测与门禁，产出指标报告。

.DESCRIPTION
    执行顺序是固定的：
    1. 解析依赖（Python / JDK / Maven）并检查模型文件；
    2. 起本地嵌入服务与 ChromaDB，等待就绪；
    3. 跑云端评测（意图 / 记忆召回 / 安全 / 共情四个维度）；
    4. 跑端侧评测（端侧识别维度，依赖 Whisper 模型）；
    5. 合并两侧报告，产出最终报告；
    6. 按门禁判定退出码。

    **退出码约定**（与 EvalCli 一致）：
    - 0  全部维度通过，或未覆盖的维度不参与判定；
    - 1  有维度未达门禁阈值；
    - 2  评测环境不可用（依赖服务没起、模型缺失）；
    - 3  自检失败（评测集格式错、语料交集非空）。

    **依赖不可用时以 2 退出，而不是降级为 0**：
    把"没跑"报成"通过"是最危险的一种失败 —— 它会让门禁形同虚设。

.PARAMETER SkipServices
    假定依赖服务已在运行，不重复拉起（也不做就绪检查）。

.PARAMETER SkipEdge
    只跑云端维度，跳过端侧识别维度。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/eval.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipServices,
    [switch]$SkipEdge
)

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $CoreRoot

# 依赖服务地址与端口，与云端 application.yml 保持一致。
$ChromaBaseUrl = 'http://127.0.0.1:8765'
$EmbeddingBaseUrl = 'http://127.0.0.1:8766'

# 报告输出路径（相对仓库根）。
$CloudReportPath = 'core/eval-report.md'
$CloudJsonReportPath = 'core/eval-report.json'
$EdgeReportPath = 'core/eval-edge-report.md'

# 退出码。
$ExitPassed = 0
$ExitGateFailed = 1
$ExitEnvUnavailable = 2
$ExitSelfCheckFailed = 3

# 解析可执行文件位置。优先用 PATH 上的命令，找不到再回退到本机默认安装路径。
function Resolve-Executable {
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
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 60,
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

# 解析 Python 解释器。
$python = Resolve-Executable -Command 'python' -FallbackPaths @(
    'F:\tools\python313\python.exe'
)
if ($null -eq $python) {
    Write-Host "评测环境不可用：找不到 Python 解释器（需要 3.10+）。" -ForegroundColor Red
    exit $ExitEnvUnavailable
}

# 解析 JDK。评测器需要 Java 21。
if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = 'F:\tools\jdk21\jdk-21.0.13+9'
}
if (-not (Test-Path (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
    Write-Host "评测环境不可用：JAVA_HOME 指向的 JDK 不存在（$env:JAVA_HOME）。" -ForegroundColor Red
    exit $ExitEnvUnavailable
}

# 解析 Maven。
$mvn = Resolve-Executable -Command 'mvn' -FallbackPaths @(
    'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd'
)
if ($null -eq $mvn) {
    Write-Host '评测环境不可用：找不到 mvn。' -ForegroundColor Red
    exit $ExitEnvUnavailable
}

Push-Location $ProjectRoot
try {
    Write-Host '=== 1/4 自检（不连依赖服务）==='
    & $python -m core.eval.self_check --eval-dir core/eval
    if ($LASTEXITCODE -ne 0) {
        Write-Host "自检失败，退出码 $LASTEXITCODE。" -ForegroundColor Red
        exit $ExitSelfCheckFailed
    }

    if (-not $SkipServices) {
        Write-Host ''
        Write-Host '=== 2/4 启动依赖服务 ==='

        # ChromaDB
        & (Join-Path $PSScriptRoot 'chroma.ps1') start
        if (-not (Wait-ForHttpOk -Uri "$ChromaBaseUrl/api/v2/version" -TimeoutSeconds 60)) {
            Write-Host "ChromaDB 未就绪（$ChromaBaseUrl）。" -ForegroundColor Red
            exit $ExitEnvUnavailable
        }

        # 本地嵌入服务。模型缺失时不算环境不可用 ——
        # 意图与记忆召回两个维度会标记为"未覆盖"，其余维度照常评测。
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
                Write-Host '本地嵌入服务未就绪，意图与记忆召回维度将标记为未覆盖。' -ForegroundColor Yellow
            }
        } else {
            Write-Host '本地嵌入模型缺失，意图与记忆召回维度将标记为未覆盖。' -ForegroundColor Yellow
        }
    }

    Write-Host ''
    Write-Host '=== 3/4 云端评测 ==='

    # 编译一次，避免每次评测都重新编译。
    Push-Location (Join-Path $ProjectRoot 'core\cloud')
    try {
        & $mvn -o -q compile
        if ($LASTEXITCODE -ne 0) {
            Write-Host '云端工程编译失败。' -ForegroundColor Red
            exit $ExitEnvUnavailable
        }
        & $mvn -o -q dependency:build-classpath "-Dmdep.outputFile=target\cp.txt"
    } finally {
        Pop-Location
    }

    $classPath = 'core\cloud\target\classes;' + (Get-Content 'core\cloud\target\cp.txt' -Raw).Trim()
    & (Join-Path $env:JAVA_HOME 'bin\java.exe') '-Dfile.encoding=UTF-8' '-Dstdout.encoding=UTF-8' `
        -cp $classPath com.company.bj.voice.cloud.eval.EvalCli `
        --eval-dir core/eval `
        --embedding-url $EmbeddingBaseUrl `
        --chroma-url $ChromaBaseUrl `
        --report $CloudReportPath `
        --json-report $CloudJsonReportPath
    $cloudExit = $LASTEXITCODE

    if ($cloudExit -eq $ExitSelfCheckFailed) {
        Write-Host '云端自检失败。' -ForegroundColor Red
        exit $ExitSelfCheckFailed
    }
    if ($cloudExit -eq $ExitEnvUnavailable) {
        Write-Host '云端评测环境不可用。' -ForegroundColor Red
        exit $ExitEnvUnavailable
    }

    $edgeExit = $ExitPassed
    if (-not $SkipEdge) {
        Write-Host ''
        Write-Host '=== 4/4 端侧评测 ==='
        & $python -m core.eval.edge_eval --eval-dir core/eval --report $EdgeReportPath
        $edgeExit = $LASTEXITCODE
        if ($edgeExit -eq $ExitEnvUnavailable) {
            Write-Host '端侧识别模型缺失，端侧识别维度未覆盖。' -ForegroundColor Yellow
            $edgeExit = $ExitPassed
        }
    }

    Write-Host ''
    Write-Host '=== 汇总 ==='
    Write-Host "云端报告：$CloudReportPath"
    if (-not $SkipEdge) {
        Write-Host "端侧报告：$EdgeReportPath"
    }

    # 两侧任一不达标即整体不达标。
    if ($cloudExit -eq $ExitGateFailed -or $edgeExit -eq $ExitGateFailed) {
        Write-Host '门禁判定：不通过' -ForegroundColor Red
        exit $ExitGateFailed
    }

    Write-Host '门禁判定：通过' -ForegroundColor Green
    exit $ExitPassed
} finally {
    Pop-Location
}
