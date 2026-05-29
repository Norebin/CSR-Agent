param(
    [string]$EnvPrefix = ".conda\envs\csr-agent"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $EnvPrefix)) {
    conda --no-plugins create --solver=classic -p $EnvPrefix python=3.11 -y
}

conda run -p $EnvPrefix python -m pip install -r requirements.txt
Write-Output "Environment ready at $EnvPrefix"
