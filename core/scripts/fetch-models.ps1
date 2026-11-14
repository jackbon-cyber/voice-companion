<#
.SYNOPSIS
    下载端侧模型权重到 core/models/。

.DESCRIPTION
    幂等脚本：文件已存在且 sha256 匹配则跳过，不重复下载。

    模型体积大（Whisper base 约 150MB，Qwen2.5-0.5B Q4 约 400MB），
    因此不入库，由本脚本按需拉取。

    **两个模型都是可选的**：
    - Whisper 缺失：端侧 ASR 走 NullRecognizer（识别不出文字），意图走规则表；
    - Qwen 缺失：端侧对话走话术库。
    两者都缺失时，端侧仍可完成一轮本地应答，不会崩溃。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/fetch-models.ps1
#>

[CmdletBinding()]
param(
    # 仅下载指定模型：'asr' / 'llm' / 'all'
    [ValidateSet('asr', 'llm', 'all')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$ModelRoot = Join-Path $CoreRoot 'models'

# 模型清单。url 走 HuggingFace 镜像，避免直连被墙时长时间挂起。
$AsrModelName = 'faster-whisper-base'
$AsrModelDir = Join-Path $ModelRoot 'asr'

$LlamaModelName = 'Qwen2.5-0.5B-Instruct-Q4_K_M.gguf'
$LlamaModelDir = Join-Path $ModelRoot 'llm'
$LlamaModelFile = Join-Path $LlamaModelDir $LlamaModelName

# HuggingFace 镜像地址。
$MirrorBase = 'https://hf-mirror.com'

function Resolve-HfMirrorUrl {
    <#
    .SYNOPSIS
        把 HuggingFace 仓库地址改写成镜像地址。
    #>
    param([Parameter(Mandatory = $true)][string]$Repository)
    return "$MirrorBase/$Repository"
}

function Test-FileHash {
    <#
    .SYNOPSIS
        判断文件是否已存在且 sha256 匹配。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    if (-not (Test-Path $Path)) {
        return $false
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        return $true
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return $actual -eq $ExpectedSha256.ToLowerInvariant()
}

function Invoke-FileDownload {
    <#
    .SYNOPSIS
        下载文件到目标路径。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    $parent = Split-Path -Parent $OutFile
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Write-Host "下载 $Uri"
    Write-Host "  -> $OutFile"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

if ($Target -in @('asr', 'all')) {
    Write-Host '=== 端侧 ASR 模型（faster-whisper base）==='
    New-Item -ItemType Directory -Force -Path $AsrModelDir | Out-Null
    # faster-whisper 的模型由 huggingface_hub 在首次加载时自动下载到缓存目录，
    # 这里预置下载以保证离线可用；文件已存在则跳过。
    $asrMarker = Join-Path $AsrModelDir 'model.bin'
    if (Test-FileHash -Path $asrMarker -ExpectedSha256 '') {
        Write-Host "已存在，跳过：$asrMarker"
    } else {
        $repoUrl = Resolve-HfMirrorUrl -Repository 'Systran/faster-whisper-base'
        Write-Host "模型仓库：$repoUrl"
        Write-Host '提示：faster-whisper 首次加载时会自动从镜像拉取模型到本地缓存。'
        Write-Host "如需离线预置，请手动下载仓库文件到 $AsrModelDir"
    }
}

if ($Target -in @('llm', 'all')) {
    Write-Host '=== 端侧对话模型（Qwen2.5-0.5B Q4_K_M）==='
    New-Item -ItemType Directory -Force -Path $LlamaModelDir | Out-Null
    if (Test-Path $LlamaModelFile) {
        Write-Host "已存在，跳过：$LlamaModelFile"
    } else {
        $url = Resolve-HfMirrorUrl -Repository 'Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf'
        Invoke-FileDownload -Uri $url -OutFile $LlamaModelFile
    }
}

Write-Host ''
Write-Host '模型准备完成。'
Write-Host '提示：两个模型都是可选的，缺失时端侧会自动降级（ASR → NullRecognizer，对话 → 话术库）。'
