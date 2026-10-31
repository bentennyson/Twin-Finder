param([string]$Python = 'python', [string]$DistPath = 'dist', [string]$WorkPath = 'build', [switch]$DebugConsole)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath 'models\base_classifier.json')) { throw 'Run research/evaluate.py first.' }
if (-not (Test-Path -LiteralPath 'models\encoder.pt')) { throw 'Run research/prepare_encoder.py first.' }
$ModelData = (Join-Path $PSScriptRoot 'models') + ';models'
$WindowMode = if ($DebugConsole) { '--console' } else { '--windowed' }
& $Python -m PyInstaller --noconfirm --clean --onedir $WindowMode --name TwinFinder --distpath $DistPath --workpath $WorkPath --specpath $WorkPath --add-data $ModelData --collect-all tokenizers --exclude-module sentence_transformers --exclude-module transformers --exclude-module sklearn --exclude-module scipy --exclude-module pandas --exclude-module matplotlib --exclude-module streamlit --exclude-module pytest --exclude-module torchvision --exclude-module torchaudio --exclude-module IPython --exclude-module notebook desktop.py
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
Write-Host "Built $DistPath\TwinFinder\TwinFinder.exe. Distribute the entire TwinFinder folder."
