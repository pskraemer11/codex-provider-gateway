<#
.SYNOPSIS
    Switch the Codex root configuration between OpenRouter and the Go/Zen proxy.
.DESCRIPTION
    Changes only model_provider, model, and model_catalog_json in the selected
    config.toml, backing up the file before writing. Switching to proxy first
    starts/checks the local proxy and selects a model from its catalog. CLI
    profiles such as `codex --profile go` are separate and are not changed.
    Use Get-Help or -? for PowerShell help; --help and -Help display this detailed help.
.PARAMETER Target
    Optional target: proxy or openrouter. Without it, switch between those two.
.PARAMETER Check
    Show the current values without starting the proxy or writing configuration.
.PARAMETER Restart
    Restart Codex Desktop after the switch. This applies only to the default
    Codex config; it does not restart a Codex TUI session.
.PARAMETER Port
    Loopback port passed to the proxy watchdog when switching to proxy. Defaults to 8787.
.PARAMETER ConfigPath
    Codex config.toml to inspect or update. Defaults to ~/.codex/config.toml.
.PARAMETER UnboundArguments
    Reserved for the -Help/--help compatibility form. Do not specify directly;
    all other unrecognized arguments are rejected.
.EXAMPLE
    .\switch-provider.ps1 -Check

    Show the current provider and root settings without side effects.
.EXAMPLE
    .\switch-provider.ps1 -Target proxy

    Wait for proxy health, then select the proxy catalog and back up/update the default config.
.EXAMPLE
    .\switch-provider.ps1 -Target openrouter -Restart

    Switch the default config to OpenRouter and restart Codex Desktop.
.EXAMPLE
    .\switch-provider.ps1 --help

    Display this script's detailed help.
.NOTES
    Requires PowerShell 7. The restart option targets Codex Desktop, not the TUI.
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet("proxy", "openrouter")]
    [string]$Target,
    [switch]$Check,
    [switch]$Restart,
    [ValidateRange(1, 65535)]
    [int]$Port = 8787,
    [string]$ConfigPath = (Join-Path $HOME ".codex\config.toml"),
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
$defaultConfigPath = [System.IO.Path]::GetFullPath((Join-Path $HOME ".codex\config.toml"))
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$codexDirectory = (Split-Path -Parent $ConfigPath) -replace "\\", "/"

