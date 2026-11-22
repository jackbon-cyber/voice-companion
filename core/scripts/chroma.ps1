<#
.SYNOPSIS
    管理本地 ChromaDB 服务（start / stop / status）。

.DESCRIPTION
    幂等脚本：
    - start 时若目标端口已有 **本工程** 的 Chroma 在监听，则直接报告"已在运行"而不重复拉起；
      若端口被**非 Chroma 进程**占用，则报错退出并打印占用者信息（绝不静默跳过）。
    - stop 时若没有对应进程则报告"未在运行"而不报错；
      只终止经身份校验确认属于本工程 Chroma 的进程，PID 被系统复用时拒绝终止。
    - status 时校验端口属主确实是本工程 Chroma，否则报告"未运行"并说明端口被谁占用。

    归属校验的唯一实现在 Test-ChromaOwnership，start / stop / status 三者复用，
    避免判定逻辑分叉。

    监听地址通过 -ListenHost 显式指定（默认 127.0.0.1），并以 --host 传给 chroma：
    Chroma 的 --host 默认值是 localhost，在本机解析为 IPv6 回环，只会监听 [::1]，
    而 JDK HttpClient 解析 localhost 时优先取 IPv4 且不回退到 IPv6，
    届时工程默认 baseUrl http://localhost:8765 将连接失败。绑定 IPv4 回环可同时满足两端。

    PID 文件默认位于工程根目录 data/chroma/chroma.pid。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/chroma.ps1 start
    powershell -ExecutionPolicy Bypass -File scripts/chroma.ps1 status
    powershell -ExecutionPolicy Bypass -File scripts/chroma.ps1 stop
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status',

    # Chroma 监听端口，与云端 application.yml 的 voice.chroma.base-url 默认端口一致。
    [int]$Port = 8765,

    # Chroma 监听地址。显式绑定 IPv4 回环：Chroma 的 --host 默认值是 localhost，
    # 在本机解析为 IPv6 回环，只会监听 [::1]，导致 JDK HttpClient 走 IPv4 的 localhost 时连接被拒。
    # 参数名不叫 $Host：那会与 PowerShell 内置只读自动变量 $Host 冲突。
    [string]$ListenHost = '127.0.0.1',

    # 数据持久化目录，与云端 application.yml 的 voice.chroma.data-path 默认值一致。
    [string]$DataPath = 'data/chroma'
)

$ErrorActionPreference = 'Stop'

# 解析仓库根目录（脚本位于 <repo>/core/scripts/ 下），保证在任意工作目录下调用行为一致。
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if (-not [System.IO.Path]::IsPathRooted($DataPath)) {
    $DataPath = Join-Path $ProjectRoot $DataPath
}

# 解析 chroma 可执行文件：优先用 PATH 上的命令，解析不到则回退到默认安装路径。
function Resolve-ChromaExecutable {
    $chromaCommand = Get-Command chroma -ErrorAction SilentlyContinue
    if ($null -ne $chromaCommand) {
        return $chromaCommand.Source
    }

    $fallback = 'F:\tools\python313\Scripts\chroma.exe'
    if (Test-Path $fallback) {
        return $fallback
    }

    throw "未找到 chroma 可执行文件。请先执行 scripts/setup-chroma.ps1，或确认 chroma 已在 PATH 中。"
}

# 判断指定端口是否已有服务在监听（不区分协议，仅作为"是否有人占位"的粗筛）。
# 以 netstat 监听表为准：脚本以 --host 显式绑定 IPv4 回环，但判定仍不假设协议族，
# 因为同一端口可能存在 IPv4/IPv6 两条监听记录（如双栈监听），
# 故端口占位与属主查询统一走 netstat，避免两处判定口径不一致。
function Test-PortListening {
    param([int]$ListenPort)

    return ($null -ne (Get-ListeningProcessIdByNetstat -ListenPort $ListenPort))
}

