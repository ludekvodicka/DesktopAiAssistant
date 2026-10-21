param([string]$DistPath = 'dist', [string]$WorkPath = 'build')

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot
Push-Location $projectRoot
try {
    $distRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DistPath))
    $workRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $WorkPath))
    $appFolder = Join-Path $distRoot 'DesktopAiAssistant'
    $extensionTarget = Join-Path $appFolder 'browser-extension'
    $installedManifest = Join-Path $extensionTarget 'manifest.json'
    $previousExtensionManifest = if (Test-Path -LiteralPath $installedManifest) { Get-Content -LiteralPath $installedManifest -Raw } else { $null }
    # QML is added as one folder: --collect-data would also pick up the SVN metadata of the mounted shared code
    $qml = Join-Path $projectRoot 'src/desktop_ai_assistant/qml'
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --windowed --name DesktopAiAssistant --paths src --add-data "$qml;desktop_ai_assistant/qml" --collect-data certifi --hidden-import comtypes.gen.UIAutomationClient --distpath $distRoot --workpath $workRoot --specpath $workRoot packaging/gui_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --console --onefile --name DesktopAiHost --paths src --exclude-module PySide6 --distpath $appFolder --workpath (Join-Path $workRoot 'host') --specpath $workRoot packaging/host_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Native host build failed' }
    Push-Location browser-extension
    try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Extension build failed' } } finally { Pop-Location }
    if ($previousExtensionManifest) {
        New-Item -ItemType Directory -Path $extensionTarget -Force | Out-Null
        [System.IO.File]::WriteAllText($installedManifest, $previousExtensionManifest, [System.Text.UTF8Encoding]::new($false))
    }
    node browser-extension/deploy.mjs $extensionTarget
    if ($LASTEXITCODE -ne 0) { throw 'Extension deployment failed' }
    Copy-Item -LiteralPath README.md -Destination (Join-Path $appFolder 'README.md') -Force
    Copy-Item -LiteralPath LICENSE, CONTRIBUTING.md -Destination $appFolder -Force
    New-Item -ItemType Directory -Path (Join-Path $appFolder 'docs') -Force | Out-Null
    Copy-Item -LiteralPath docs/guide.md -Destination (Join-Path $appFolder 'docs') -Force
    Copy-Item -LiteralPath docs/images -Destination (Join-Path $appFolder 'docs') -Recurse -Force
    # Windows PowerShell 5.1 strips double quotes from native arguments, so Python only prints the version
    $version = & .venv/Scripts/python.exe -c 'from desktop_ai_assistant import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Version lookup failed' }
    $release = [ordered]@{ version = $version; builtAt = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText((Join-Path $appFolder 'release.json'), $release, [System.Text.UTF8Encoding]::new($false))
    if (Get-ChildItem -LiteralPath $appFolder -Recurse -Force -Directory -Filter .svn) { throw 'SVN metadata in the build' }
    Write-Host "Ready: $appFolder/DesktopAiAssistant.exe"
    Write-Host 'Release zip and Setup: .venv/Scripts/python.exe packaging/package_release.py'
} finally { Pop-Location }
