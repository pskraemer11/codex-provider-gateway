#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$pickerRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$scripts = Get-ChildItem -LiteralPath $pickerRoot -Filter "*.ps1" -File
if ($scripts.Count -eq 0) {
    throw "No PowerShell scripts found under $pickerRoot"
}

foreach ($script in $scripts) {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw "PowerShell parse failed for $($script.Name): $($errors[0].Message)"
    }
}

$hiddenRun = Join-Path $pickerRoot "hidden-run.vbs"
if (-not (Test-Path -LiteralPath $hiddenRun -PathType Leaf)) {
    throw "Hidden console launcher is missing: $hiddenRun"
}
$installerText = Get-Content -LiteralPath (Join-Path $pickerRoot "install-proxy-autostart.ps1") -Raw
if ($installerText -notmatch 'wscript\.exe' -or $installerText -notmatch 'hidden-run\.vbs') {
    throw "Autostart installer does not route scheduled tasks through the hidden console launcher."
}

$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("opencode-go-picker-tests-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $configPath = Join-Path $temporary "config.toml"
    $catalogPath = Join-Path $temporary "picker-catalog.json"
    $config = @'
model_provider = "opencode-proxy"
model = "old-model"
model_catalog_json = "old-catalog.json"

[model_providers.openrouter]
name = "openrouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"

[model_providers.opencode-proxy]
name = "OpenCode Go + Zen (local proxy)"
base_url = "http://127.0.0.1:8787/v1"
wire_api = "responses"
env_key = "OPENCODE_GO_API_KEY"
'@
    $config = $config -replace "(?<!\r)\n", "`r`n"
    [System.IO.File]::WriteAllText($configPath, $config, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText(
        $catalogPath,
        '{"models":[{"slug":"deepseek/deepseek-v4.1-flash-1017","priority":1}]}',
        [System.Text.UTF8Encoding]::new($false)
    )

    $switchScript = Join-Path $pickerRoot "switch-provider.ps1"
    & $switchScript -ConfigPath $configPath -Target openrouter | Out-Null
    $updated = Get-Content -LiteralPath $configPath -Raw
    if ($updated -notmatch 'model_provider = "openrouter"') {
        throw "Provider switch did not update model_provider."
    }
    if ($updated -notmatch 'model = "deepseek/deepseek-v4\.1-flash-1017"') {
        throw "Provider switch did not select the catalog model."
    }
    if (Get-ChildItem -LiteralPath $temporary -Filter ".*.tmp" -Force -File) {
        throw "Atomic config write left a temporary file behind."
    }

    $missingProviderPath = Join-Path $temporary "missing-provider.toml"
    [System.IO.File]::WriteAllText(
        $missingProviderPath,
        "model_provider = `"opencode-proxy`"`nmodel = `"old`"`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    $rejected = $false
    try {
        & $switchScript -ConfigPath $missingProviderPath -Target openrouter | Out-Null
    }
    catch {
        $rejected = $_.Exception.Message -match 'provider table'
    }
    if (-not $rejected) {
        throw "Provider switch accepted a config without the target provider table."
    }

    $dummyExecutable = Join-Path $temporary "opencode-go-proxy.cmd"
    [System.IO.File]::WriteAllText($dummyExecutable, "@exit /b 0`r`n", [System.Text.UTF8Encoding]::new($false))
    $watchdog = Join-Path $pickerRoot "watchdog-proxy.ps1"
    & $watchdog -Port 65534 -Executable $dummyExecutable -WhatIf -Quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Watchdog WhatIf smoke test failed with exit code $LASTEXITCODE."
    }

    Write-Host "PowerShell script parser and fixture tests passed."
}
finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