# 取端口的监听属主进程（Win32_Process 对象），无属主时返回 $null。
# 优先用 netstat 解析监听表：Get-NetTCPConnection 是较慢的 CIM/WMI 查询，
# 在本机实测单次调用可达数秒且偶发返回空集合——一旦漏查属主，
# status 会误报"未运行"、start 会重复拉起，故以 netstat 为准并保留 CIM 作为兜底。
function Get-PortOwnerProcess {
    param([int]$ListenPort)

    $ownerProcessId = Get-ListeningProcessIdByNetstat -ListenPort $ListenPort

    if ($null -eq $ownerProcessId) {
        # 兜底：netstat 未解析到时回退到 CIM 查询（慢但覆盖不同实现路径）。
        $connection = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $connection) {
            $ownerProcessId = $connection.OwningProcess
        }
    }

    if ($null -eq $ownerProcessId -or $ownerProcessId -le 0) {
        return $null
    }

    return Get-CimInstance Win32_Process -Filter "ProcessId=$ownerProcessId" -ErrorAction SilentlyContinue
}

# 用 netstat -ano 解析指定端口的监听属主 PID，无监听时返回 $null。
function Get-ListeningProcessIdByNetstat {
    param([int]$ListenPort)

    # 必须用不带 -p 的 netstat：`-p tcp` 只输出 IPv4 记录，
    # 若 Chroma 或其它进程绑定在 IPv6 回环 [::1] 上，带 -p 会漏掉它的监听记录。
    $netstatOutput = netstat -ano 2>$null
    if ([string]::IsNullOrWhiteSpace($netstatOutput)) {
        return $null
    }

    $portPattern = ':' + [regex]::Escape([string]$ListenPort) + '$'
    foreach ($line in $netstatOutput) {
        # netstat -ano 的 TCP 行格式：Proto  本地地址  外部地址  状态  PID
        $columns = ($line.Trim() -split '\s+')
        if ($columns.Count -lt 5) {
            continue
        }
        if ($columns[0] -ne 'TCP') {
            continue
        }
        if ($columns[3] -ne 'LISTENING') {
            continue
        }
        # 本地地址形如 "0.0.0.0:8765" 或 "[::1]:8765"，端口号必须精确相等，
        # 否则 8765 会被 87651 之类的端口误命中。
        if ($columns[1] -notmatch $portPattern) {
            continue
        }

        $parsedProcessId = 0
        if ([int]::TryParse($columns[4], [ref]$parsedProcessId) -and $parsedProcessId -gt 0) {
            return $parsedProcessId
        }
    }

    return $null
}

