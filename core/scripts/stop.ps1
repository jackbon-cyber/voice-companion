<#
.SYNOPSIS
    停止语音陪伴机器人的本地环境（云端后端 → ChromaDB）。

.DESCRIPTION
    停止顺序与启动相反：先停后端，再停 Chroma。
    先停 Chroma 会让后端在退出过程中反复重试连接，拖慢退出。

    幂等：某个组件本来就没在运行时，不报错。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/stop.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$CloudRoot = Join-Path $CoreRoot 'cloud'

# 后端监听端口。
$BackendPort = 8080

function Stop-ProcessOnPort {
    <#
    .SYNOPSIS
        停止占用指定端口的进程。
    #>
    param([Parameter(Mandatory = $true)][int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $connections) {
        Write-Host "端口 $Port 上没有监听进程，跳过"
        return
    }
    foreach ($connection in $connections) {
        $processId = $connection.OwningProcess
        if ($processId -le 0) {
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }
        Write-Host "停止进程 $($process.ProcessName)（PID $processId，端口 $Port）"
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Warning "停止进程 $processId 失败：$_"
        }
    }
}

Write-Host '=== 停止云端后端 ==='
Stop-ProcessOnPort -Port $BackendPort

Write-Host ''
Write-Host '=== 停止 ChromaDB ==='
& (Join-Path $PSScriptRoot 'chroma.ps1') stop

Write-Host ''
Write-Host '停止完成。'
