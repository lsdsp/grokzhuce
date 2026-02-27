param(
    [Nullable[int]]$Threads = $null,
    [Nullable[int]]$Count = $null,
    [Nullable[int]]$MaxAttempts = $null,
    [int]$SolverThread = 5,
    [string]$ProxyHttp = "http://127.0.0.1:10808",
    [string]$ProxySocks = "socks5://127.0.0.1:10808",
    [switch]$NoProxy
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    $line = "[{0}] [*] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host "[*] $Message"
    if ($script:oneclickLogFile) {
        Add-Content -Path $script:oneclickLogFile -Value $line -Encoding UTF8
    }
}

function Read-PositiveIntPrompt {
    param(
        [string]$Prompt,
        [int]$DefaultValue
    )

    while ($true) {
        $inputValue = Read-Host "$Prompt (默认 $DefaultValue)"
        if ([string]::IsNullOrWhiteSpace($inputValue)) {
            return $DefaultValue
        }

        $parsed = 0
        if ([int]::TryParse($inputValue, [ref]$parsed) -and $parsed -gt 0) {
            return $parsed
        }

        Write-Host "[!] 请输入正整数，或直接回车使用默认值 $DefaultValue"
    }
}

function Set-ProxyEnvironment {
    param(
        [string]$Http,
        [string]$Socks
    )

    $env:http_proxy = $Http
    $env:https_proxy = $Http
    $env:all_proxy = $Socks
    $env:HTTP_PROXY = $Http
    $env:HTTPS_PROXY = $Http
    $env:ALL_PROXY = $Socks
}