# 规范化路径用于命令行比对：统一分隔符、去掉末尾分隔符、忽略大小写。
function ConvertTo-NormalizedPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ''
    }

    $normalized = $Path.Trim().Replace('/', '\')
    while ($normalized.Length -gt 1 -and $normalized.EndsWith('\')) {
        $normalized = $normalized.Substring(0, $normalized.Length - 1)
    }

    return $normalized.ToLowerInvariant()
}

<#
.SYNOPSIS
    Chroma 进程归属校验——本脚本唯一的身份判定实现。
.DESCRIPTION
    同时被 start / stop / status 复用，保证三处对"这是不是本工程的 Chroma"的判断完全一致。

    判定条件（全部满足才算本工程 Chroma）：
    1. 命令行含 chroma 可执行文件特征（chroma.exe / chromadb 等），排除同名误伤；
    2. 命令行含 `--port <监听端口>`，且端口号与本进程实际监听的端口一致；
    3. 命令行含 `--path <本工程数据目录>`，且路径规范化后与本工程数据目录一致。
       第 3 条是精准匹配的关键：它把进程绑定到"本工程这一次部署"，
       既避免跨参数宽松匹配误杀其它 python 进程，也避免误伤别的工程目录下的 Chroma。

    仅在命令行同时出现 chroma 特征与 `--path` 时才启用路径比对；
    退化情形（命令行被截断）会被判定为非本工程 Chroma，属于安全的保守方向。
.PARAMETER Process
    待校验的 Win32_Process 对象。
.PARAMETER ListenPort
    本工程 Chroma 期望的监听端口。
.PARAMETER PersistPath
    本工程 Chroma 期望的数据目录。
#>
function Test-ChromaOwnership {
    param(
        [Parameter(Mandatory = $true)]
        $Process,
        [int]$ListenPort,
        [string]$PersistPath
    )

    if ($null -eq $Process) {
        return $false
    }

    $commandLine = $Process.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }

    $lowerCommandLine = $commandLine.ToLowerInvariant()

    # 条件 1：必须是 chroma 进程特征。
    $hasChromaSignature = $lowerCommandLine.Contains('chroma')
    if (-not $hasChromaSignature) {
        return $false
    }

    # 条件 2：必须绑定到期望端口。用 \s 分隔，避免 "--port 87651" 被 "--port 8765" 误命中。
    $portPattern = '--port\s+' + [regex]::Escape([string]$ListenPort) + '(\s|$)'
    if (-not [regex]::IsMatch($lowerCommandLine, $portPattern)) {
        return $false
    }

    # 条件 3：必须绑定到本工程数据目录。提取 --path 后的路径值并做规范化比对。
    $expectedPath = ConvertTo-NormalizedPath -Path $PersistPath
    if ([string]::IsNullOrWhiteSpace($expectedPath)) {
        return $false
    }

    $pathMatch = [regex]::Match($lowerCommandLine, '--path\s+(?:"([^"]+)"|(\S+))')
    if (-not $pathMatch.Success) {
        # 命令行里没有 --path：无法证明属于本工程，按"不是"处理（保守拒绝）。
        return $false
    }

    $actualPathValue = if ($pathMatch.Groups[1].Success) { $pathMatch.Groups[1].Value } else { $pathMatch.Groups[2].Value }
    $actualPath = ConvertTo-NormalizedPath -Path $actualPathValue
    if ($actualPath -ne $expectedPath) {
        return $false
    }

    return $true
}

# 取出该进程所属的、且经归属校验通过的 Chroma 进程集合（本工程实例可能有 shim + python 两层）。
function Get-OwnedChromaProcesses {
    param([int]$ListenPort, [string]$PersistPath)

    $owned = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        if (Test-ChromaOwnership -Process $_ -ListenPort $ListenPort -PersistPath $PersistPath) {
            $owned += $_
        }
    }

    return $owned
}

# 描述端口属主，供错误提示使用。
function Format-ProcessDescription {
    param($Process)

    if ($null -eq $Process) {
        return '<未知进程>'
    }

    $name = $Process.Name
    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = '<未知名称>'
    }

    $commandLine = $Process.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        $commandLine = '<命令行不可读>'
    }

    return "PID $($Process.ProcessId) / $name / 命令行: $commandLine"
}

