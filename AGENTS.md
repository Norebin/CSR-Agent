# AGENTS.md

## Project overview

Build a **research-oriented, pluggable multi-agent code smell refactoring system** for Java projects.
Target actionable smells:

- Long Method
- Complex Method
- Long Parameter List
- Feature Envy

The system takes one smell instance plus repository context as input, then outputs the best validated refactoring patch, evidence, logs, and evaluation records.

## Primary objective

Implement a Python-first orchestration system that can:

1. load smell datasets and project repositories,
2. retrieve relevant historical refactoring cases,
3. orchestrate multiple specialized agents,
4. generate and validate refactoring patches,
5. compute research metrics for RQ1–RQ4.

## Hard constraints

- Keep every module **replaceable** for ablation.
- Do not hardcode local Windows paths. All paths must come from config.
- Prefer **structured outputs** (JSON/YAML/dataclasses) over free-form text.
- Every agent must have:
  - explicit input schema,
  - explicit output schema,
  - tool allowlist,
  - stop condition,
  - failure mode.
- Validation must use tools whenever possible (compile, AST diff, smell detection, tests).
- The review loop must be bounded (`max_review_loops`, default 3).
- Missing GraphML or partial version tags must not crash the pipeline. Use fallbacks.

## Research expectations

The implementation must support:

- RQ1: overall comparison against baseline methods
- RQ2: RAG ablation
- RQ3: multi-agent ablation
- RQ4: efficiency / cost analysis

## Required architecture layers

1. Dataset & repository layer
2. Case knowledge base (RCKB)
3. Retrieval & evidence layer
4. Agent orchestration layer
5. Tool adapter layer
6. Validation & review layer
7. Evaluation layer
8. Experiment runner layer

## Required modules

### 1) Dataset ingestion
Responsibilities:
- load CSV rows into normalized records,
- resolve repository path,
- resolve version tags,
- prepare task objects.

### 2) Version and entity resolution
Responsibilities:
- match incomplete dataset version strings to git tags,
- checkout begin/disappear revisions,
- locate target class/method/entity,
- map entity across refactor/move/rename when possible.

### 3) RCKB builder
Responsibilities:
- convert train split examples into structured cases,
- build semantic / structural / refactoring-prior indices,
- support missing-feature fallback.

### 4) Retriever
Responsibilities:
- coarse retrieval,
- context gating,
- reranking,
- evidence packing.

### 5) Orchestrator
Responsibilities:
- create task graph,
- choose expert sequence,
- aggregate outputs,
- trigger review loops,
- keep episode memory.

### 6) Expert agents
Must include:
- method_refactorer
- move_refactorer
- class_harmonizer
- reviewer_verifier

Optional but recommended:
- patch_integrator
- retrieval_analyst

### 7) Tool adapters
Provide unified interfaces for:
- git
- code parsing / AST
- repository search
- build / compile
- targeted test execution
- smell detection
- diff / patch apply
- vector retrieval

### 8) Metrics and experiment runner
Responsibilities:
- compute SRR / SIR / CSR / assertion pass rate / token cost / time cost / CodeBLEU,
- run ablations from config,
- persist reproducible artifacts.

## Coding preferences

- Python 3.11+
- Use `pydantic` or dataclasses for schemas
- Use `pathlib`, not string concatenation for paths
- Use dependency injection for tools and model backends
- Keep experiment configuration in YAML
- Use clear logs and event IDs per smell instance (`unique_id`)
- Prefer small interfaces and pure functions in utility layers

## Output artifacts per task

Every smell task should produce:

- `task_input.json`
- `retrieval_evidence.json`
- `plan.json`
- `candidate_patch.diff`
- `review_feedback.json`
- `final_result.json`
- `metrics.json`
- execution logs

## Definition of done

A module is only complete when:

1. its interface matches the machine-readable config files,
2. it has at least one integration test,
3. it logs structured events,
4. it is selectable by experiment config,
5. it fails gracefully on missing context.

## Important implementation warnings

- `code_after_refactor` in the dataset may be noisy. Do not treat it as ground truth without validation.
- When entity mapping is uncertain, preserve uncertainty in metadata.
- Do not infer behavioral equivalence from compile success alone.
- When no relevant unit tests exist, generate lightweight regression assertions only as a fallback experiment mode.
