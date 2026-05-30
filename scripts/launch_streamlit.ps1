param(
    [int]$Port = 8766,
    [int]$MaxPort = 8799
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Split-Path -Parent $ScriptDir
$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
$App = Join-Path $AppDir "app.py"
$LogDir = Join-Path $AppDir "logs"
$OutLog = Join-Path $LogDir "streamlit.out.log"
$ErrLog = Join-Path $LogDir "streamlit.err.log"
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Local Python environment was not found."
    Write-Host "Expected: $Python"
    Write-Host ""
    Write-Host "Run this once from the project folder:"
    Write-Host "python -m venv .venv"
    Write-Host ".\.venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-PortListeners {
    param([int]$CandidatePort)

    Get-NetTCPConnection -LocalPort $CandidatePort -State Listen -ErrorAction SilentlyContinue
}

function Test-ProjectAppProcess {
    param([int]$ProcessId)

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $processInfo -or -not $processInfo.CommandLine) {
        return $false
    }

    return $processInfo.CommandLine.IndexOf($App, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-ProjectAppOnPort {
    param([int]$CandidatePort)

    $listeners = Get-PortListeners -CandidatePort $CandidatePort
    foreach ($listener in $listeners) {
        if (Test-ProjectAppProcess -ProcessId $listener.OwningProcess) {
            return $true
        }
    }
    return $false
}

$selectedPort = $null
$shouldStart = $false

for ($candidatePort = $Port; $candidatePort -le $MaxPort; $candidatePort++) {
    $listeners = Get-PortListeners -CandidatePort $candidatePort
    if (-not $listeners) {
        $selectedPort = $candidatePort
        $shouldStart = $true
        break
    }

    if (Test-ProjectAppOnPort -CandidatePort $candidatePort) {
        $selectedPort = $candidatePort
        $shouldStart = $false
        break
    }
}

if (-not $selectedPort) {
    Write-Host "No free port found between $Port and $MaxPort."
    Write-Host "Close another local app or launch with a different -Port value."
    exit 1
}

$Url = "http://localhost:$selectedPort"

if ($shouldStart) {
    $streamlitArgs = @(
        "-m",
        "streamlit",
        "run",
        "`"$App`"",
        "--server.port",
        "$selectedPort",
        "--server.headless",
        "true"
    )

    Start-Process `
        -FilePath $Python `
        -ArgumentList $streamlitArgs `
        -WorkingDirectory $AppDir `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $listener = Get-PortListeners -CandidatePort $selectedPort
    } while (-not $listener -and (Get-Date) -lt $deadline)

    if (-not $listener) {
        Write-Host "Streamlit did not start on port $selectedPort."
        Write-Host "Check: $ErrLog"
        exit 1
    }
}

Start-Process $Url
