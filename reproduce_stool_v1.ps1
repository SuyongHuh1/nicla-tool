param(
    [string]$RunName = ("stool_public_v1_{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")),
    [int]$Epochs = 30,
    [string]$PythonPath = "",
    [switch]$RunCrossValidation
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$python = if ($PythonPath) {
    (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    Join-Path $projectRoot ".venv\Scripts\python.exe"
}
$datasetRoot = Join-Path $projectRoot "datasets\stool_public\v1"
$trainingSession = Join-Path $datasetRoot "train"
$evaluationSession = Join-Path $datasetRoot "evaluation\inference_e01"
$runRoot = Join-Path $projectRoot ("training_runs\{0}" -f $RunName)

if (-not (Test-Path -LiteralPath $python)) {
    throw "Run setup_windows.ps1 and install laptop\requirements-training.txt first."
}
if (-not (Test-Path -LiteralPath (Join-Path $trainingSession "metadata.jsonl"))) {
    throw "Public training dataset is missing: $trainingSession"
}
if (Test-Path -LiteralPath $runRoot) {
    throw "Run output already exists; choose another -RunName: $runRoot"
}

Write-Host "Verifying dataset checksums..." -ForegroundColor Cyan
$checksumFile = Join-Path $datasetRoot "checksums.sha256"
foreach ($line in Get-Content -LiteralPath $checksumFile) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '  ', 2
    if ($parts.Count -ne 2) { throw "Invalid checksum row: $line" }
    $path = Join-Path $datasetRoot ($parts[1] -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Dataset file missing: $path"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0].ToLowerInvariant()) {
        throw "Checksum mismatch: $path"
    }
}

New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

if ($RunCrossValidation) {
    $cvRoot = Join-Path $runRoot "cross_validation"
    foreach ($augmentation in @("none", "mild", "default")) {
        & (Join-Path $projectRoot "cross_validate_fomo.ps1") `
            -SessionDir $trainingSession `
            -OutputDir $cvRoot `
            -RunName $augmentation `
            -GroupField "shape_id" `
            -Classes "background,stool" `
            -MetricClass "stool" `
            -Architecture "tiny" `
            -Epochs $Epochs `
            -Augmentation $augmentation
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & $python "laptop\compare_augmentation_cv.py" $cvRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$finalRoot = Join-Path $runRoot "final_default"
& $python "laptop\prepare_stool_fomo.py" $trainingSession `
    --output $finalRoot `
    --source labels `
    --group-field shape_id `
    --classes background,stool
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python "laptop\train_stool_fomo.py" (Join-Path $finalRoot "manifest.jsonl") `
    --architecture tiny `
    --classes background,stool `
    --metric-class stool `
    --output $finalRoot `
    --model-out (Join-Path $finalRoot "model.tflite") `
    --labels-out (Join-Path $finalRoot "labels.txt") `
    --epochs $Epochs `
    --augmentation default
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$validationRoot = Join-Path $finalRoot "validation"
& $python "laptop\validate_stool_fomo.py" (Join-Path $finalRoot "manifest.jsonl") `
    --model (Join-Path $finalRoot "model.tflite") `
    --output $validationRoot `
    --class-id 1 `
    --class-name stool
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$validation = Get-Content -LiteralPath (Join-Path $validationRoot "validation_report.json") `
    -Raw | ConvertFrom-Json
$threshold = [double]$validation.selected_threshold
$inferenceRoot = Join-Path $finalRoot "independent_inference"
& $python "laptop\evaluate_fomo_tflite.py" $evaluationSession `
    --model (Join-Path $finalRoot "model.tflite") `
    --output $inferenceRoot `
    --threshold $threshold `
    --roi-width 112 `
    --roi-height 112 `
    --class-id 1 `
    --class-name stool
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python "laptop\evaluate_inference_gt.py" $evaluationSession `
    (Join-Path $inferenceRoot "inference_report.json") `
    --output $inferenceRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Reproduction completed." -ForegroundColor Green
Write-Host "Run: $runRoot"
Write-Host "Model: $(Join-Path $finalRoot 'model.tflite')"
Write-Host "Validation: $(Join-Path $validationRoot 'summary.md')"
Write-Host "Independent evaluation: $(Join-Path $inferenceRoot 'summary.md')"
