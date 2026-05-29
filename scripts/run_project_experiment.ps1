param(
    [Parameter(Mandatory = $true)]
    [string]$Project,
    [string]$Profile = "",
    [string]$ExperimentId = ""
)

$ErrorActionPreference = "Stop"

$envPath = "D:\AsmellRefactor\CSR-Agent\.conda\envs\csr-agent\python"
$config = "configs/pipeline_config.local.yaml"
$contracts = "configs/agent_contracts.yaml"
$csvPath = "D:\AsmellRefactor\MyCode\ACSmellData\$Project.csv"
$m2Dir = "D:\AsmellRefactor\CSR-Agent\.m2"
$m2Repo = "$m2Dir\repository"
$m2Settings = "$m2Dir\settings.xml"

if (!(Test-Path $csvPath)) {
    throw "Dataset csv not found: $csvPath"
}

if (!(Test-Path $m2Repo)) {
    New-Item -ItemType Directory -Path $m2Repo -Force | Out-Null
}
if (!(Test-Path $m2Settings)) {
    @"
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <localRepository>D:/AsmellRefactor/CSR-Agent/.m2/repository</localRepository>
</settings>
"@ | Set-Content -LiteralPath $m2Settings -Encoding UTF8
}

if ([string]::IsNullOrWhiteSpace($ExperimentId)) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    if ([string]::IsNullOrWhiteSpace($Profile)) {
        $ExperimentId = "rq1_full_${Project}_$ts"
    }
    else {
        $ExperimentId = "${Profile}_${Project}_$ts"
    }
}

$args = @(
    "-m", "csr_agent", "run-experiment",
    "--config", $config,
    "--contracts", $contracts,
    "--dataset-csv", $csvPath,
    "--experiment-id", $ExperimentId
)

if (-not [string]::IsNullOrWhiteSpace($Profile)) {
    $args += @("--profile", $Profile)
}

$env:PYTHONPATH = "src"
& $envPath @args
