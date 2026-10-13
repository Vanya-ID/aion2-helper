$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = $PSScriptRoot
$zip = Join-Path $env:TEMP 'aion2-helper.zip'
$tmp = Join-Path $env:TEMP 'aion2-helper-update'

Write-Host 'Скачиваю свежую версию с GitHub...'
Invoke-WebRequest 'https://github.com/Vanya-ID/aion2-helper/archive/refs/heads/main.zip' -OutFile $zip -UseBasicParsing
if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $tmp

$overlay = Join-Path $dir 'overlay.pyw'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($overlay) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

robocopy (Join-Path $tmp 'aion2-helper-main') $dir /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Не удалось скопировать файлы (robocopy $LASTEXITCODE)" }
Remove-Item -LiteralPath $zip, $tmp -Recurse -Force

& (Join-Path $dir 'install.ps1') -Quiet
Write-Host 'Обновлено.'
