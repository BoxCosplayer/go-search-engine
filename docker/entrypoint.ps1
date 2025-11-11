$ErrorActionPreference = 'Stop'

param(
    [string]$Executable = 'C:\app\go-server.exe',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$env:GO_HOST = if ($env:GO_HOST) { $env:GO_HOST } else { '127.0.0.1' }
$env:GO_PORT = if ($env:GO_PORT) { $env:GO_PORT } else { '5000' }
$env:GO_DB_PATH = if ($env:GO_DB_PATH) { $env:GO_DB_PATH } else { 'C:\data\links.db' }

function Initialize-Config {
    param(
        [string]$ConfigPath,
        [string]$TemplateSource
    )

    $configDir = Split-Path -Path $ConfigPath -Parent
    if (-not (Test-Path -Path $configDir)) {
        New-Item -Path $configDir -ItemType Directory -Force | Out-Null
    }

    if (Test-Path -Path $ConfigPath) {
        return
    }

    if (Test-Path -Path $TemplateSource) {
        Copy-Item -Path $TemplateSource -Destination $ConfigPath
    }
    else {
        # Minimal default when the template is unavailable.
        $default = @{
            host           = '127.0.0.1'
            port           = 5000
            debug          = $false
            'db-path'      = 'C:\data\links.db'
            'allow-files'  = $false
            'fallback-url' = ''
            'file-allow'   = @()
        }
        $default | ConvertTo-Json -Depth 4 | Set-Content -Path $ConfigPath -Encoding utf8NoBOM
        return
    }

    try {
        $json = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Failed to parse config template: $_. Using safe defaults."
        $json = [ordered]@{
            host           = '127.0.0.1'
            port           = 5000
            debug          = $false
            'db-path'      = 'C:\data\links.db'
            'allow-files'  = $false
            'fallback-url' = ''
            'file-allow'   = @()
        }
    }

    if (-not $json.host -or $json.host -eq '127.0.0.1') {
        $json.host = $env:GO_HOST
    }
    if (-not $json.port -or $json.port -eq 0) {
        $json.port = [int]$env:GO_PORT
    }
    if (-not $json.'db-path' -or $json.'db-path' -eq 'backend/app/data/links.db' -or $json.'db-path' -eq 'links.db') {
        $json.'db-path' = $env:GO_DB_PATH
    }
    if (-not $json.'file-allow') {
        $json.'file-allow' = @()
    }

    $json | ConvertTo-Json -Depth 6 | Set-Content -Path $ConfigPath -Encoding utf8NoBOM
}

function Ensure-DbDirectory {
    param([string]$ConfigPath)
    try {
        $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
        $dbPath = if ($cfg.'db-path') { $cfg.'db-path' } else { 'C:\data\links.db' }
    }
    catch {
        Write-Warning "Unable to parse $ConfigPath for db-path. Falling back to C:\data\links.db. $_"
        $dbPath = 'C:\data\links.db'
    }

    $dbDir = Split-Path -Path $dbPath -Parent
    if ($dbDir -and -not (Test-Path -Path $dbDir)) {
        New-Item -Path $dbDir -ItemType Directory -Force | Out-Null
    }
}

function Update-ConfigFromEnv {
    param([string]$ConfigPath)

    try {
        $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Unable to parse $ConfigPath for overrides. $_"
        return
    }

    $writeBack = $false
    if ($env:GO_HOST -and $cfg.host -ne $env:GO_HOST) {
        $cfg.host = $env:GO_HOST
        $writeBack = $true
    }
    if ($env:GO_PORT) {
        $desiredPort = [int]$env:GO_PORT
        if ($cfg.port -ne $desiredPort) {
            $cfg.port = $desiredPort
            $writeBack = $true
        }
    }
    if ($env:GO_DB_PATH -and $cfg.'db-path' -ne $env:GO_DB_PATH) {
        $cfg.'db-path' = $env:GO_DB_PATH
        $writeBack = $true
    }

    if ($writeBack) {
        $cfg | ConvertTo-Json -Depth 6 | Set-Content -Path $ConfigPath -Encoding utf8NoBOM
    }
}

$configPath = $env:GO_CONFIG_PATH
if (-not $configPath) {
    $configPath = 'C:\data\config.json'
    $env:GO_CONFIG_PATH = $configPath
}

$templateSource = Join-Path -Path 'C:\app' -ChildPath 'config-template.txt'
Initialize-Config -ConfigPath $configPath -TemplateSource $templateSource
Update-ConfigFromEnv -ConfigPath $configPath
Ensure-DbDirectory -ConfigPath $configPath

if (-not (Test-Path -Path $Executable)) {
    throw "Executable not found at $Executable"
}

Write-Host "Starting go-server from $Executable with config $configPath"
& $Executable @AppArgs
exit $LASTEXITCODE
