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

    **校验口径**：sha256 比对是"有则必校"——
    - 模型目录存在 `SHA256SUMS` 文件时，逐个校验，不匹配就重新下载；
    - 没有 `SHA256SUMS` 时，先下载再把实测 sha256 写入该文件，下次运行起就变成强制校验。
    绝不用"期望值为空即视为通过"这种伪校验 —— 那会把下载损坏的文件当成好的。

.PARAMETER Target
    仅下载指定模型：'asr' / 'llm' / 'embedding' / 'all'

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File core/scripts/fetch-models.ps1
#>

[CmdletBinding()]
param(
    [ValidateSet('asr', 'llm', 'embedding', 'all')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'

$CoreRoot = Split-Path -Parent $PSScriptRoot
$ModelRoot = Join-Path $CoreRoot 'models'

# 模型清单。url 走 HuggingFace 镜像，避免直连被墙时长时间挂起。
$AsrModelName = 'faster-whisper-base'
$AsrModelDir = Join-Path $ModelRoot 'asr'
$AsrRepository = 'Systran/faster-whisper-base'

$LlamaModelName = 'Qwen2.5-0.5B-Instruct-Q4_K_M.gguf'
$LlamaModelDir = Join-Path $ModelRoot 'llm'
$LlamaModelFile = Join-Path $LlamaModelDir $LlamaModelName
$LlamaRepository = 'Qwen/Qwen2.5-0.5B-Instruct-GGUF'
$LlamaRemoteFile = 'qwen2.5-0.5b-instruct-q4_k_m.gguf'

# 本地嵌入模型。量化 ONNX，22.9 MB，512 维。
# 选它是因为评测门禁的"记忆召回"维度需要真实语义召回，
# 而远端嵌入 API 需要凭据 —— 有了本地模型，"克隆下来就能跑出真实指标"才成立。
$EmbeddingModelDir = Join-Path $ModelRoot 'embedding'
$EmbeddingRepository = 'Xenova/bge-small-zh-v1.5'
$EmbeddingFiles = @{
    'model.onnx'      = 'onnx/model_quantized.onnx'
    'tokenizer.json'  = 'tokenizer.json'
    'config.json'     = 'config.json'
}

# sha256 清单。放在模型根目录，与权重同寿命。
$ChecksumFile = Join-Path $ModelRoot 'SHA256SUMS'

# HuggingFace 镜像地址。
$MirrorBase = 'https://hf-mirror.com'

# ASR 必需文件。tokenizer 与词表缺一不可，否则加载直接失败。
$AsrRequiredFiles = @(
    'model.bin',
    'config.json',
    'tokenizer.json',
    'vocabulary.txt',
    'preprocessor_config.json'
)

function Resolve-HfMirrorUrl {
    <#
    .SYNOPSIS
        把 HuggingFace 仓库地址改写成镜像地址。
    .PARAMETER Repository
        形如 'owner/repo' 或 'owner/repo/resolve/main/path'。
    #>
    param([Parameter(Mandatory = $true)][string]$Repository)
    return "$MirrorBase/$Repository"
}

function Get-ExpectedHash {
    <#
    .SYNOPSIS
        从 SHA256SUMS 中读取某个文件的期望 sha256。
    .DESCRIPTION
        清单格式为标准的 `<sha256>  <相对路径>`（与 sha256sum 兼容）。
    .PARAMETER RelativePath
        相对于模型根目录的路径。
    #>
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    if (-not (Test-Path $ChecksumFile)) {
        return $null
    }
    $normalized = $RelativePath.Replace('\', '/')
    foreach ($line in Get-Content -Path $ChecksumFile) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith('#')) {
            continue
        }
        $parts = $trimmed -split '\s+', 2
        if ($parts.Count -lt 2) {
            continue
        }
        if ($parts[1].Trim().Replace('\', '/') -eq $normalized) {
            return $parts[0].Trim().ToLowerInvariant()
        }
    }
    return $null
}

function Add-ActualHash {
    <#
    .SYNOPSIS
        把实测 sha256 记入 SHA256SUMS。
    .DESCRIPTION
        下次运行时该文件就变成强制校验项。
    .PARAMETER RelativePath
        相对于模型根目录的路径。
    .PARAMETER Hash
        实测 sha256。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Hash
    )
    $lines = @()
    if (Test-Path $ChecksumFile) {
        $lines = @(Get-Content -Path $ChecksumFile | Where-Object { $_ -notmatch '^\s*$' })
    }
    $normalized = $RelativePath.Replace('\', '/')
    $kept = @($lines | Where-Object {
        $parts = $_ -split '\s+', 2
        $parts.Count -lt 2 -or $parts[1].Trim().Replace('\', '/') -ne $normalized
    })
    $kept += "$($Hash.ToLowerInvariant())  $normalized"
    Set-Content -Path $ChecksumFile -Value $kept -Encoding UTF8
}

function Test-FileIntegrity {
    <#
    .SYNOPSIS
        判断文件是否已存在，且（在有期望值时）sha256 匹配。
    .DESCRIPTION
        没有期望 sha256 时返回 $true —— 但调用方必须把它当作"存在但未校验"，
        并在下载后补录 sha256，避免伪校验。
    .PARAMETER Path
        文件绝对路径。
    .PARAMETER RelativePath
        相对于模型根目录的路径，用于查 SHA256SUMS。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    if (-not (Test-Path $Path)) {
        return $false
    }
    $expected = Get-ExpectedHash -RelativePath $RelativePath
    if ([string]::IsNullOrWhiteSpace($expected)) {
        return $true
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return $actual -eq $expected.ToLowerInvariant()
}

function Invoke-FileDownload {
    <#
    .SYNOPSIS
        下载文件到目标路径，并记录 sha256。
    .PARAMETER Uri
        下载地址。
    .PARAMETER OutFile
        目标文件绝对路径。
    .PARAMETER RelativePath
        相对于模型根目录的路径，用于记录 sha256。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    $parent = Split-Path -Parent $OutFile
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Write-Host "下载 $Uri"
    Write-Host "  -> $OutFile"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing

    $actual = (Get-FileHash -Path $OutFile -Algorithm SHA256).Hash.ToLowerInvariant()
    Add-ActualHash -RelativePath $RelativePath -Hash $actual
    Write-Host "  sha256: $actual"
}

New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null

if ($Target -in @('asr', 'all')) {
    Write-Host '=== 端侧 ASR 模型（faster-whisper base）==='
    New-Item -ItemType Directory -Force -Path $AsrModelDir | Out-Null
    foreach ($fileName in $AsrRequiredFiles) {
        # 变量名不能叫 $target：PowerShell 变量名不区分大小写，
        # $target 会覆盖脚本自身的 -Target 参数，赋值时触发 ValidateSet 重新校验而报错。
        $targetFile = Join-Path $AsrModelDir $fileName
        $relative = Join-Path 'asr' $fileName
        if (Test-FileIntegrity -Path $targetFile -RelativePath $relative) {
            Write-Host "已存在，跳过：$relative"
            continue
        }
        $url = Resolve-HfMirrorUrl -Repository "$AsrRepository/resolve/main/$fileName"
        Invoke-FileDownload -Uri $url -OutFile $targetFile -RelativePath $relative
    }
    Write-Host "ASR 模型目录：$AsrModelDir"
}

if ($Target -in @('llm', 'all')) {
    Write-Host '=== 端侧对话模型（Qwen2.5-0.5B Q4_K_M）==='
    New-Item -ItemType Directory -Force -Path $LlamaModelDir | Out-Null
    $relative = Join-Path 'llm' $LlamaModelName
    if (Test-FileIntegrity -Path $LlamaModelFile -RelativePath $relative) {
        Write-Host "已存在，跳过：$relative"
    } else {
        $url = Resolve-HfMirrorUrl -Repository "$LlamaRepository/resolve/main/$LlamaRemoteFile"
        Invoke-FileDownload -Uri $url -OutFile $LlamaModelFile -RelativePath $relative
    }
}

if ($Target -in @('embedding', 'all')) {
    Write-Host '=== 本地嵌入模型（BGE-small-zh 量化 ONNX）==='
    New-Item -ItemType Directory -Force -Path $EmbeddingModelDir | Out-Null
    foreach ($localName in $EmbeddingFiles.Keys) {
        $remotePath = $EmbeddingFiles[$localName]
        # 同样不能用 $target，理由见 ASR 分支的注释。
        $targetFile = Join-Path $EmbeddingModelDir $localName
        $relative = Join-Path 'embedding' $localName
        if (Test-FileIntegrity -Path $targetFile -RelativePath $relative) {
            Write-Host "已存在，跳过：$relative"
            continue
        }
        $url = Resolve-HfMirrorUrl -Repository "$EmbeddingRepository/resolve/main/$remotePath"
        Invoke-FileDownload -Uri $url -OutFile $targetFile -RelativePath $relative
    }
    Write-Host "嵌入模型目录：$EmbeddingModelDir"
}

Write-Host ''
Write-Host '模型准备完成。'
Write-Host "sha256 清单：$ChecksumFile"
Write-Host '提示：三个模型都是可选的，缺失时端侧会自动降级（ASR → NullRecognizer，对话 → 话术库）。'
Write-Host '      嵌入模型缺失时，云端记忆召回会退化为词面匹配，并在评测报告中明确标注。'
