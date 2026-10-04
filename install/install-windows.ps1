<#
  Geekatplay 3D Layers for Krita - installer for Windows
  by Geekatplay Studio - https://www.geekatplay.com

  Copies the plugin into Krita's plugin folder (%APPDATA%\krita\pykrita) and switches it on.
  Run "Install on Windows.cmd" next to this folder; -Uninstall removes the plugin again.
  Your 3D model library and keys (in %APPDATA%\Geekatplay\3D Layers) are never touched.
#>
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $PSScriptRoot
$Name = "geekatplay_3d_layers"
$PyKrita = Join-Path $env:APPDATA "krita\pykrita"
$KritaRc = Join-Path $env:LOCALAPPDATA "kritarc"

function Say($text, $color = "Gray") { Write-Host "  $text" -ForegroundColor $color }

Write-Host ""
Say "Geekatplay 3D Layers for Krita" "White"
Write-Host ""

# Krita writes its settings when it closes, so it must not be running while we switch the plugin on.
while (Get-Process -Name krita -ErrorAction SilentlyContinue) {
    Say "Krita is open. Please close Krita (save your work first), then press Enter here." "Yellow"
    [void](Read-Host)
}

$Target = Join-Path $PyKrita $Name
$Desktop = Join-Path $PyKrita "$Name.desktop"
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
if (Test-Path $Desktop) { Remove-Item -Force $Desktop }

$rc = if (Test-Path $KritaRc) { [IO.File]::ReadAllText($KritaRc) } else { "" }
$rc = [regex]::Replace($rc, "(?m)^enable_$Name=.*\r?\n?", "")

if ($Uninstall) {
    [IO.File]::WriteAllText($KritaRc, $rc)
    Say "Removed. Your model library and keys are still in %APPDATA%\Geekatplay\3D Layers." "Green"
    exit 0
}

$Source = Join-Path $Here $Name
if (-not (Test-Path (Join-Path $Source "__init__.py"))) {
    Say "The plugin files were not found next to this installer. Unzip the whole download first, then run Install on Windows.cmd from the unzipped folder." "Red"
    exit 1
}
New-Item -ItemType Directory -Force $PyKrita | Out-Null
Copy-Item -Recurse $Source $Target
Copy-Item (Join-Path $Here "$Name.desktop") $Desktop

# Switch it on: Krita keeps plugin switches in kritarc, section [python].
if ($rc -match "(?m)^\[python\]\r?$") {
    $rc = [regex]::Replace($rc, "(?m)^\[python\]\r?\n", "[python]`r`nenable_$Name=true`r`n", 1)
} else {
    $rc = $rc.TrimEnd() + "`r`n`r`n[python]`r`nenable_$Name=true`r`n"
}
[IO.File]::WriteAllText($KritaRc, $rc)

Say "Installed." "Green"
Write-Host ""
Say "Next:"
Say "1. Open Krita."
Say "2. Settings > Dockers > 3D Layers shows the panel."
Say "3. On its Create tab, click 'Try the sample model'."
Write-Host ""