# 读取 PID 文件并校验该 PID 当前确实是本工程的 Chroma 进程。
# PID 文件位于 gitignore 的 data 目录，不随仓库走，PID 被系统回收复用是现实风险，
# 因此必须校验身份后才允许后续终止动作。
function Get-VerifiedChromaProcessId {
    param([string]$PidFile, [int]$ListenPort, [string]$PersistPath)

    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $pidContent = (Get-Content -Path $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ([string]::IsNullOrWhiteSpace($pidContent)) {
        return $null
    }

    $parsedProcessId = 0
    if (-not [int]::TryParse($pidContent, [ref]$parsedProcessId)) {
        Write-Warning "PID 文件内容不是合法进程号（'$pidContent'），已忽略。文件：$PidFile"
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$parsedProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }

    if (-not (Test-ChromaOwnership -Process $process -ListenPort $ListenPort -PersistPath $PersistPath)) {
        Write-Warning "PID 文件记录的进程 $parsedProcessId 不是本工程的 Chroma（PID 可能已被系统复用），拒绝终止。"
        Write-Warning "    实际进程：$(Format-ProcessDescription -Process $process)"
        return $null
    }

    return $parsedProcessId
}

function Start-ChromaService {
    param([int]$ListenPort, [string]$PersistPath, [string]$ListenHost)

    # 端口已有人占位时，必须先判定属主身份：
    #   - 属主是本工程 Chroma → 幂等跳过；
    #   - 属主是非 Chroma 进程 → 报错退出，绝不静默跳过（否则后续 REST 调用会以协议不符的方式失败）。
    $portOwner = Get-PortOwnerProcess -ListenPort $ListenPort
    if ($null -ne $portOwner) {
        if (Test-ChromaOwnership -Process $portOwner -ListenPort $ListenPort -PersistPath $PersistPath) {
            Write-Host "Chroma 已在端口 $ListenPort 运行，无需重复启动。"
            return
        }

        throw ("端口 $ListenPort 已被非 Chroma 进程占用，拒绝启动以免与既有服务冲突。`n" +
            "    占用者：$(Format-ProcessDescription -Process $portOwner)")
    }

    $chromaExecutable = Resolve-ChromaExecutable

    if (-not (Test-Path $PersistPath)) {
        New-Item -ItemType Directory -Path $PersistPath -Force | Out-Null
    }

    $stdoutLog = Join-Path $PersistPath 'chroma.stdout.log'
    $stderrLog = Join-Path $PersistPath 'chroma.stderr.log'

    Write-Host "==> 启动 Chroma：$chromaExecutable run --path $PersistPath --host $ListenHost --port $ListenPort"

    # 通过 Win32_Process 的 Create 方法拉起 cmd 再拉起 chroma：
    #   1) Win32_Process.Create 创建的是完全独立的进程，不继承调用方的任何标准句柄，
    #      因此调用方在管道中（`| Out-String`）等待 EOF 时不会挂起，
    #      且脚本返回后 chroma 继续存活；
    #   2) 交给 cmd 解释输出重定向（Create 方法本身不解析 `1>` / `2>`），
    #      日志落盘便于排查启动失败原因。
    # --host 显式指定监听地址：Chroma 默认的 localhost 在本机会解析为 IPv6 回环，
    # 只监听 [::1]，而 JDK HttpClient 解析 localhost 时优先取 IPv4 且不回退，
    # 会导致工程默认 baseUrl http://localhost:8765 连不通。
    $launchCommand = 'cmd /c ""{0}" run --path "{1}" --host {2} --port {3} 1> "{4}" 2> "{5}""' -f `
        $chromaExecutable, $PersistPath, $ListenHost, $ListenPort, $stdoutLog, $stderrLog
    $createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
        -Arguments @{ CommandLine = $launchCommand }
    if ($createResult.ReturnValue -ne 0) {
        throw "Chroma 启动失败，无法创建进程（Win32_Process.Create 返回 $($createResult.ReturnValue)）。详见 $stderrLog"
    }

    # 等待端口就绪；服务起来后才算启动成功。
    #
    # **为什么窗口是 180 秒而不是 60 秒**：等待循环里每一次
    # Get-PortOwnerProcess 都要做一次 CIM 进程查询，
    # 而**带 Filter 的 CIM 查询实测要 3.1 秒**（不带 Filter 的全量查询只要 0.19 秒）。
    # 一轮循环（取属主 + 校验归属）因此要 6 秒左右，
    # 60 秒窗口里实际只有约 10 次探测机会。
    #
    # 而 Chroma 冷启动（要恢复已有集合数据）实测需要 70 秒以上 ——
    # 于是脚本在服务**实际已经起来**的情况下报"启动超时"，
    # 把整条 start.ps1 链路带崩。
    #
    # **为什么不是无限等待**：端口被非 Chroma 进程占用是真故障，
    # 应该快速失败而不是慢慢等。
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline) {
        $ownerProcess = Get-PortOwnerProcess -ListenPort $ListenPort
        if ($null -ne $ownerProcess) {
            if (-not (Test-ChromaOwnership -Process $ownerProcess -ListenPort $ListenPort -PersistPath $PersistPath)) {
                throw ("端口 $ListenPort 已被非 Chroma 进程占用（启动过程中被抢占），启动中止。`n" +
                    "    占用者：$(Format-ProcessDescription -Process $ownerProcess)")
            }

            # 记录真正占用端口的进程 PID：chroma.exe 只是 shim，
            # 实际服务由其 python.exe 子进程提供，记录端口属主才能被 stop 精确清理。
            $pidFile = Join-Path $PersistPath 'chroma.pid'
            Set-Content -Path $pidFile -Value $ownerProcess.ProcessId -Encoding ascii
            Write-Host "Chroma started on port $ListenPort"
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw "Chroma 启动超时（180s），端口 $ListenPort 未就绪。详见 $stderrLog"
}

