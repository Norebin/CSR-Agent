param(
    [string]$SuiteId = "",
    [string]$DatasetDir = "",
    [string]$PythonExe = "python",
    [string]$Config = "configs/pipeline_config.local.yaml",
    [string]$Matrix = "configs/rq_suite.local.yaml",
    [string]$Contracts = "configs/agent_contracts.yaml"
)

$ErrorActionPreference = "Stop"

if (!(Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python executable not found in PATH: $PythonExe"
}
if (-not [string]::IsNullOrWhiteSpace($DatasetDir) -and !(Test-Path $DatasetDir)) {
    throw "Dataset directory not found: $DatasetDir"
}

if ([string]::IsNullOrWhiteSpace($SuiteId)) {
    $SuiteId = "rq_suite_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}

$env:PYTHONPATH = "src"
if ([string]::IsNullOrWhiteSpace($DatasetDir)) {
    & $PythonExe -m csr_agent run-rq-suite `
        --config $Config `
        --contracts $Contracts `
        --matrix $Matrix `
        --suite-id $SuiteId
}
else {
    & $PythonExe -m csr_agent run-rq-suite `
        --config $Config `
        --contracts $Contracts `
        --matrix $Matrix `
        --dataset-dir $DatasetDir `
        --suite-id $SuiteId
}
