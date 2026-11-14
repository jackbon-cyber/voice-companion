<#
.SYNOPSIS
    启动语音陪伴机器人的本地环境（ChromaDB → 云端后端）。

.DESCRIPTION
    启动顺序是固定的：
    1. 起 ChromaDB，并等待其健康检查通过；
    2. 起云端后端（Maven），并等待其健康检查返回 UP。

    Chroma 必须先于后端起来 —— 后端启动时会做一次 Chroma 连通性检查，
    Chroma 没就绪会让后端启动失败。

    端侧模型**不自动启动**：模拟端是交互式程序，由使用者手动运行。

.PARAMETER SkipBackend
    只起 Chroma，不起后端。

.PARAMETER SkipChroma
    跳过 Chroma 启动（假定已在运行）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/start.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipChroma
)

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$CloudRoot = Join-Path $CoreRoot 'cloud'

# Chroma 监听地址与端口，与云端配置保持一致。
$ChromaHost = '127.0.0.1'
$ChromaPort = 8765
$ChromaHealthUri = "http://$ChromaHost`:$ChromaPort/api/v2/version"

# 云端后端端口。
$BackendPort = 8080
$BackendHealthUri = "http://127.0.0.1:$BackendPort/api/health"

# 环境变量占位。真实凭据一律走环境变量，仓库内不出现。
$env:JAVA_HOME = if ($env:JAVA_HOME) { $env:JAVA_HOME } else { 'F:\tools\jdk21\jdk-21.0.13+9' }
$env:VOICE_CHROMA_BASE_URL = "http://$ChromaHost`:$ChromaPort"

function Wait-ForHttpOk {
    <#
    .SYNOPSIS
        轮询等待某个地址返回 200。
    #>
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

if (-not $SkipChroma) {
    Write-Host '=== 启动 ChromaDB ==='
    & (Join-Path $PSScriptRoot 'chroma.ps1') start
    Write-Host '等待 ChromaDB 就绪...'
    if (-not (Wait-ForHttpOk -Uri $ChromaHealthUri -TimeoutSeconds 60)) {
        throw "ChromaDB 在 60 秒内未就绪（$ChromaHealthUri）。请检查 scripts/chroma.ps1 start 的输出。"
    }
    Write-Host "ChromaDB 已就绪：$ChromaHealthUri"
} else {
    Write-Host '跳过 ChromaDB 启动（假定已在运行）'
}

if ($SkipBackend) {
    Write-Host '跳过云端后端启动'
Write-Host ''
Write-Host '启动完成。端侧模拟端请手动运行（在仓库根目录）：'
Write-Host '  F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink'
exit 0
}

Write-Host ''
Write-Host '=== 启动云端后端 ==='

# Maven 可执行文件：优先用 PATH 上的 mvn。
$mvn = Get-Command mvn -ErrorAction SilentlyContinue
if ($null -eq $mvn) {
    $mvnFallback = 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd'
    if (-not (Test-Path $mvnFallback)) {
        throw '找不到 mvn。请把 Maven 加入 PATH，或设置 $env:MAVEN_HOME。'
    }
    $mvn = $mvnFallback
}

Push-Location $CloudRoot
try {
    # 日志落盘：后台进程没有窗口，出错时无处可查。开发期落文件，便于定位启动失败与运行期异常。
    $LogDir = Join-Path $CloudRoot 'logs'
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    $StdOutLog = Join-Path $LogDir 'backend.out.log'
    $StdErrLog = Join-Path $LogDir 'backend.err.log'

    $backend = Start-Process -FilePath $mvn -ArgumentList 'spring-boot:run' `
        -WorkingDirectory $CloudRoot -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog
} finally {
    Pop-Location
}

Write-Host "云端后端进程已启动（PID $($backend.Id)）"
Write-Host '等待后端就绪...'
if (-not (Wait-ForHttpOk -Uri $BackendHealthUri -TimeoutSeconds 180)) {
    throw "云端后端在 180 秒内未就绪（$BackendHealthUri）。请检查日志：$StdOutLog"
}
Write-Host "云端后端已就绪：$BackendHealthUri"
Write-Host "后端日志：$StdOutLog"

Write-Host ''
Write-Host '启动完成。端侧模拟端请手动运行（在仓库根目录）：'
Write-Host '  F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink'
