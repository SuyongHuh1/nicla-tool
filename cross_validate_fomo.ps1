param(
    [Parameter(Mandatory = $true)]
    [string]$SessionDir,
    [string]$OutputDir = "training_runs\fomo_group_cv",
    [string]$RunName = ("run_{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$GroupField = "shape_id",
    [string]$Classes = "background,stool",
    [string]$MetricClass = "stool",
    [ValidateSet("tiny", "mobilenetv2_035")]
    [string]$Architecture = "tiny",
    [string]$LabelSource = "labels",
    [string]$RoiSizes = "96,112,128,144,160,176,192,208,224",
    [int]$Epochs = 30,
    [double]$PositiveWeight = 80.0,
    [ValidateSet("none", "mild", "default")]
    [string]$Augmentation = "default",
    [string]$AugmentationConfig = "",
    [switch]$AllowPending,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Run setup_windows.ps1 first."
}
$metadata = Join-Path $SessionDir "metadata.jsonl"
if (-not (Test-Path -LiteralPath $metadata)) {
    throw "Session metadata not found: $metadata"
}
$classNames = @($Classes.Split(",") | ForEach-Object { $_.Trim() } |
    Where-Object { $_ })
if ($classNames.Count -lt 2 -or $classNames[0] -ne "background") {
    throw "Classes must start with background and include an object class."
}
$metricClassId = [Array]::IndexOf($classNames, $MetricClass)
if ($metricClassId -le 0) {
    throw "MetricClass must be one of the configured object classes."
}

$records = Get-Content -LiteralPath $metadata | ForEach-Object { $_ | ConvertFrom-Json }
$groups = @($records |
    Where-Object { [int]$_.expected_instances -gt 0 } |
    ForEach-Object { $_.PSObject.Properties[$GroupField].Value } |
    Where-Object { $_ -and $_ -notin @("none", "baseline") } |
    Select-Object -Unique | Sort-Object)
if ($groups.Count -lt 3) {
    throw "At least three physical groups are required for grouped cross-validation."
}

$runDir = Join-Path $OutputDir $RunName
if ($PlanOnly) {
    $foldPlan = for ($index = 0; $index -lt $groups.Count; $index++) {
        [pscustomobject]@{
            TestGroup = [string]$groups[$index]
            ValidationGroup = [string]$groups[($index + 1) % $groups.Count]
            TrainGroups = @($groups | Where-Object {
                $_ -ne $groups[$index] -and $_ -ne $groups[($index + 1) % $groups.Count]
            })
        }
    }
    [pscustomobject]@{
        SessionDir = $SessionDir
        RunDir = $runDir
        GroupField = $GroupField
        Classes = $classNames
        MetricClass = $MetricClass
        Architecture = $Architecture
        Augmentation = $Augmentation
        AugmentationConfig = $AugmentationConfig
        RoiSizes = $RoiSizes
        Folds = $foldPlan
    } | ConvertTo-Json -Depth 6
    exit 0
}
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
for ($index = 0; $index -lt $groups.Count; $index++) {
    $testGroup = [string]$groups[$index]
    $validationGroup = [string]$groups[($index + 1) % $groups.Count]
    $safeGroup = $testGroup -replace '[^A-Za-z0-9_.-]', '_'
    $fold = Join-Path $runDir ("fold_test_{0}" -f $safeGroup)
    $prepareArgs = @(
        "laptop\prepare_stool_fomo.py", $SessionDir,
        "--output", $fold,
        "--source", $LabelSource,
        "--group-field", $GroupField,
        "--classes", ($classNames -join ","),
        "--validation-group", $validationGroup,
        "--test-group", $testGroup
    )
    if ($AllowPending) { $prepareArgs += "--allow-pending" }
    Write-Host "Fold test=$testGroup validation=$validationGroup" -ForegroundColor Cyan
    & $python @prepareArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $trainArgs = @(
        "laptop\train_stool_fomo.py", "$fold\manifest.jsonl",
        "--architecture", $Architecture,
        "--classes", ($classNames -join ","),
        "--metric-class", $MetricClass,
        "--positive-weight", $PositiveWeight,
        "--output", $fold,
        "--model-out", "$fold\model.tflite",
        "--labels-out", "$fold\labels.txt",
        "--epochs", $Epochs,
        "--augmentation", $Augmentation
    )
    if ($AugmentationConfig) {
        $trainArgs += @("--augmentation-config", $AugmentationConfig)
    }
    & $python @trainArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $python "laptop\validate_stool_fomo.py" "$fold\manifest.jsonl" `
        --model "$fold\model.tflite" `
        --class-id $metricClassId `
        --class-name $MetricClass `
        --roi-sizes $RoiSizes `
        --output "$fold\validation"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $python "laptop\summarize_stool_cv.py" $runDir
exit $LASTEXITCODE
