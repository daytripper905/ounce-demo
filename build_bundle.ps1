# build_bundle.ps1  -  builds the customer-ready portable folder for An Ounce of Prevention.
# Run it from the folder that holds app.py (your dev folder), in PowerShell:
#     powershell -ExecutionPolicy Bypass -File .\build_bundle.ps1
# Options:
#     -Out   C:\Temp\OunceBundle     where to build (default shown)
#     -Stamp                         stamp your public key into the bundle's app.py
#                                    (needs license_private.key in this folder)
#     -Demo                          build the free DEMO (30 days, 10 own assets); also writes the zip
#     -PublicKey <64 hex>            stamp this PUBLIC key (no private key file needed - used by the automatic build)
# VENDOR-ONLY. Never ship this file.

param(
    [string]$Out = "C:\Temp\OunceBundle",
    [switch]$Stamp,
    [switch]$Demo,
    [string]$PublicKey = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the download progress bar makes downloads very slow in PowerShell
$src = (Get-Location).Path
$pyVer = "3.12.8"
$pyZip = "python-$pyVer-embed-amd64.zip"
$pyUrl = "https://www.python.org/ftp/python/$pyVer/$pyZip"
$pipUrl = "https://bootstrap.pypa.io/get-pip.py"
$folderName = "An Ounce of Prevention"
$bundle = Join-Path $Out $folderName

if (-not (Test-Path (Join-Path $src "app.py"))) { throw "app.py not found here. Run this from your dev folder." }

Write-Host "1/7  Clean build folder: $bundle"
if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
New-Item -ItemType Directory -Path $bundle | Out-Null
$pyDir = Join-Path $bundle "python"
New-Item -ItemType Directory -Path $pyDir | Out-Null

Write-Host "2/7  Download embedded Python $pyVer"
$tmpZip = Join-Path $Out $pyZip
Invoke-WebRequest -Uri $pyUrl -OutFile $tmpZip
Expand-Archive -Path $tmpZip -DestinationPath $pyDir -Force

Write-Host "3/7  Enable packages in embedded Python"
$pth = Get-ChildItem $pyDir -Filter "python*._pth" | Select-Object -First 1
$lines = Get-Content $pth.FullName
$lines = $lines | ForEach-Object { if ($_ -match '^\s*#\s*import site') { "import site" } else { $_ } }
$lines += "Lib\site-packages"
Set-Content -Path $pth.FullName -Value $lines

Write-Host "4/7  Install pip, then streamlit, pandas, reportlab (a few minutes)"
$getpip = Join-Path $Out "get-pip.py"
Invoke-WebRequest -Uri $pipUrl -OutFile $getpip
$py = Join-Path $pyDir "python.exe"
& $py $getpip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }
# Versions are PINNED to the ones that passed run_selftest_full.bat on 2026-10-18 (156/156). The app uses features newer Streamlit
# releases may remove. To move to newer versions: change these numbers, rebuild, then re-run run_selftest_full.bat and check by eye.
& $py -m pip install --no-warn-script-location "streamlit==1.66.0" "pandas==3.0.6" "reportlab==5.0.1"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "5/7  Copy the app files (public files only)"
Copy-Item (Join-Path $src "app.py") $bundle
foreach ($img in @("BlackMarble_2016_3km.jpg", "world.jpg")) {
    $p = Join-Path $src $img
    if (Test-Path $p) { Copy-Item $p $bundle } else { Write-Host "     (note: $img not found, skipped)" }
}
$samples = Join-Path $src "Sample CSV files"
if (Test-Path $samples) { Copy-Item $samples (Join-Path $bundle "Sample CSV files") -Recurse } else { Write-Host "     (note: Sample CSV files folder not found, skipped)" }
New-Item -ItemType Directory -Path (Join-Path $bundle ".streamlit") | Out-Null
@"
[browser]
gatherUsageStats = false

[server]
address = "127.0.0.1"
headless = false
runOnSave = false
fileWatcherType = "none"

[theme]
base = "light"
"@ | Set-Content -Path (Join-Path $bundle ".streamlit\config.toml") -Encoding ASCII

@"
@echo off
cd /d "%~dp0"
title An Ounce of Prevention
echo Starting An Ounce of Prevention...
echo Your browser will open in a moment. Close this black window to stop the program.
set "OUNCE_DB_PATH=%~dp0"
"%~dp0python\python.exe" -m streamlit run app.py
pause
"@ | Set-Content -Path (Join-Path $bundle "Start An Ounce of Prevention.bat") -Encoding ASCII

