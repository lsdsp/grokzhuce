param(
    [switch]$NoProxy,
    [string]$ProxyHttp = "",
    [string]$ProxySocks = "",
    [Nullable[int]]$SolverThread = $null,
    [Nullable[int]]$ReadyTimeoutSec = $null
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    $line = "[{0}] [*] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    if ($script:smokeLogFile) {
        Add-Content -Path $script:smokeLogFile -Value $line -Encoding UTF8
    }
}

function Set-ProxyEnvironment {
    param([string]$Http, [string]$Socks)
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

function Get-OneClickSharedDefaults {
    param(
        [string]$PythonPath,
        [string]$ProjectRoot
    )

    $helperPath = Join-Path $ProjectRoot "oneclick_shared.py"
    $settings = @{}
    # oneclick_shared.py defaults
    foreach ($line in & $PythonPath $helperPath defaults) {
        if ([string]::IsNullOrWhiteSpace($line) -or ($line -notmatch "=")) {
            continue
        }
        $parts = $line -split "=", 2
        $settings[$parts[0]] = $parts[1]
    }
    return $settings
}

function Get-SharedDefaultValue {
    param(
        [hashtable]$Defaults,
        [string]$Key,
        [string]$Fallback
    )

    if ($Defaults.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($Defaults[$Key])) {
        return $Defaults[$Key]
    }
    return $Fallback
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

function Set-SolverStoreEnvironment {
    param(
        [string]$StoreKind,
        [string]$DbPath
    )

    $script:previousSolverStore = [ordered]@{
        SOLVER_RESULT_STORE = $env:SOLVER_RESULT_STORE
        SOLVER_RESULT_DB_PATH = $env:SOLVER_RESULT_DB_PATH
    }

    $env:SOLVER_RESULT_STORE = $StoreKind
    $env:SOLVER_RESULT_DB_PATH = $DbPath
}

function Restore-SolverStoreEnvironment {
    if (-not $script:previousSolverStore) {
        return
    }

    foreach ($name in @("SOLVER_RESULT_STORE", "SOLVER_RESULT_DB_PATH")) {
        $value = $script:previousSolverStore[$name]
        if ($null -eq $value) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item "Env:$name" -Value $value
        }
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

$sharedDefaults = Get-OneClickSharedDefaults -PythonPath $pythonPath -ProjectRoot $projectRoot
$defaultSmokeSolverThread = [int](Get-SharedDefaultValue -Defaults $sharedDefaults -Key "DEFAULT_SMOKE_SOLVER_THREAD" -Fallback "2")
$defaultProxyHttp = Get-SharedDefaultValue -Defaults $sharedDefaults -Key "DEFAULT_PROXY_HTTP" -Fallback ""
$defaultProxySocks = Get-SharedDefaultValue -Defaults $sharedDefaults -Key "DEFAULT_PROXY_SOCKS" -Fallback ""
$defaultReadyTimeoutSec = [int](Get-SharedDefaultValue -Defaults $sharedDefaults -Key "SMOKE_READY_TIMEOUT_SEC" -Fallback "90")

if ($null -eq $SolverThread) {
    $SolverThread = $defaultSmokeSolverThread
}
if ($null -eq $ReadyTimeoutSec) {
    $ReadyTimeoutSec = $defaultReadyTimeoutSec
}
if ([string]::IsNullOrWhiteSpace($ProxyHttp)) {
    $ProxyHttp = $defaultProxyHttp
}
if ([string]::IsNullOrWhiteSpace($ProxySocks)) {
    $ProxySocks = $defaultProxySocks
}

$logRoot = Join-Path $projectRoot (Get-SharedDefaultValue -Defaults $sharedDefaults -Key "LOG_ROOT_DIR" -Fallback "logs")
$solverLogDir = Join-Path $projectRoot (Get-SharedDefaultValue -Defaults $sharedDefaults -Key "LOG_SOLVER_DIR" -Fallback "logs/solver")
$oneclickLogDir = Join-Path $projectRoot (Get-SharedDefaultValue -Defaults $sharedDefaults -Key "LOG_ONECLICK_DIR" -Fallback "logs/oneclick")
foreach ($dir in @($logRoot, $solverLogDir, $oneclickLogDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$script:smokeLogFile = Join-Path $oneclickLogDir "release_smoke.$ts.log"
New-Item -ItemType File -Path $script:smokeLogFile -Force | Out-Null

if ($NoProxy) {
    Write-Step "Proxy disabled by -NoProxy"
    Clear-ProxyEnvironment
} else {
    Write-Step "Applying proxy: $ProxyHttp / $ProxySocks"
    Set-ProxyEnvironment -Http $ProxyHttp -Socks $ProxySocks
}

$startedSolver = $false
$solverProcess = $null
$solverErr = $null
$solverDbPath = $null
$script:previousSolverStore = $null

try {
    Write-Step "Running unit tests"
    & $pythonPath -m unittest discover -s tests -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed with exit code $LASTEXITCODE"
    }

    $solverAlreadyRunning = Test-SolverReady
    if ($solverAlreadyRunning) {
        Write-Step "Solver already running at http://127.0.0.1:5072"
    } else {
        $solverOut = Join-Path $solverLogDir "solver.smoke.$ts.out.log"
        $solverErr = Join-Path $solverLogDir "solver.smoke.$ts.err.log"
        $solverDbPath = Join-Path $solverLogDir "solver.smoke.$ts.sqlite3"
        Write-Step "Using SQLite solver store for smoke: $solverDbPath"
        Set-SolverStoreEnvironment -StoreKind "sqlite" -DbPath $solverDbPath
        $solverArgs = @("api_solver.py", "--browser_type", "camoufox", "--thread", "$SolverThread", "--debug")
        if (-not $NoProxy) {
            $solverArgs += "--proxy"
        }

        Write-Step "Starting solver for smoke check (threads=$SolverThread)"
        $solverProcess = Start-Process `
            -FilePath $pythonPath `
            -ArgumentList $solverArgs `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $solverOut `
            -RedirectStandardError $solverErr `
            -PassThru
        $startedSolver = $true
        Write-Step "Started solver PID=$($solverProcess.Id)"
        Write-Step "Solver logs: $solverOut / $solverErr"

        $ready = $false
        for ($i = 1; $i -le $ReadyTimeoutSec; $i++) {
            Start-Sleep -Seconds 1
            if (Test-SolverReady) {
                $ready = $true
                break
            }
        }
        if (-not $ready) {
            $hint = ""
            if ($solverErr -and (Test-Path $solverErr)) {
                $hintText = (Get-Content $solverErr -Tail 20 -ErrorAction SilentlyContinue) -join " | "
                if ($hintText) {
                    $hint = " | solver.err tail: $hintText"
                }
            }
            throw "Solver not ready on 127.0.0.1:5072 after $ReadyTimeoutSec seconds$hint"
        }
    }

    Write-Step "Checking solver API health"
    $r1 = Invoke-RestMethod -Uri "http://127.0.0.1:5072/result?id=smoke-missing-id" -Method Get -TimeoutSec 15
    if ($r1.errorId -ne 1) {
        throw "Unexpected /result response: $($r1 | ConvertTo-Json -Compress)"
    }
    $r2 = Invoke-RestMethod -Uri "http://127.0.0.1:5072/turnstile" -Method Get -TimeoutSec 15
    if ($r2.errorId -ne 1) {
        throw "Unexpected /turnstile response: $($r2 | ConvertTo-Json -Compress)"
    }

    if ($startedSolver -and $solverDbPath) {
        Write-Step "Checking SQLite solver store health"
        if (-not (Test-Path $solverDbPath)) {
            throw "SQLite solver DB was not created: $solverDbPath"
        }

        $tableCheck = & $pythonPath -c "import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); row = conn.execute(""SELECT name FROM sqlite_master WHERE type='table' AND name='solver_results'"").fetchone(); conn.close(); raise SystemExit(0 if row else 1)" $solverDbPath
        if ($LASTEXITCODE -ne 0) {
            throw "SQLite solver DB is missing table solver_results: $solverDbPath"
        }
    } else {
        Write-Step "Skipping SQLite solver store check because an existing solver instance is already running"
    }

    Write-Step "Release smoke passed"
    exit 0
} catch {
    Write-Step "Release smoke failed: $($_.Exception.Message)"
    exit 1
} finally {
    Restore-SolverStoreEnvironment
    if ($startedSolver -and $solverProcess) {
        try {
            Stop-Process -Id $solverProcess.Id -Force -ErrorAction SilentlyContinue
            Write-Step "Stopped smoke solver PID=$($solverProcess.Id)"
        } catch {
            Write-Step "Failed to stop smoke solver PID=$($solverProcess.Id)"
        }
    }
}
