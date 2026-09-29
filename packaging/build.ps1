$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot
Push-Location $projectRoot
try {
    $extensionTarget = Join-Path $projectRoot 'dist/DesktopAiAssistant/browser-extension'
    $installedManifest = Join-Path $extensionTarget 'manifest.json'
    $previousExtensionManifest = if (Test-Path -LiteralPath $installedManifest) { Get-Content -LiteralPath $installedManifest -Raw } else { $null }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --windowed --name DesktopAiAssistant --paths src --collect-data desktop_ai_assistant --hidden-import comtypes.gen.UIAutomationClient --distpath dist --workpath build --specpath build packaging/gui_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --console --onefile --name DesktopAiHost --paths src --exclude-module PySide6 --distpath dist/DesktopAiAssistant --workpath build/host --specpath build packaging/host_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Native host build failed' }
    Push-Location browser-extension
    try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Extension build failed' } } finally { Pop-Location }
    if ($previousExtensionManifest) {
        New-Item -ItemType Directory -Path $extensionTarget -Force | Out-Null
        [System.IO.File]::WriteAllText($installedManifest, $previousExtensionManifest, [System.Text.UTF8Encoding]::new($false))
    }
    node browser-extension/deploy.mjs dist/DesktopAiAssistant/browser-extension
    if ($LASTEXITCODE -ne 0) { throw 'Extension deployment failed' }
    Copy-Item -LiteralPath README.md -Destination dist/DesktopAiAssistant/README.md -Force
    Copy-Item -LiteralPath LICENSE, CONTRIBUTING.md -Destination dist/DesktopAiAssistant -Force
    New-Item -ItemType Directory -Path dist/DesktopAiAssistant/docs -Force | Out-Null
    Copy-Item -LiteralPath docs/guide.md -Destination dist/DesktopAiAssistant/docs -Force
    Copy-Item -LiteralPath docs/images -Destination dist/DesktopAiAssistant/docs -Recurse -Force
    & .venv/Scripts/python.exe -c 'import json,datetime,pathlib; from desktop_ai_assistant import __version__; pathlib.Path("dist/DesktopAiAssistant/release.json").write_text(json.dumps({"version":__version__,"builtAt":datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding="utf-8")'
    Write-Host 'Ready: dist/DesktopAiAssistant/DesktopAiAssistant.exe'
} finally { Pop-Location }
