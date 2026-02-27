param(
    [switch]$NoProxy,
    [string]$ProxyHttp = "http://127.0.0.1:10808",
    [string]$ProxySocks = "socks5://127.0.0.1:10808",
    [int]$SolverThread = 2,
    [int]$ReadyTimeoutSec = 90
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

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$logRoot = Join-Path $projectRoot "logs"
$solverLogDir = Join-Path $logRoot "solver"
$oneclickLogDir = Join-Path $logRoot "oneclick"
foreach ($dir in @($logRoot, $solverLogDir, $oneclickLogDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$script:smokeLogFile = Join-Path $oneclickLogDir "release_smoke.$ts.log"
New-Item -ItemType File -Path $script:smokeLogFile -Force | Out-Null

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

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

    Write-Step "Release smoke passed"
    exit 0
} catch {
    Write-Step "Release smoke failed: $($_.Exception.Message)"
    exit 1
} finally {
    if ($startedSolver -and $solverProcess) {
        try {
            Stop-Process -Id $solverProcess.Id -Force -ErrorAction SilentlyContinue
            Write-Step "Stopped smoke solver PID=$($solverProcess.Id)"
        } catch {
            Write-Step "Failed to stop smoke solver PID=$($solverProcess.Id)"
        }
    }
}
