param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$site = 'https://vanya-id.github.io/aion2-helper/'
$overlay = Join-Path $dir 'overlay.pyw'
$icon = Join-Path $dir 'overlay.ico'

function Find-Python {
  $found = @(Get-Command pythonw.exe, pyw.exe -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*\WindowsApps\*' } | ForEach-Object Source)
  $found += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe", "$env:ProgramFiles\Python3*\pythonw.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object FullName)
  $found | Select-Object -First 1
}

$python = Find-Python
if (-not $python) {
  Write-Host 'Не найден Python. Установи Python 3 с https://www.python.org/downloads/ и снова запусти install.cmd.'
  exit 1
}

Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($overlay) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$shell = New-Object -ComObject WScript.Shell
$tmp = Join-Path $env:TEMP 'aion2-helper.lnk'
$lnk = $shell.CreateShortcut($tmp)
$lnk.TargetPath = $python
$lnk.Arguments = "`"$overlay`""
$lnk.WorkingDirectory = $dir
$lnk.IconLocation = "$icon,0"
$lnk.Save()
Move-Item -LiteralPath $tmp -Destination (Join-Path ([Environment]::GetFolderPath('Startup')) 'Aion 2 плашка.lnk') -Force

$url = "[InternetShortcut]`r`nURL=$site`r`nIconFile=$icon`r`nIconIndex=0`r`n"
Set-Content -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Aion 2 трекер.url') -Value $url -Encoding Unicode

Start-Process -FilePath $python -ArgumentList "`"$overlay`"" -WorkingDirectory $dir
if (-not $Quiet) { Start-Process $site }
Write-Host 'Готово: плашка запущена и будет стартовать вместе с Windows, на рабочем столе ярлык «Aion 2 трекер».'
