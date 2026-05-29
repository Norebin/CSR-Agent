# CSR-Agent

Research-oriented, pluggable multi-agent code smell refactoring system for Java projects.

## Implemented architecture

- Dataset & repository layer (`src/csr_agent/dataset`, `src/csr_agent/resolver`)
- Case knowledge base + retrieval (`src/csr_agent/kb`, `src/csr_agent/retrieval`)
- Agent orchestration with bounded review loop (`src/csr_agent/orchestration`)
- Tool adapter layer (`src/csr_agent/tools`)
- Validation/review layer (`src/csr_agent/validation`, `src/csr_agent/agents/reviewer_verifier.py`)
- Evaluation + experiment runner (`src/csr_agent/evaluation`, `src/csr_agent/runner`)
- Structured artifacts and logs (`src/csr_agent/artifacts`, `src/csr_agent/logging.py`)

## Environment setup

Conda environment file is included:

```bash
conda env create -f environment.yml
conda activate csr-agent
```

Or use the local prefix environment already created in this workspace:

```bash
conda activate D:\AsmellRefactor\CSR-Agent\.conda\envs\csr-agent
```

## Run tests

```bash
python -m pytest -q -p no:cacheprovider
```

## CLI usage

Run one experiment from dataset CSV:

```bash
csr-agent run-experiment \
  --config configs/pipeline_config.local.yaml \
  --contracts configs/agent_contracts.yaml \
  --dataset-csv <path/to/dataset.csv>
```

Run one task from JSON:

```bash
csr-agent run-task \
  --config configs/pipeline_config.template.yaml \
  --task-json <path/to/task_input.json>
```

Run full RQ1-RQ4 suite (all configured methods/ablations):

```bash
csr-agent run-rq-suite \
  --config configs/pipeline_config.local.yaml \
  --contracts configs/agent_contracts.yaml \
  --matrix configs/rq_suite.local.yaml \
  --dataset-dir D:/AsmellRefactor/MyCode/ACSmellData \
  --suite-id rq_suite_full
```

Key suite artifacts are written under:

- `outputs/experiments/<suite-id>/rq_all_task_metrics.csv`
- `outputs/experiments/<suite-id>/rq_by_method_smell.csv`
- `outputs/experiments/<suite-id>/rq_by_method.csv`
- `outputs/experiments/<suite-id>/rq_method_level_assertion.csv`
- `outputs/experiments/<suite-id>/rq4_loop_tradeoff.csv`

## Key guarantees

- Config-driven ablation switches (`pipeline_config.template.yaml`)
- Strongly typed structured I/O with Pydantic models
- Explicit agent/tool contracts and runtime validation
- Graceful fallback for missing graph context and uncertain entity/version resolution
- Bounded review loop (`max_review_loops`, default 3)
- LLM API is optional per config; retrieval and tool adapters remain local
- Runtime per-task loop performs static checks only (patch/parse/compile)
- PMD/smell redetect and optional tests run at experiment-level post-validation

## Local experiment paths (already prepared)

`configs/pipeline_config.local.yaml` is preconfigured for:

- Smell CSVs: `D:/AsmellRefactor/MyCode/ACSmellData`
- Git repos: `D:/AsmellRefactor/GitClone`
- Graph context: `D:/AsmellRefactor/graph_data`
- Outputs: `D:/AsmellRefactor/CSR-Agent/outputs`

## Real tool adapters

The tool layer now executes real commands where available:

- `git_tool`: `git` tags/show/diff/checkout verification
- `build_tool`: Maven/Gradle compile
- `test_tool`: targeted test execution (Maven/Gradle)
- `repo_browser_tool`: real file read/search
- `smell_detector_tool`: optional external detector commands

To enable PMD/Designite detection, set `tool_runtime.pmd_command` and/or
`tool_runtime.designite_command` in `configs/pipeline_config.local.yaml`.

Validation behavior:

- Per-task runtime stage: static checks only.
- Post-experiment stage: target-smell redetect (PMD/Designite) and optional tests.
- `validation.targeted_tests` defaults to `false` (unit tests disabled by default).

## Graph Data (Zip) Resolution

The pipeline now resolves graph context from zip bundles under `project.graph_root`:

- Expected folder: `<graph_root>/<project>/`
- Expected zip naming: `<project>-<version>.zip` (fuzzy matched by version hints)
- Expected member naming: `<project>-<task_id>.graphml` (or `<task_id>.graphml`)

Resolved graph files are extracted to:

- `<output_root>/.graph_cache/<project>/<zip_stem>/<graphml_name>`

## LLM API setup

The agents now support OpenAI-compatible API inference:

1. Enable `llm_api.enabled: true` in your config.
2. Configure `llm_api.base_url` and model names under `models.*_model`.
3. Set key via environment variable:

```powershell
$env:OPENAI_API_KEY="your_api_key"
```

By design, retrieval (`RCKB + FAISS`) and tool execution (`git/build/test/smell detectors`)
continue to run locally.

## Quick run (single project)

```powershell
.\scripts\run_project_experiment.ps1 -Project jsoup
.\scripts\run_project_experiment.ps1 -Project jsoup -Profile rq2_no_rag
```

The script auto-creates `D:/AsmellRefactor/CSR-Agent/.m2/settings.xml`
and local Maven repository for permission-safe dependency caching.

Run full RQ suite helper script:

```powershell
.\scripts\run_rq_suite.ps1 -SuiteId rq_suite_full
.\scripts\run_rq_suite.ps1 -SuiteId rq_suite_full -DatasetDir D:\AsmellRefactor\MyCode\ACSmellData
```
