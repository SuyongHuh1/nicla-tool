param(
    [string]$DefaultSsid = "DESKTOP-UB7F2AI 9369",
    [string]$BoardDrive = "E:\"
)

$ErrorActionPreference = "Stop"
$configPath = Join-Path $BoardDrive "wifi_config.py"
if (-not (Test-Path -LiteralPath $BoardDrive -PathType Container)) {
    throw "Nicla drive not found: $BoardDrive"
}

$ssid = Read-Host "Hotspot SSID [$DefaultSsid]"
if ([string]::IsNullOrWhiteSpace($ssid)) {
    $ssid = $DefaultSsid
}
$securePassword = Read-Host "Hotspot password (hidden)" -AsSecureString
$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    if ($password.Length -lt 8) {
        throw "Wi-Fi password must contain at least 8 characters."
    }
    $ssidEscaped = $ssid.Replace('\', '\\').Replace('"', '\"')
    $passwordEscaped = $password.Replace('\', '\\').Replace('"', '\"')
    $content = @"
# Generated locally. Do not commit this file.
WIFI_MODE = "auto"
WIFI_STA_TIMEOUT_MS = 15000
WIFI_SSID = "$ssidEscaped"
WIFI_PASS = "$passwordEscaped"

# Direct-board fallback if the Windows hotspot is unavailable.
AP_SSID = "nicla-cam"
AP_PASS = "nicla1234"
"@
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($configPath, $content, $utf8NoBom)
}
finally {
    if ($passwordPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr)
    }
    $password = $null
    $securePassword.Dispose()
}

Write-Host ""
Write-Host "Saved Nicla Wi-Fi configuration without printing the password:" -ForegroundColor Green
Write-Host $configPath
Write-Host "Return to Codex and say: saved"
