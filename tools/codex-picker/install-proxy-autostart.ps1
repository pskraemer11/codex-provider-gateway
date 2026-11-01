<#
.SYNOPSIS
    Install or remove the current user's scheduled tasks for the local proxy.
.DESCRIPTION
    Installs a logon task and a five-minute health-watchdog task for the proxy
    in this repository checkout. Registration and removal are explicit actions;
    -WhatIf previews them without changing Task Scheduler. Replacing existing
    tasks requires -ReplaceExisting and is limited to the two documented task names.
    Use Get-Help or -? for PowerShell help; --help and -Help display this detailed help.
.PARAMETER Port
    Loopback port passed to the watchdog task. Defaults to 8787.
.PARAMETER ReplaceExisting
    Replace existing tasks named 'opencode-go-proxy' and/or
    'opencode-go-proxy watchdog'. Without this switch, existing tasks cause an error.
.PARAMETER Uninstall
    Remove only those two named tasks, if present. Cannot be combined with
    -ReplaceExisting.
.PARAMETER UnboundArguments
    Reserved for the -Help/--help compatibility form. Do not specify directly;
    all other unrecognized arguments are rejected.
.EXAMPLE
    .\install-proxy-autostart.ps1 -WhatIf

    Preview registration of the logon and periodic watchdog tasks.
.EXAMPLE
    .\install-proxy-autostart.ps1

    Register the two tasks for the current Windows user.
.EXAMPLE
    .\install-proxy-autostart.ps1 -Uninstall

    Remove only the two proxy tasks managed by this script.
.EXAMPLE
    .\install-proxy-autostart.ps1 --help

    Display this script's detailed help.
.NOTES
    Requires PowerShell 7 and Task Scheduler cmdlets. The watchdog prefers the
    installed proxy command and uses uv only as a checkout fallback.
#>
#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8787,
    [switch]$ReplaceExisting,
    [switch]$Uninstall,
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
$taskNames = @("opencode-go-proxy", "opencode-go-proxy watchdog")

if ($Uninstall -and $ReplaceExisting) {
    throw "Use either -Uninstall or -ReplaceExisting, not both."
}

if ($Uninstall) {
    foreach ($taskName in $taskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $task) { continue }
        if ($PSCmdlet.ShouldProcess("Task Scheduler\$taskName", "Remove this proxy task")) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
    }
    return
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$watchdogPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "watchdog-proxy.ps1"))
$installDirectory = Join-Path $env:LOCALAPPDATA "opencode-go-proxy\bin"
$installedWatchdogPath = Join-Path $installDirectory "watchdog-proxy.ps1"
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml") -PathType Leaf)) {
    throw "Run this installer from the checked-out opencode-go-proxy repository."
}
if (-not (Test-Path -LiteralPath $watchdogPath -PathType Leaf)) {
    throw "Proxy watchdog script is missing."
}
$existingTasks = @{}
foreach ($taskName in $taskNames) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        if (-not $ReplaceExisting) {
            throw "Task '$taskName' already exists. Review it, then rerun with -ReplaceExisting to replace that exact task."
        }
        $existingTasks[$taskName] = $true
    }
}

$powerShell = Join-Path $PSHOME "pwsh.exe"
if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
    throw "The current PowerShell 7 executable was not found: $powerShell"
}
if ($PSCmdlet.ShouldProcess($installedWatchdogPath, "Install the watchdog script outside the checkout")) {
    New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
    Copy-Item -LiteralPath $watchdogPath -Destination $installedWatchdogPath -Force
}
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -Hidden
$taskArguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File `"$installedWatchdogPath`" -ProjectRoot `"$repoRoot`" -Port $Port -Quiet"
$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument $taskArguments `
    -WorkingDirectory $repoRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$definitions = @(
    @{
        Name = $taskNames[0]
        Trigger = $logonTrigger
        Description = "Start the loopback OpenCode Go/Zen proxy when this user signs in."
    },
    @{
        Name = $taskNames[1]
        Trigger = $repeatTrigger
        Description = "Check proxy health every five minutes while this user is signed in."
    }
)

foreach ($definition in $definitions) {
    $taskName = $definition.Name
    $registerArguments = @{
        TaskName = $taskName
        Action = $action
        Trigger = $definition.Trigger
        Settings = $settings
        Principal = $principal
        Description = $definition.Description
    }
    if ($existingTasks.ContainsKey($taskName)) { $registerArguments.Force = $true }

    $operation = if ($existingTasks.ContainsKey($taskName)) { "Replace scheduled task" } else { "Register scheduled task" }
    if ($PSCmdlet.ShouldProcess("Task Scheduler\$taskName", $operation)) {
        Register-ScheduledTask @registerArguments | Out-Null
    }
}

if ($WhatIfPreference) {
    Write-Host "WhatIf preview finished; no scheduled tasks were registered."
}
else {
    Write-Host "Task registration pass finished for $userId."
    Write-Host "The proxy runs independently from Codex and is checked every five minutes."
    Write-Host "Use -Uninstall to remove only these two task names."
}