if ($Demo) {
@"
An Ounce of Prevention - FREE DEMO
==================================
This is a working copy of the real program. It runs for 30 days from the first time you start it,
comes with sample data to explore, and lets you add up to 8 assets and 5 asset groups of your own.
Your sample data and anything you enter is kept. After 30 days the demo becomes read-only:
you can still look, print and back up - nothing is deleted.

TO START
1. Right-click the downloaded zip file and choose "Extract All". (Do not run it from inside the zip.)
2. Open the extracted folder and double-click  "Start An Ounce of Prevention.bat".
3. Windows may say "Windows protected your PC". That is normal for new software from a small company.
   Click "More info", then "Run anyway".
4. Your web browser opens the program. Nothing is sent over the internet.
5. To stop: close the black window.

Your data is stored in the file OunceOfPrevention.db in this folder. Copy this whole folder to keep it safe or move it.

TO KEEP USING IT
Buy a licence at www.bioship.ca. You will get a licence code by email.
In the program open "Users & Security", paste the code under Licence, and click Activate Licence.
The limits go away and everything you entered stays.

Questions: support@bioship.ca     (c) BioShip Inc.   www.bioship.ca
"@ | Set-Content -Path (Join-Path $bundle "READ ME FIRST.txt") -Encoding ASCII
} else {
@"
An Ounce of Prevention
======================
1. Double-click  "Start An Ounce of Prevention.bat".
2. Your web browser opens the program. Nothing is sent over the internet.
3. To stop: close the black window.

Your data is stored in the file OunceOfPrevention.db in this folder.
Keep a copy of it somewhere safe, or use the Back Up button inside the program.
To move to a new computer, copy this whole folder.

Sample CSV files: example spreadsheets you can open in Excel, copy and fill in.
Support: see the Manual.   (c) BioShip Inc.
"@ | Set-Content -Path (Join-Path $bundle "READ ME FIRST.txt") -Encoding ASCII
}

if ($PublicKey) {
    Write-Host "6/7  Stamp the public key (no private key needed)"
    if ($PublicKey -notmatch '^[0-9a-fA-F]{64}$') { throw "PublicKey must be 64 hex characters." }
    $appPath = Join-Path $bundle "app.py"
    $txt = [System.IO.File]::ReadAllText($appPath)
    if ($txt -notmatch 'LICENSE_PUBLIC_KEY_HEX = ""') { throw "app.py has no empty LICENSE_PUBLIC_KEY_HEX to fill." }
    $txt = $txt -replace 'LICENSE_PUBLIC_KEY_HEX = ""', ('LICENSE_PUBLIC_KEY_HEX = "' + $PublicKey.ToLower() + '"')
    [System.IO.File]::WriteAllText($appPath, $txt, (New-Object System.Text.UTF8Encoding($false)))
    if (([System.IO.File]::ReadAllText($appPath)) -notmatch $PublicKey.ToLower()) { throw "Stamping failed." }
} elseif ($Stamp) {
    Write-Host "6/7  Stamp public key into the bundle's app.py"
    if (-not (Test-Path (Join-Path $src "license_private.key"))) { throw "license_private.key not found in $src" }
    python (Join-Path $src "make_license.py") stamp --app (Join-Path $bundle "app.py")
    if ($LASTEXITCODE -ne 0) { throw "stamp failed" }
} else {
    Write-Host "6/7  SKIPPED stamping. This is a TEST bundle, not for customers."
}

Write-Host "7/7  Safety check: no vendor-only files in the bundle"
$banned = @("make_license.py", "license_private.key", "licenses_issued.csv", "private_groups.py", "build_bundle.ps1", "OunceOfPrevention.db", "ounce_config.json", "license.txt")
$found = Get-ChildItem $bundle -Recurse -File | Where-Object { ($banned -ccontains $_.Name) -and ($_.FullName -notlike "*\python\*") }
if ($found) { $found | ForEach-Object { Write-Host "  FOUND: $($_.FullName)" }; throw "Vendor-only file in bundle. Stopping." }
$inc = Get-ChildItem $bundle -Recurse -Directory -Filter incident_files
if ($inc) { throw "An incident_files folder (customer data) is in the bundle. Stopping." }
$apf = Get-ChildItem $bundle -Recurse -Directory -Filter asset_photos
if ($apf) { throw "An asset_photos folder (customer data) is in the bundle. Stopping." }
$flac = Get-ChildItem $bundle -Recurse -File -Filter *.flac
if ($flac) { throw "Audio files found in bundle. Stopping." }

if ($Demo) {
    $appTxt = [System.IO.File]::ReadAllText((Join-Path $bundle "app.py"))
    if ($appTxt -notmatch 'DEMO_BUILD = True') { throw "This app.py is not the demo (DEMO_BUILD = True missing). Stopping." }
    if ($appTxt -match 'LICENSE_PUBLIC_KEY_HEX = ""') { throw "Demo has no public key, so license codes could not unlock it. Stopping." }
    $zip = Join-Path $Out "An-Ounce-of-Prevention-Demo.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($bundle, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    Write-Host "Demo zip: $zip  ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
}

Write-Host ""
Write-Host "Done. Bundle folder: $bundle"
$mb = [math]::Round(((Get-ChildItem $bundle -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB)
Write-Host "Size: about $mb MB"
Write-Host "Test it: double-click 'Start An Ounce of Prevention.bat' inside that folder."
