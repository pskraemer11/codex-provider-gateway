<#
.SYNOPSIS
    Check the local Go/Zen proxy and start it from this checkout when needed.
.DESCRIPTION
    Checks the loopback /health endpoint on the selected port. If the proxy is
    not healthy, validates this repository and uv, then starts the proxy in the
    background and waits up to 60 seconds for health to pass. Status is also
    appended to the user's local proxy log directory. The proxy is not stopped
    when this script exits. Use Get-Help or -? for PowerShell help; --help and
    -Help display this detailed help directly.
.PARAMETER Port
    Loopback port used by the proxy health check and start request. Defaults to 8787.
.PARAMETER Quiet
    Suppress status messages in the console. Local watchdog logging remains enabled.
.PARAMETER Executable
    Explicit opencode-go-proxy executable. By default the installed command is
    preferred, with `uv run` from this checkout as a development fallback.
.PARAMETER ProjectRoot
    Repository checkout used only for the uv fallback when no installed proxy
    command is available. Defaults to this script's checkout location.
.PARAMETER UnboundArguments
    Reserved for the -Help/--help compatibility form. Do not specify directly;
    all other unrecognized arguments are rejected.
.EXAMPLE
    .\watchdog-proxy.ps1

    Check port 8787 and start the proxy if it is not healthy.
.EXAMPLE
    .\watchdog-proxy.ps1 -Port 8788 -WhatIf

    Check port 8788 and preview, without launching a proxy, if a start is needed.
.EXAMPLE
    .\watchdog-proxy.ps1 --help

    Display this script's detailed help.
.NOTES
    Requires PowerShell 7. Uses uv only when no installed proxy command exists.
    Only binds the proxy to 127.0.0.1.
#>
#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8787,
    [switch]$Quiet,
    [string]$Executable,
    [string]$ProjectRoot,
    [Parameter(ValueFromRemainingArguments = $true, DontShow = $true)]
    [string[]]$UnboundArguments
)

if ($UnboundArguments) {
    if ($UnboundArguments.Count -eq 1 -and $UnboundArguments[0] -in @("--help", "-Help")) {
        Get-Help -Name $PSCommandPath -Detailed
        return
    }
    throw "Unrecognized argument(s): $($UnboundArguments -join ', '). Use -? or --help for help."
}

$ErrorActionPreference = "Stop"
$healthUri = "http://127.0.0.1:$Port/health"
$repoRoot = if ($ProjectRoot) {
    [System.IO.Path]::GetFullPath($ProjectRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$localAppData = [Environment]::GetFolderPath("LocalApplicationData")
$logDirectory = Join-Path $localAppData "opencode-go-proxy\logs"
$watchdogLog = Join-Path $logDirectory "watchdog.log"

function Write-Status {
    param([Parameter(Mandatory)][string]$Message)

    if (-not $Quiet) { Write-Host $Message }
    try {
        if (-not (Test-Path -LiteralPath $logDirectory)) {
            New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        }
        $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
        Add-Content -LiteralPath $watchdogLog -Value $line -Encoding utf8
    }
    catch {
        # A local log failure must not prevent a health check or a start attempt.
    }
}

function Test-ProxyHealth {
    try {
        $response = Invoke-WebRequest -Uri $healthUri -TimeoutSec 3
        $payload = $response.Content | ConvertFrom-Json
        return $payload.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Get-UvPath {
    $command = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return [string]$command.Source }

    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $candidates = @(
        (Join-Path $userProfile ".local\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\uv\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Get-ProxyLaunch {
    if ($Executable) {
        $explicit = [System.IO.Path]::GetFullPath($Executable)
        if (-not (Test-Path -LiteralPath $explicit -PathType Leaf)) {
            throw "Proxy executable was not found: $explicit"
        }
        return [pscustomobject]@{
            FilePath = $explicit
            Arguments = @()
            WorkingDirectory = (Get-Location).Path
            Mode = "explicit"
        }
    }

    $command = Get-Command opencode-go-proxy -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) {
        return [pscustomobject]@{
            FilePath = [string]$command.Source
            Arguments = @()
            WorkingDirectory = (Get-Location).Path
            Mode = "installed"
        }
    }

    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $installed = Join-Path $userProfile ".local\bin\opencode-go-proxy.exe"
    if (Test-Path -LiteralPath $installed -PathType Leaf) {
        return [pscustomobject]@{
            FilePath = $installed
            Arguments = @()
            WorkingDirectory = (Get-Location).Path
            Mode = "installed"
        }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml") -PathType Leaf)) {
        throw "No installed proxy command was found and the repository checkout is incomplete."
    }
    $uv = Get-UvPath
    if (-not $uv) {
        throw "No installed proxy command or uv was found."
    }
    return [pscustomobject]@{
        FilePath = $uv
        Arguments = @("run", "--project", ('"{0}"' -f $repoRoot), "--locked", "opencode-go-proxy")
        WorkingDirectory = $repoRoot
        Mode = "checkout"
    }
}

if (Test-ProxyHealth) {
    if (-not $Quiet) { Write-Host "Proxy health is OK on port $Port." }
    exit 0
}

try {
    $launch = Get-ProxyLaunch
}
catch {
    Write-Status $_.Exception.Message
    exit 1
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    Write-Status "Port $Port is listening, but /health did not answer; refusing to start a duplicate."
    exit 1
}

if (-not $PSCmdlet.ShouldProcess($healthUri, "Start the proxy")) {
    exit 0
}

# Scheduled tasks do not always inherit user-scoped environment variables.
# Copy the key into this process only; never log or persist the value.
if (-not [Environment]::GetEnvironmentVariable("OPENCODE_GO_API_KEY", "Process")) {
    $userKey = [Environment]::GetEnvironmentVariable("OPENCODE_GO_API_KEY", "User")
    if ($userKey) {
        [Environment]::SetEnvironmentVariable("OPENCODE_GO_API_KEY", $userKey, "Process")
    }
}

try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutLog = Join-Path $logDirectory "proxy-$stamp.stdout.log"
    $stderrLog = Join-Path $logDirectory "proxy-$stamp.stderr.log"
    $arguments = @($launch.Arguments) + @(
        "--bind",
        "127.0.0.1",
        "--port",
        "$Port"
    )
    $null = Start-Process -FilePath $launch.FilePath `
        -ArgumentList $arguments `
        -WorkingDirectory $launch.WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    Write-Status "Proxy start requested ($($launch.Mode)); checking /health."
}
catch {
    Write-Status "Could not start the proxy process."
    exit 1
}

for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (Test-ProxyHealth) {
        Write-Status "Proxy health is OK on port $Port."
        exit 0
    }
}

Write-Status "Proxy did not pass /health within 60 seconds; inspect its local stdout/stderr logs."
exit 1
