param([string]$LocalPackageSource = '')
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'ReportappNavigationBridge.csproj'
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the .NET 8 SDK or Visual Studio 2022 with .NET desktop development.'
}
$config = Join-Path ([IO.Path]::GetTempPath()) ('reportapp-' + [guid]::NewGuid() + '.config')
$extra = ''
if ($LocalPackageSource) {
    $resolved = (Resolve-Path -LiteralPath $LocalPackageSource).Path
    $extra = '<add key="local" value="' + [Security.SecurityElement]::Escape($resolved) + '"/>'
}
try {
    '<configuration><packageSources><clear/>' + $extra + '<add key="nuget" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>' | Set-Content -LiteralPath $config
    & dotnet restore $project --configfile $config
    if ($LASTEXITCODE -ne 0) { throw 'Restore failed.' }
    & dotnet build $project -c Release --no-restore
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    $package = Join-Path $PSScriptRoot 'bin/Release/net8.0-windows/ReportappNavigationBridge.esriAddInX'
    Get-Item -LiteralPath $package
    Get-FileHash -LiteralPath $package -Algorithm SHA256
} finally {
    if (Test-Path -LiteralPath $config) { Remove-Item -LiteralPath $config }
}