function Clear-ProxyEnvironment {
    foreach ($name in @("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")) {
        if (Test-Path "Env:$name") {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

function Test-SolverReady {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connected = $client.ConnectAsync("127.0.0.1", 5072).Wait(500)
        $isReady = $connected -and $client.Connected
        $client.Close()
        return [bool]$isReady
    } catch {
        return $false
    }
}

function Get-SolverProcessIds {
    $ids = @()

    try {
        $listenLines = @(netstat -ano | findstr ":5072" | findstr "LISTENING")
        foreach ($line in $listenLines) {
            $parts = ($line -split "\s+") | Where-Object { $_ -ne "" }
            if ($parts.Count -ge 5) {
                $pidStr = $parts[-1]
                if ($pidStr -match "^\d+$") {
                    $ids += [int]$pidStr
                }
            }
        }
    } catch {}

    try {
        $solverPids = Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -like "*api_solver.py*" } |
            Select-Object -ExpandProperty ProcessId
        foreach ($pid in $solverPids) {
            if ("$pid" -match "^\d+$") {
                $ids += [int]$pid
            }
        }
    } catch {}

    return @($ids | Sort-Object -Unique)
}

function Stop-SolverWithTimeout {
    param([int]$TimeoutSec = 180)

    Write-Step "Stopping solver (timeout ${TimeoutSec}s)..."
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $signaled = @{}

    while ((Get-Date) -lt $deadline) {
        $pids = Get-SolverProcessIds
        $isReady = Test-SolverReady
        if (($pids.Count -eq 0) -and (-not $isReady)) {
            Write-Step "Solver stopped."
            return $true
        }

        foreach ($pid in $pids) {
            if (-not $signaled.ContainsKey($pid)) {
                try {
                    Stop-Process -Id $pid -ErrorAction SilentlyContinue
                    Write-Step "Stop signal sent to solver PID: $pid"
                } catch {}
                $signaled[$pid] = $true
            }
        }

        Start-Sleep -Seconds 2
    }

    $remaining = Get-SolverProcessIds
    if ($remaining.Count -gt 0) {
        Write-Step "Timeout reached, force stopping solver PID(s): $($remaining -join ', ')"
        foreach ($pid in $remaining) {
            try {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            } catch {}
        }
        Start-Sleep -Seconds 2
    }

    $finalRemaining = Get-SolverProcessIds
    if (($finalRemaining.Count -eq 0) -and (-not (Test-SolverReady))) {
        Write-Step "Solver force-stop completed."
        return $true
    }

    Write-Step "Solver may still be running after timeout."
    return $false
}

function Write-Diag {
    param([string]$Message)
    Write-Host $Message
    if ($script:oneclickLogFile) {
        Add-Content -Path $script:oneclickLogFile -Value $Message -Encoding UTF8
    }
}

function Show-GrokFailureSummary {
    param([string]$LogPath)

    if (-not (Test-Path $LogPath)) {
        Write-Step "Unable to build failure summary: grok log not found."
        return
    }

    $patterns = @(
        "ATTEMPT_LIMIT_REACHED",
        "已达到最大尝试上限",
        "初始化扫描失败",
        "未找到 Action ID",
        "服务初始化失败",
        "Traceback",
        "ModuleNotFoundError",
        "TLS connect error",
        "Connection timed out",
        "Resolving timed out",
        "SSLError",
        "Timeout"
    )

    $summaryLines = @()
    foreach ($p in $patterns) {
        $match = Select-String -Path $LogPath -Pattern $p -SimpleMatch | Select-Object -Last 1
        if ($match) {
            $summaryLines += $match.Line.Trim()
        }
    }

    $summaryLines = $summaryLines | Select-Object -Unique
    if ($summaryLines.Count -gt 0) {
        Write-Step "Failure summary from grok log:"
        foreach ($line in ($summaryLines | Select-Object -First 6)) {
            Write-Diag "[diag] $line"
        }
        return
    }

    Write-Step "Failure summary fallback: tail of grok log."
    Get-Content -Path $LogPath -Tail 20 | ForEach-Object {
        Write-Diag "[tail] $_"
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$logRoot = Join-Path $projectRoot "logs"
$logSolverDir = Join-Path $logRoot "solver"
$logGrokDir = Join-Path $logRoot "grok"
$logOneClickDir = Join-Path $logRoot "oneclick"
$logOthersDir = Join-Path $logRoot "others"
foreach ($dir in @($logRoot, $logSolverDir, $logGrokDir, $logOneClickDir, $logOthersDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$runTimestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$script:oneclickLogFile = Join-Path $logOneClickDir "start_all.$runTimestamp.log"
New-Item -ItemType File -Path $script:oneclickLogFile -Force | Out-Null

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

if ($NoProxy) {
    Write-Step "Proxy disabled by -NoProxy."
    Clear-ProxyEnvironment
} else {
    Write-Step "Applying local proxy: $ProxyHttp / $ProxySocks"
    Set-ProxyEnvironment -Http $ProxyHttp -Socks $ProxySocks
}

if (Test-SolverReady) {
    Write-Step "Solver is already running at http://127.0.0.1:5072"
} else {
    $solverOut = Join-Path $logSolverDir "solver.oneclick.$runTimestamp.out.log"
    $solverErr = Join-Path $logSolverDir "solver.oneclick.$runTimestamp.err.log"

    $solverArgs = @(
        "api_solver.py",
        "--browser_type", "camoufox",
        "--thread", "$SolverThread",
        "--debug"
    )
    if (-not $NoProxy) {
        $solverArgs += "--proxy"
    }

    Write-Step "Starting solver (threads=$SolverThread)..."
    $solverProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $solverArgs `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $solverOut `
        -RedirectStandardError $solverErr `
        -PassThru

    Write-Step "Solver PID: $($solverProcess.Id)"
    Write-Step "Solver logs: $solverOut / $solverErr"

    $ready = $false
    for ($i = 1; $i -le 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-SolverReady) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Step "Solver not ready within 60 seconds; starting cleanup."
        [void](Stop-SolverWithTimeout -TimeoutSec 180)
        Write-Error "Solver did not become ready on port 5072 within 60 seconds."
        exit 1
    }
    Write-Step "Solver is ready."
}

$defaultThreads = 3
$defaultCount = 5
$threadsProvided = $PSBoundParameters.ContainsKey("Threads")
$countProvided = $PSBoundParameters.ContainsKey("Count")

if ($threadsProvided -and $Threads -le 0) {
    Write-Error "Invalid -Threads value: $Threads. It must be a positive integer."
    exit 1
}
if ($countProvided -and $Count -le 0) {
    Write-Error "Invalid -Count value: $Count. It must be a positive integer."
    exit 1
}
if ($PSBoundParameters.ContainsKey("MaxAttempts") -and $MaxAttempts -le 0) {
    Write-Error "Invalid -MaxAttempts value: $MaxAttempts. It must be a positive integer."
    exit 1
}

if (-not $threadsProvided) {
    $Threads = Read-PositiveIntPrompt -Prompt "请输入并发 threads" -DefaultValue $defaultThreads
}
if (-not $countProvided) {
    $Count = Read-PositiveIntPrompt -Prompt "请输入目标 count" -DefaultValue $defaultCount
}

Write-Step "Starting grok with --threads $Threads --count $Count"
$grokOut = Join-Path $logGrokDir "grok.oneclick.$runTimestamp.out.log"
Write-Step "Grok log: $grokOut"
$grokArgs = @("-u", "grok.py", "--threads", "$Threads", "--count", "$Count")
if ($PSBoundParameters.ContainsKey("MaxAttempts")) {
    $grokArgs += @("--max-attempts", "$MaxAttempts")
    Write-Step "Apply max attempts: $MaxAttempts"
}
$exitCode = 1
try {
    & $pythonPath @grokArgs 2>&1 | Tee-Object -FilePath $grokOut
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    Write-Step "grok.py exited with code $exitCode"
    $attemptLimitHit = $false
    $hasSuccess = $false
    $hasFailurePattern = $false
    if (Test-Path $grokOut) {
        $hasSuccess =
            (Select-String -Path $grokOut -Pattern "[OK]" -SimpleMatch -Quiet) -or
            (Select-String -Path $grokOut -Pattern "注册成功:" -SimpleMatch -Quiet)
        $attemptLimitHit =
            (Select-String -Path $grokOut -Pattern "ATTEMPT_LIMIT_REACHED" -SimpleMatch -Quiet) -or
            (Select-String -Path $grokOut -Pattern "已达到最大尝试上限" -SimpleMatch -Quiet)
        foreach ($hint in @(
            "初始化扫描失败",
            "未找到 Action ID",
            "服务初始化失败",
            "Traceback",
            "ModuleNotFoundError",
            "TLS connect error",
            "Connection timed out",
            "Resolving timed out",
            "SSLError",
            "Timeout"
        )) {
            if (Select-String -Path $grokOut -Pattern $hint -SimpleMatch -Quiet) {
                $hasFailurePattern = $true
                break
            }
        }
    }
    if ($exitCode -ne 0 -or $attemptLimitHit -or ((-not $hasSuccess) -and $hasFailurePattern)) {
        Show-GrokFailureSummary -LogPath $grokOut
    }
} finally {
    $stopped = Stop-SolverWithTimeout -TimeoutSec 180
    if (-not $stopped -and $exitCode -eq 0) {
        $exitCode = 1
    }
}
exit $exitCode

