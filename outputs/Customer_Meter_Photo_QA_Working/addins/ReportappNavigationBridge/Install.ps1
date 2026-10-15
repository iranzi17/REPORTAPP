param([string]$Python = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe')
$ErrorActionPreference = 'Stop'
$pro = 'C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe'
if (-not (Test-Path -LiteralPath $pro)) { throw 'ArcGIS Pro installation not found.' }
if ((Get-Item -LiteralPath $pro).VersionInfo.ProductVersion -notmatch '^3\.4\.') {
    throw 'This package targets ArcGIS Pro 3.4. Verify the installed version.'
}
if (Get-Process ArcGISPro -ErrorAction SilentlyContinue) { throw 'Save your project and close ArcGIS Pro before installing.' }
$package = Join-Path $PSScriptRoot 'bin/Release/net8.0-windows/ReportappNavigationBridge.esriAddInX'
if (-not (Test-Path -LiteralPath $package)) { throw 'Run Build.ps1 first.' }
# Interactive installer requested by this installation script.
Start-Process -FilePath $package -Wait
Write-Host 'Verify success in the Esri installer. Then register the click handler with:'
$handler = Join-Path $PSScriptRoot '../../src/meter_photo_qa/alert_navigation.py'
Write-Host ('& "' + $Python + '" "' + (Resolve-Path -LiteralPath $handler).Path + '" --register')
Write-Host 'Restart Pro and verify REPORTAPP in Project > Add-In Manager before testing.'
