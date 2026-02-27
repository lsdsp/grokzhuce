param()

$ErrorActionPreference = "Stop"

function Test-FileLocked {
    param([string]$Path)

    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $stream.Close()
        return $false
    } catch {
        return $true
    }
}

function Get-LogCategoryDir {
    param(
        [string]$FileName,
        [string]$SolverDir,
        [string]$GrokDir,
        [string]$OneClickDir,
        [string]$OthersDir
    )

    $name = $FileName.ToLowerInvariant()
    if ($name -like "solver*" -or $name -like "camoufox.fetch*") {
        return $SolverDir
    }
    if ($name -like "grok*") {
        return $GrokDir
    }
    if ($name -like "*oneclick*") {
        return $OneClickDir
    }
    return $OthersDir
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$logRoot = Join-Path $projectRoot "logs"
$solverDir = Join-Path $logRoot "solver"
$grokDir = Join-Path $logRoot "grok"
$oneClickDir = Join-Path $logRoot "oneclick"
$othersDir = Join-Path $logRoot "others"
foreach ($dir in @($logRoot, $solverDir, $grokDir, $oneClickDir, $othersDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$moved = 0
$skipped = 0
$movedList = New-Object System.Collections.Generic.List[string]
$skippedList = New-Object System.Collections.Generic.List[string]

$rootLogs = Get-ChildItem -File -Path $projectRoot -Filter "*.log" -ErrorAction SilentlyContinue
foreach ($file in $rootLogs) {
    if (Test-FileLocked -Path $file.FullName) {
        $skipped++
        $skippedList.Add($file.Name) | Out-Null
        continue
    }

    $targetDir = Get-LogCategoryDir `
        -FileName $file.Name `
        -SolverDir $solverDir `
        -GrokDir $grokDir `
        -OneClickDir $oneClickDir `
        -OthersDir $othersDir

    Move-Item -LiteralPath $file.FullName -Destination (Join-Path $targetDir $file.Name) -Force
    $moved++
    $movedList.Add($file.Name) | Out-Null
}

Write-Host "[*] Log organize done. moved=$moved skipped_locked=$skipped"
if ($movedList.Count -gt 0) {
    Write-Host "[*] Moved files:"
    $movedList | ForEach-Object { Write-Host "  - $_" }
}
if ($skippedList.Count -gt 0) {
    Write-Host "[*] Skipped (likely still writing):"
    $skippedList | ForEach-Object { Write-Host "  - $_" }
}