$variants = @{
    proxy = @{
        model_provider = "opencode-proxy"
        model = "opencode-go/gpt-6-luna"
        model_catalog_json = "$codexDirectory/proxy-catalog.json"
    }
    openrouter = @{
        model_provider = "openrouter"
        model = "deepseek/deepseek-v4.1-flash-1017"
        model_catalog_json = "$codexDirectory/picker-catalog.json"
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Codex config was not found: $ConfigPath"
}
$raw = Get-Content -LiteralPath $ConfigPath -Raw

function Get-TomlRootInfo {
    param([string]$Text)

    $state = "normal"
    $arrayDepth = 0
    $masked = [System.Text.StringBuilder]::new()
    $linePattern = "(?:[^\r\n]*)(?:\r\n|\n|\r|$)"
    foreach ($lineMatch in [regex]::Matches($Text, $linePattern)) {
        if ($lineMatch.Length -eq 0) { continue }
        $line = [regex]::Replace($lineMatch.Value, "[\r\n]+$", "")
        if ($state -eq "normal" -and $arrayDepth -eq 0 -and
            $line -match '^[ \t]*(?:\[\[[^\r\n]*\]\]|\[[^\r\n]*\])[ \t]*(?:#.*)?$') {
            return [pscustomobject]@{ EndIndex = $lineMatch.Index; MaskedText = $masked.ToString() }
        }

        $maskedLine = [System.Text.StringBuilder]::new()
        for ($index = 0; $index -lt $line.Length;) {
            if ($state -eq "multiline-basic") {
                if ($index + 2 -lt $line.Length -and $line.Substring($index, 3) -ceq '"""') {
                    $backslashes = 0
                    for ($cursor = $index - 1; $cursor -ge 0 -and $line[$cursor] -eq [char]92; $cursor--) {
                        $backslashes++
                    }
                    if ($backslashes % 2 -eq 0) {
                        $state = "normal"
                        $null = $maskedLine.Append('   ')
                        $index += 3
                        continue
                    }
                }
                $null = $maskedLine.Append([char]32)
                $index++
                continue
            }
            if ($state -eq "multiline-literal") {
                if ($index + 2 -lt $line.Length -and $line.Substring($index, 3) -ceq "'''") {
                    $state = "normal"
                    $null = $maskedLine.Append('   ')
                    $index += 3
                    continue
                }
                $null = $maskedLine.Append([char]32)
                $index++
                continue
            }
            if ($state -eq "basic") {
                if ($line[$index] -eq [char]92) {
                    $null = $maskedLine.Append([char]32)
                    if ($index + 1 -lt $line.Length) {
                        $null = $maskedLine.Append([char]32)
                        $index += 2
                    }
                    else { $index++ }
                    continue
                }
                $null = $maskedLine.Append([char]32)
                if ($line[$index] -eq '"') { $state = "normal" }
                $index++
                continue
            }
            if ($state -eq "literal") {
                $null = $maskedLine.Append([char]32)
                if ($line[$index] -eq "'") { $state = "normal" }
                $index++
                continue
            }

            if ($arrayDepth -eq 0 -and
                $line.Substring(0, $index) -match '^[ \t]*$' -and
                ($line[$index] -eq '"' -or $line[$index] -eq "'")) {
                $quote = $line[$index]
                $cursor = $index + 1
                $quoteEnd = -1
                while ($cursor -lt $line.Length) {
                    if ($quote -eq '"' -and $line[$cursor] -eq [char]92) {
                        $cursor += 2
                        continue
                    }
                    if ($line[$cursor] -eq $quote) {
                        $quoteEnd = $cursor
                        break
                    }
                    $cursor++
                }
                if ($quoteEnd -ge 0) {
                    $afterKey = $quoteEnd + 1
                    while ($afterKey -lt $line.Length -and ($line[$afterKey] -eq ' ' -or $line[$afterKey] -eq [char]9)) {
                        $afterKey++
                    }
                    if ($afterKey -lt $line.Length -and $line[$afterKey] -eq '=') {
                        $null = $maskedLine.Append($line.Substring($index, $afterKey - $index + 1))
                        $index = $afterKey + 1
                        continue
                    }
                }
            }

            if ($line[$index] -eq '#') {
                $null = $maskedLine.Append(' ' * ($line.Length - $index))
                $index = $line.Length
                break
            }
            if ($line[$index] -eq '"') {
                if ($index + 2 -lt $line.Length -and $line.Substring($index, 3) -ceq '"""') {
                    $state = "multiline-basic"
                    $null = $maskedLine.Append('   ')
                    $index += 3
                }
                else {
                    $state = "basic"
                    $null = $maskedLine.Append([char]32)
                    $index++
                }
                continue
            }
            if ($line[$index] -eq "'") {
                if ($index + 2 -lt $line.Length -and $line.Substring($index, 3) -ceq "'''") {
                    $state = "multiline-literal"
                    $null = $maskedLine.Append('   ')
                    $index += 3
                }
                else {
                    $state = "literal"
                    $null = $maskedLine.Append([char]32)
                    $index++
                }
                continue
            }
            $null = $maskedLine.Append($line[$index])
            if ($line[$index] -eq '[') { $arrayDepth++ }
            elseif ($line[$index] -eq ']') { $arrayDepth-- }
            if ($arrayDepth -lt 0) { throw "Codex config has an unmatched TOML closing bracket." }
            $index++
        }
        $lineEnding = $lineMatch.Value.Substring($line.Length)
        $null = $masked.Append($maskedLine.ToString()).Append($lineEnding)
        if ($state -eq "basic" -or $state -eq "literal") {
            throw "Codex config has an unterminated TOML string; no change was made."
        }
    }

    if ($state -ne "normal" -or $arrayDepth -ne 0) {
        throw "Could not determine the Codex config's root TOML section; no change was made."
    }
    return [pscustomobject]@{ EndIndex = $Text.Length; MaskedText = $masked.ToString() }
}

function Get-CurrentValue {
    param([string]$Text, [string]$Key)
    $rootInfo = Get-TomlRootInfo $Text
    $root = $Text.Substring(0, $rootInfo.EndIndex)
    $escapedKey = [regex]::Escape($Key)
    $keyPattern = "(?:$escapedKey|`"$escapedKey`"|'$escapedKey')"
    $assignments = [regex]::Matches($rootInfo.MaskedText, "(?m)^[ \t]*$keyPattern[ \t]*=")
    if ($assignments.Count -gt 1) { throw "Codex config has duplicate root-level '$Key' assignments." }
    if ($assignments.Count -eq 0) { return "(not set)" }

    $matchIndex = $assignments[0].Index
    $lineStart = $root.LastIndexOf("`n", $matchIndex) + 1
    $lineEnd = $root.IndexOfAny([char[]]@("`r", "`n"), $lineStart)
    if ($lineEnd -lt 0) { $lineEnd = $root.Length }
    $line = $root.Substring($lineStart, $lineEnd - $lineStart)
    $valuePattern = "^[ \t]*$keyPattern[ \t]*=[ \t]*(?:`"([^`"\r\n]*)`"|'([^'\r\n]*)')"
    $match = [regex]::Match($line, $valuePattern)
    if (-not $match.Success) { return "(not set)" }
    if ($match.Groups[1].Success) { return $match.Groups[1].Value }
    return $match.Groups[2].Value
}

$current = [ordered]@{
    model_provider = Get-CurrentValue $raw "model_provider"
    model = Get-CurrentValue $raw "model"
    model_catalog_json = Get-CurrentValue $raw "model_catalog_json"
}
$active = switch ($current.model_provider) {
    "opencode-proxy" { "proxy"; break }
    "opencode-go" { "direct Go (legacy)"; break }
    "openrouter" { "openrouter"; break }
    default { "unknown" }
}

Write-Host "active: $active"
$current.GetEnumerator() | ForEach-Object {
    Write-Host ("  {0,-19} {1}" -f $_.Key, $_.Value)
}
if ($Check) { return }

function Restart-CodexDesktop {
    if ($ConfigPath -ne $defaultConfigPath) {
        Write-Host "Restart skipped: ConfigPath is not the default Codex config."
        return
    }
    Get-Process ChatGPT -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    Start-Process "shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App"
    Write-Host "Codex Desktop restarted."
}

function Get-SafeCatalogSlug {
    param([object]$Slug, [string]$CatalogPath)

    if ($Slug -isnot [string]) {
        throw "Target catalog has a non-string model slug: $CatalogPath"
    }
    if ([string]::IsNullOrWhiteSpace($Slug)) {
        throw "Target catalog has an empty model slug: $CatalogPath"
    }
    if ($Slug.Length -gt 512 -or [regex]::IsMatch($Slug, '\p{Cc}')) {
        throw "Target catalog has an oversized or control-character model slug: $CatalogPath"
    }
    return $Slug
}

function ConvertTo-TomlBasicString {
    param([string]$Value)
    return ConvertTo-Json -InputObject $Value -Compress
}

function Test-ProviderTable {
    param([string]$Text, [string]$Name)

    $escaped = [regex]::Escape($Name)
    $patterns = @(
        "^[ \t]*\[model_providers\.$escaped\][ \t]*(?:#.*)?$",
        "^[ \t]*\[model_providers\.`"$escaped`"\][ \t]*(?:#.*)?$",
        "^[ \t]*\[model_providers\.'$escaped'\][ \t]*(?:#.*)?$"
    )
    return $patterns | Where-Object { [regex]::IsMatch($Text, $_, [System.Text.RegularExpressions.RegexOptions]::Multiline) } |
        Select-Object -First 1
}

function Write-TextAtomically {
    param([string]$Path, [string]$Contents)

    $directory = [System.IO.Path]::GetDirectoryName($Path)
    $temporary = Join-Path $directory (".{0}.{1}.tmp" -f ([System.IO.Path]::GetFileName($Path)), [guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText($temporary, $Contents, [System.Text.UTF8Encoding]::new($false))
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Codex config disappeared before the atomic replacement: $Path"
        }
        [System.IO.File]::Move($temporary, $Path, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Set-RootTomlStringValue {
    param([string]$Text, [string]$Key, [string]$Value)

    $rootInfo = Get-TomlRootInfo $Text
    $root = $Text.Substring(0, $rootInfo.EndIndex)
    $tail = $Text.Substring($rootInfo.EndIndex)
    $escapedKey = [regex]::Escape($Key)
    $keyPattern = "(?:$escapedKey|`"$escapedKey`"|'$escapedKey')"
    $assignments = [regex]::Matches($rootInfo.MaskedText, "(?m)^[ \t]*$keyPattern[ \t]*=")
    if ($assignments.Count -gt 1) {
        throw "Codex config has duplicate root-level '$Key' assignments; no change was made."
    }

    $tomlValue = ConvertTo-TomlBasicString $Value
    if ($assignments.Count -eq 0) {
        if ($root.Length -gt 0 -and -not $root.EndsWith("`n") -and -not $root.EndsWith("`r")) {
            $root += "`r`n"
        }
        return $root + "$Key = $tomlValue`r`n" + $tail
    }

    $lineStart = $root.LastIndexOf("`n", $assignments[0].Index) + 1
    $lineEnd = $root.IndexOfAny([char[]]@("`r", "`n"), $lineStart)
    if ($lineEnd -lt 0) { $lineEnd = $root.Length }
    $line = $root.Substring($lineStart, $lineEnd - $lineStart)
    $quotedBasic = '"(?:\\.|[^"\\])*"'
    $quotedLiteral = "'(?:''|[^'])*'"
    $shapePattern = "^(?<prefix>[ \t]*$keyPattern[ \t]*=[ \t]*)(?<value>(?:$quotedBasic|$quotedLiteral))(?<suffix>[ \t]*(?:#.*)?)$"
    $shapeMatch = [regex]::Match($line, $shapePattern)
    if (-not $shapeMatch.Success) {
        throw "Root-level '$Key' is not a single-line TOML string; no change was made."
    }

    $replacement = $shapeMatch.Groups["prefix"].Value + $tomlValue + $shapeMatch.Groups["suffix"].Value
    $root = $root.Substring(0, $lineStart) + $replacement + $root.Substring($lineEnd)
    return $root + $tail
}

function Get-CatalogDefaultModel {
    param([string]$CatalogPath, [string]$Preferred)

    if (-not (Test-Path -LiteralPath $CatalogPath -PathType Leaf)) {
        throw "Target catalog is missing: $CatalogPath. Build the filtered provider catalog first."
    }
    $catalog = Get-Content -LiteralPath $CatalogPath -Raw | ConvertFrom-Json
    $models = @($catalog.models)
    if ($models.Count -eq 0) { throw "Target catalog contains no models: $CatalogPath" }

    $preferredEntry = $models | Where-Object { $_.slug -ceq $Preferred } | Select-Object -First 1
    if ($preferredEntry) {
        return Get-SafeCatalogSlug -Slug $preferredEntry.slug -CatalogPath $CatalogPath
    }
    $first = $models | Sort-Object priority | Select-Object -First 1
    $firstSlug = Get-SafeCatalogSlug -Slug $first.slug -CatalogPath $CatalogPath
    Write-Host "Preferred model is absent; using highest catalog priority: $firstSlug"
    return $firstSlug
}

if ([string]::IsNullOrWhiteSpace($Target)) {
    if ($current.model_provider -eq "opencode-proxy") {
        $Target = "openrouter"
    }
    elseif ($current.model_provider -eq "openrouter") {
        $Target = "proxy"
    }
    else {
        throw "Cannot infer target from model_provider=$($current.model_provider). Specify -Target proxy or -Target openrouter."
    }
    Write-Host "Switching automatically: $active -> $Target"
}

$wanted = $variants[$Target]
if (-not (Test-ProviderTable -Text $raw -Name $wanted.model_provider)) {
    throw "Target provider table [model_providers.$($wanted.model_provider)] is missing. Add the documented provider configuration first."
}

if ($Target -eq "proxy") {
    $watchdogPath = Join-Path $PSScriptRoot "watchdog-proxy.ps1"
    if (-not (Test-Path -LiteralPath $watchdogPath -PathType Leaf)) {
        throw "Proxy watchdog is missing: $watchdogPath"
    }
    $powerShell = Join-Path $PSHOME "pwsh.exe"
    if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
        throw "The current PowerShell 7 executable was not found: $powerShell"
    }
    & $powerShell -NoLogo -NoProfile -File $watchdogPath -Port $Port -Quiet
    $watchdogExitCode = $LASTEXITCODE
    if ($watchdogExitCode -ne 0) {
        throw "Proxy did not become healthy; provider config was not changed. Watchdog exit code: $watchdogExitCode"
    }
    Write-Host "Proxy /health is ready on port $Port."
}

$wanted.model = Get-CatalogDefaultModel $wanted.model_catalog_json $wanted.model
$updated = $raw
foreach ($key in $wanted.Keys) {
    $updated = Set-RootTomlStringValue -Text $updated -Key $key -Value ([string]$wanted[$key])
}

if ($updated -ceq $raw) {
    Write-Host "No config change needed."
    if ($Restart) { Restart-CodexDesktop }
    return
}

$running = Get-Process ChatGPT -ErrorAction SilentlyContinue
if ($ConfigPath -eq $defaultConfigPath -and $running -and -not $Restart) {
    Write-Host "Codex Desktop is running (PID $($running[0].Id))."
    Write-Host "Use -Restart or fully quit Codex first; no config was changed."
    return
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$backupDirectory = Join-Path ([System.IO.Path]::GetDirectoryName($ConfigPath)) "backups"
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupPath = Join-Path $backupDirectory "config.toml.backup-$stamp-before-switch-$Target"
if (Test-Path -LiteralPath $backupPath) {
    $backupPath = Join-Path $backupDirectory "config.toml.backup-$stamp-$([guid]::NewGuid().ToString('N'))-before-switch-$Target"
}
Copy-Item -LiteralPath $ConfigPath -Destination $backupPath
Write-TextAtomically -Path $ConfigPath -Contents $updated

Write-Host "Switched to: $Target"
Write-Host "Backup: $backupPath"
if ($Restart) {
    Restart-CodexDesktop
}
else {
    Write-Host "Restart Codex Desktop for the new provider and catalog to take effect."
}
