param(
    [string]$BasePath = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw "ASSERT FAILED: $Message"
    }
}

Write-Host "Validating PharmaCRM query-router context pack..." -ForegroundColor Cyan

$schemaPath = Join-Path $BasePath "sp_profile_schema.json"
$profilesPath = Join-Path $BasePath "pharmacrm_sp_profiles.json"
$markdownPath = Join-Path $BasePath "pharmacrm_sp_profiles.md"
$testsPath = Join-Path $BasePath "routing_test_suite.json"
$samplesPath = Join-Path $BasePath "execution_samples"

Assert-True (Test-Path -LiteralPath $schemaPath) "Schema file missing: $schemaPath"
Assert-True (Test-Path -LiteralPath $profilesPath) "Profiles file missing: $profilesPath"
Assert-True (Test-Path -LiteralPath $markdownPath) "Markdown file missing: $markdownPath"
Assert-True (Test-Path -LiteralPath $testsPath) "Test suite file missing: $testsPath"
Assert-True (Test-Path -LiteralPath $samplesPath) "Execution samples folder missing: $samplesPath"

$schema = Get-Content -LiteralPath $schemaPath -Raw | ConvertFrom-Json
$profilesDoc = Get-Content -LiteralPath $profilesPath -Raw | ConvertFrom-Json
$testsDoc = Get-Content -LiteralPath $testsPath -Raw | ConvertFrom-Json
$mdText = Get-Content -LiteralPath $markdownPath -Raw

$requiredFields = @(
    "sp_name",
    "purpose",
    "input_intent",
    "output_grain",
    "result_sets",
    "filters_supported",
    "date_logic",
    "supports_targets",
    "supports_incentive",
    "supports_entity_breakdown",
    "performance_risk",
    "anti_patterns",
    "routing_rules",
    "example_prompts_positive",
    "example_prompts_negative",
    "clarification_questions"
)

Assert-True ($profilesDoc.profiles.Count -eq 3) "Expected exactly 3 profiles."
Assert-True ($null -ne $profilesDoc.metadata.live_execution_evidence) "Live execution evidence is missing from metadata."
Assert-True ($profilesDoc.metadata.live_execution_evidence.executed_after_user_approval -eq $true) "Live execution evidence must show explicit user-approved execution."
Assert-True ($profilesDoc.metadata.live_execution_evidence.execution_scope -like "*narrow*") "Live execution scope must document narrow sample parameters."

foreach ($profile in $profilesDoc.profiles) {
    foreach ($field in $requiredFields) {
        $hasProp = $null -ne $profile.PSObject.Properties[$field]
        Assert-True $hasProp "Profile '$($profile.sp_name)' is missing required field '$field'."
    }
}

$profileNames = $profilesDoc.profiles | ForEach-Object { $_.sp_name }
foreach ($name in $profileNames) {
    Assert-True ($mdText -like "*$name*") "Markdown file does not mention profile name '$name'."
}

Assert-True ($mdText -like "*Router Decision Policy*") "Markdown does not include router policy section."
Assert-True ($testsDoc.routing_accuracy_tests.Count -ge 30) "Routing accuracy tests must be at least 30."
Assert-True ($testsDoc.stored_procedures_were_executed_on_live -eq $true) "Test suite must show live SP execution happened after approval."
Assert-True ($testsDoc.ambiguity_tests.Count -ge 1) "Ambiguity tests missing."
Assert-True ($testsDoc.boundary_safety_tests.Count -ge 1) "Boundary safety tests missing."
Assert-True ($testsDoc.output_contract_tests.Count -ge 1) "Output contract tests missing."
Assert-True ($testsDoc.regression_tests.Count -ge 1) "Regression tests missing."

$schemaRequired = @("metadata", "router_policy", "profiles")
foreach ($topField in $schemaRequired) {
    Assert-True ($schema.required -contains $topField) "Schema required list missing '$topField'."
}

$expectedOutputFiles = @(
    "01_SS_sp_CustomerSales_YTD_Excel_output.txt",
    "02_Sp_PharmaCRM_SVT_output.txt",
    "03_Sp_PharmaCRM_GetIncentiveProcessReport_output.txt"
)
$expectedErrorFiles = @(
    "01_SS_sp_CustomerSales_YTD_Excel_error.txt",
    "02_Sp_PharmaCRM_SVT_error.txt",
    "03_Sp_PharmaCRM_GetIncentiveProcessReport_error.txt"
)

foreach ($fileName in $expectedOutputFiles) {
    $filePath = Join-Path $samplesPath $fileName
    Assert-True (Test-Path -LiteralPath $filePath) "Expected live execution output file missing: $fileName"
    Assert-True ((Get-Item -LiteralPath $filePath).Length -gt 0) "Expected live execution output file is empty: $fileName"
}

foreach ($fileName in $expectedErrorFiles) {
    $filePath = Join-Path $samplesPath $fileName
    Assert-True (Test-Path -LiteralPath $filePath) "Expected live execution error file missing: $fileName"
    Assert-True ((Get-Item -LiteralPath $filePath).Length -eq 0) "Live execution error file is not empty: $fileName"
}

Write-Host "Validation passed." -ForegroundColor Green
Write-Host ("Profiles: {0}" -f $profilesDoc.profiles.Count)
Write-Host ("Routing accuracy tests: {0}" -f $testsDoc.routing_accuracy_tests.Count)
Write-Host ("Ambiguity tests: {0}" -f $testsDoc.ambiguity_tests.Count)
Write-Host ("Boundary safety tests: {0}" -f $testsDoc.boundary_safety_tests.Count)
Write-Host ("Live execution evidence: {0}" -f $profilesDoc.metadata.live_execution_evidence.executed_after_user_approval)
