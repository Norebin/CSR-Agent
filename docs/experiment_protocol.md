# 实验协议与评测设计（RQ1–RQ4）

## 1. 实验目标

本文件定义如何使用配置驱动方式评测 Multi-Agent 代码异味重构系统，并保证实验复现与消融可执行。

---

## 2. 数据划分与运行粒度

- 基本粒度：**单条异味实例（unique_id）**
- 训练集：用于构建 RCKB
- 测试集：用于离线重构评测
- 每次实验运行必须记录：
  - config snapshot
  - model backend
  - enabled agents
  - enabled tools
  - enabled memories
  - prompt strategy
  - timestamp
  - git commit hash of the framework

---

## 3. 输入 / 输出规范

## 3.1 单任务输入
- smell metadata
- resolved repository state
- code context
- retrieved evidence
- experiment switches

## 3.2 单任务输出
- final patch
- validation records
- smell re-detection records
- metrics
- execution trace

---

## 4. 核心指标

## 4.1 SRR
`SRR = (# tasks where target smell disappears) / (# evaluated tasks)`

建议同时按以下维度分层统计：
- smell type
- project
- baseline / method
- review loop count

## 4.2 CSR
`CSR = (# tasks that compile successfully) / (# evaluated tasks)`

若项目使用 Gradle/Maven，需要分别记录：
- parser pass
- module compile pass
- project compile pass

## 4.3 SIR
推荐同时输出两套结果：

### Binary-task SIR
`binary_SIR = (# tasks introducing at least one new smell) / (# evaluated tasks)`

### Count-normalized SIR
`count_SIR = (total # newly introduced smells) / (# evaluated tasks)`

## 4.4 Assertion/Test Pass Rate
仅对方法级异味统计：
- Long Method
- Complex Method
- Long Parameter List

分别记录：
- existing_related_test_pass_rate
- generated_assertion_pass_rate
- combined_behavioral_pass_rate

## 4.5 Cost Metrics
- mean input tokens / task
- mean output tokens / task
- mean total tokens / task
- mean wall-clock time / task
- mean tool time / task
- mean number of review loops / task

## 4.6 CodeBLEU
与 `best_match code_after_refactor` 比较，但必须附带 `mapping_confidence`。

---

## 5. RQ1：与基线总体效果比较

## 5.1 比较对象
按你的设定，基线包括：
- GPT-5.2
- Gemini-2.5-Pro
- Deepseek-V3.2

建议把“基线方法”统一封装成相同 runner 接口，只在：
- model backend
- prompt template
- tool availability
- review strategy

上做配置差异。

## 5.2 输出表格
建议最少输出以下表：

### Table A：总体结果
- Method
- SRR
- CSR
- binary SIR
- count SIR
- mean tokens
- mean time

### Table B：按 smell type 分层
- Method
- Smell Type
- SRR
- CSR
- SIR
- assertion pass rate

### Table C：按 project 分层
- Method
- Project
- SRR
- CSR
- SIR

---

## 6. RQ2：RAG 消融

## 6.1 推荐实验组
- no_rag
- semantic_only
- context_only
- semantic_plus_context
- semantic_plus_context_plus_refactor_prior

## 6.2 控制变量
以下保持不变：
- model backend
- planner
- same agent set
- same review loop cap
- same tool set

## 6.3 输出
- 每组的 SRR / CSR / SIR / assertion pass rate
- top-k evidence hit characteristics
- retrieval latency
- evidence token budget

---

## 7. RQ3：multi-agent 消融

## 7.1 推荐拆分维度

### Agent 维度
- full
- no_planner
- no_method_refactorer
- no_move_refactorer
- no_class_harmonizer
- no_reviewer

### Memory 维度
- no_semantic_memory
- no_episode_memory
- no_skill_memory

### Tool 维度
- no_ast_tool
- no_smell_detector
- no_test_tool

### Prompting 维度
- one_shot
- few_shot
- CoT
- ReAct
- ToT

## 7.2 注意事项
- `no_reviewer` 会显著降低安全性，建议只做离线实验
- `no_move_refactorer` 对 Feature Envy 的影响应重点分析
- `no_skill_memory` 适合分析程序性知识是否真的有贡献

---

## 8. RQ4：效率-效果平衡

## 8.1 重点变量
- `max_review_loops`
- retrieval top-k
- whether targeted tests are enabled
- whether move agent is enabled

## 8.2 建议分析方式
- 画出 `loops -> SRR/CSR/SIR/tokens/time`
- 找 Pareto 前沿
- 讨论何时第 3/4 轮修复开始收益递减

---

## 9. 统计建议

- 主结果报告均值 + 95% CI
- 若样本足够，可使用 bootstrap
- 对 paired task-level outcomes 可使用 McNemar 或配对非参数检验
- 显式报告 `not_applicable` 样本数量，尤其是没有测试的任务

---

## 10. 误差分析建议

对失败样本至少做以下标签：
- entity localization failure
- tag resolution failure
- patch conflict
- compile failure
- test failure
- smell not removed
- new smell introduced
- over-refactoring
- insufficient context retrieval
- wrong expert routing

这会非常有助于论文中的威胁分析和案例研究。

---

## 11. 结果产物建议

每次实验应输出：

```text
outputs/
└─ experiments/<exp_id>/
   ├─ config_snapshot.yaml
   ├─ summary_metrics.csv
   ├─ by_smell_metrics.csv
   ├─ by_project_metrics.csv
   ├─ failure_analysis.csv
   ├─ task_records/
   │  └─ <unique_id>/
   │     ├─ task_input.json
   │     ├─ retrieval_evidence.json
   │     ├─ plan.json
   │     ├─ candidate_patch.diff
   │     ├─ review_feedback.json
   │     └─ metrics.json
   └─ plots/
```

---

## 12. 最小可复现实验路径

如果你要先快速出一个可跑版本，建议先完成：

1. Long Method + Complex Method
2. semantic_only RAG
3. planner + method_refactorer + reviewer
4. compile + generated assertion
5. SRR / CSR / assertion pass / tokens / time

然后再逐步扩展到：
- Feature Envy
- move agent
- context gating
- smell introduction analysis
- 全量 ablation
