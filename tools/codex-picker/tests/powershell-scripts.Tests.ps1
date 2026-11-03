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

$helpExpectations = @{
    "switch-provider.ps1" = @("-Target", "-Check", "-Restart", "-Port", "-ConfigPath", "-Help")
    "watchdog-proxy.ps1" = @("-Port", "-Quiet", "-Executable", "-ProjectRoot", "-Help", "-WhatIf", "-Confirm")
    "install-proxy-autostart.ps1" = @(
        "-Port", "-ReplaceExisting", "-Uninstall", "-Help", "-WhatIf", "-Confirm"
    )
}
$powerShell = Join-Path $PSHOME "pwsh.exe"
if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
    throw "PowerShell 7 executable was not found: $powerShell"
}

foreach ($script in $scripts) {
    if (-not $helpExpectations.ContainsKey($script.Name)) {
        throw "Missing help expectations for $($script.Name)."
    }
    foreach ($form in @("Long", "Short")) {
        $helpText = if ($form -eq "Long") {
            & { param($ScriptPath) & $ScriptPath --help 2>&1 | Out-String -Width 200 } $script.FullName
        }
        else {
            & { param($ScriptPath) & $ScriptPath -Help 2>&1 | Out-String -Width 200 } $script.FullName
        }
        if ($helpText -notmatch [regex]::Escape($script.Name)) {
            throw "$form help for $($script.Name) did not identify the script."
        }
        foreach ($option in $helpExpectations[$script.Name]) {
            if ($helpText -notmatch "(?m)^\s*$([regex]::Escape($option))\b") {
                throw "$form help for $($script.Name) did not explain $option."
            }
        }
        if ($helpText -match "UnboundArguments") {
            throw "$form help for $($script.Name) exposed the removed internal argument."
        }
    }

    $externalHelpText = & $powerShell -NoLogo -NoProfile -File $script.FullName --help 2>&1 | Out-String -Width 200
    if ($LASTEXITCODE -ne 0) {
        throw "External --help for $($script.Name) exited with code $LASTEXITCODE."
    }
    if ($externalHelpText -notmatch [regex]::Escape($script.Name) -or $externalHelpText -match "RemainingArguments") {
        throw "External --help for $($script.Name) did not return clean detailed help."
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

    $checkCatalog = Join-Path $temporary "check-catalog.json"
    [System.IO.File]::WriteAllText(
        $checkCatalog,
        '{"models":[{"slug":"catalogued-model"}]}',
        [System.Text.UTF8Encoding]::new($false)
    )
    $checkConfigPath = Join-Path $temporary "check.toml"
    $checkCatalogToml = $checkCatalog -replace '\\', '/'
    $checkConfig = @"
model_provider = "opencode-proxy"
model = "missing-model"
model_catalog_json = "$checkCatalogToml"

[model_providers.opencode-proxy]
name = "OpenCode Go + Zen (local proxy)"
base_url = "http://127.0.0.1:8787/v1"
wire_api = "responses"
env_key = "OPENCODE_GO_API_KEY"
"@
    [System.IO.File]::WriteAllText($checkConfigPath, $checkConfig, [System.Text.UTF8Encoding]::new($false))
    $checkOutput = & $switchScript -ConfigPath $checkConfigPath -Check | Out-String
    if ($checkOutput -notmatch "catalog: STALE" -or $checkOutput -notmatch "provider auth: WARN") {
        throw "Provider check did not report the stale catalog and the env_key provider shape."
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