function Stop-ChromaService {
    param([int]$ListenPort, [string]$PersistPath)

    $pidFile = Join-Path $PersistPath 'chroma.pid'
    $chromaProcessId = Get-VerifiedChromaProcessId -PidFile $pidFile -ListenPort $ListenPort -PersistPath $PersistPath

    if ($null -eq $chromaProcessId) {
        Write-Host "Chroma 未在运行（无有效的 PID 文件）。"
        if (Test-Path $pidFile) {
            Remove-Item -Path $pidFile -Force
        }
        return
    }

    # 终止目标集合 = PID 文件记录的进程 + 归属校验通过的本工程 Chroma 进程。
    # 归属校验（Test-ChromaOwnership）要求 --path 精确等于本工程数据目录，
    # 因此不会误伤其它 python / 其它目录下的 chroma 进程。
    $ownedProcesses = Get-OwnedChromaProcesses -ListenPort $ListenPort -PersistPath $PersistPath
    $processToStop = @()
    $processToStop += $ownedProcesses | Where-Object { $_.ProcessId -ne $chromaProcessId }
    $processToStop += $ownedProcesses | Where-Object { $_.ProcessId -eq $chromaProcessId }

    if ($processToStop.Count -eq 0) {
        Write-Host "Chroma 未在运行（PID $chromaProcessId 已不存在）。"
        if (Test-Path $pidFile) {
            Remove-Item -Path $pidFile -Force
        }
        return
    }

    # 终止前打印完整命令行，便于人工确认即将被杀的是不是目标进程。
    Write-Host "==> 即将终止以下属于本工程的 Chroma 进程（端口 $ListenPort，数据目录 $PersistPath）："
    $processToStop | ForEach-Object {
        Write-Host "    PID $($_.ProcessId) / $($_.Name) / 命令行: $($_.CommandLine)"
    }

    foreach ($process in $processToStop) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path $pidFile) {
        Remove-Item -Path $pidFile -Force
    }

    # 确认端口确实已释放，避免遗留占用导致后续 start 被判定为"已在运行"。
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-PortListening -ListenPort $ListenPort)) {
            Write-Host "Chroma stopped on port $ListenPort"
            return
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Warning "Chroma 进程已终止，但端口 $ListenPort 仍在监听，可能有其它进程占用。"
}

function Show-ChromaStatus {
    param([int]$ListenPort, [string]$PersistPath)

    $pidFile = Join-Path $PersistPath 'chroma.pid'
    $chromaProcessId = Get-VerifiedChromaProcessId -PidFile $pidFile -ListenPort $ListenPort -PersistPath $PersistPath

    $portOwner = Get-PortOwnerProcess -ListenPort $ListenPort
    if ($null -ne $portOwner) {
        if (Test-ChromaOwnership -Process $portOwner -ListenPort $ListenPort -PersistPath $PersistPath) {
            Write-Host "Chroma 运行中，监听端口 $ListenPort。"
            if ($null -ne $chromaProcessId) {
                Write-Host "    PID: $chromaProcessId"
            }
            return
        }

        # 端口在监听但属主不是本工程 Chroma：不能报告为"Chroma 运行中"。
        Write-Host "Chroma 未运行（端口 $ListenPort 已被非 Chroma 进程占用）。"
        Write-Host "    占用者：$(Format-ProcessDescription -Process $portOwner)"
        return
    }

    Write-Host "Chroma 未运行（端口 $ListenPort 无监听）。"
}

switch ($Action) {
    'start' { Start-ChromaService -ListenPort $Port -PersistPath $DataPath -ListenHost $ListenHost }
    'stop' { Stop-ChromaService -ListenPort $Port -PersistPath $DataPath }
    'status' { Show-ChromaStatus -ListenPort $Port -PersistPath $DataPath }
}
