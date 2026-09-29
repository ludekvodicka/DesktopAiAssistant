param([string]$Source = (Join-Path $PSScriptRoot '../dist/DesktopAiAssistant'))
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'DesktopAiAssistant.exe'))) { throw 'Build the package first.' }
$destination = Join-Path $env:LOCALAPPDATA 'Programs/DesktopAiAssistant'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -Path (Join-Path $sourceRoot '*') -Destination $destination -Recurse -Force
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Desktop AI Assistant.lnk'))
$shortcut.TargetPath = Join-Path $destination 'DesktopAiAssistant.exe'
$shortcut.WorkingDirectory = $destination
$shortcut.Save()
Write-Host "Installed: $destination/DesktopAiAssistant.exe"
Write-Host 'Re-register the extension from the installed app if you registered the portable build before.'
