# CSR-Agent 架构设计说明（面向代码代理实现）

## 1. 设计目标

本系统用于学术科研场景下的 **Multi-Agent 可操作代码异味重构**。输入是一条带有版本、文件、方法、历史提交、局部代码与潜在重构线索的异味样本；输出是经过多智能体协作、工具验证与闭环审查后的最优重构建议与补丁。

你的初稿已经包含了四个关键方向：案例知识库、分层检索、多专家协作、指标评测。这里对其进行工程化加强，核心是把“概念设计”变成“代码代理可直接实现的系统规约”。

---

## 2. 相比初稿的关键增强

### 2.1 从“RAG = 记忆”升级为三层记忆

初稿中把记忆主要理解为 RAG，这个方向正确，但对多智能体来说不够。推荐拆成三层：

1. **语义长期记忆（semantic memory）**  
   即 RCKB，存储历史重构案例、案例向量、上下文特征、重构模式先验。

2. **过程记忆（episodic memory）**  
   存储本次 `unique_id` 执行过程中的计划、候选补丁、失败原因、审查意见、工具输出摘要。  
   作用：避免 review loop 中重复犯错。

3. **程序性记忆（procedural memory / skills）**  
   存储“如何做某类任务”的技能卡，例如：
   - long method → 优先尝试 Extract Method / Guard Clause / Decompose Conditional
   - feature envy → 优先尝试 Move Method / Extract Class / Introduce Parameter Object
   - long parameter list → 优先尝试 Introduce Parameter Object / Preserve Whole Object

这样设计后，RAG 不再只是“找相似案例”，而是整个 agent system 的长期知识底座。

### 2.2 从“固定 0.5 / 0.5 融合”升级为可消融、可回退的检索策略

你初稿中的语义相似度 0.5 + 上下文相似度 0.5 易于理解，但过于刚性。建议改为：

- 默认使用可配置加权融合  
  `score = w_semantic * s_semantic + w_structure * s_structure + w_refactor_prior * s_prior`
- 当 GraphML 缺失时，自动重归一化剩余权重
- 所有权重写入实验配置，便于做 RQ2 消融

推荐默认值：
- `w_semantic = 0.45`
- `w_structure = 0.35`
- `w_refactor_prior = 0.20`

理由：
- 代码语义仍应占主导；
- 图结构信息经常缺失，不能作为强依赖；
- `refactorings/refactor_type` 虽然有噪声，但对“动作先验”有价值。

### 2.3 把“多 Agent”从角色列表升级为“任务图 + 状态机 + 工具契约”

初稿已经定义了规划、方法级重构、代码移动、类微调、审查等角色。为了让 Codex/Copilot 能稳定落地，还需要进一步明确：

- 哪些是**智能体（LLM-driven）**
- 哪些是**系统服务（non-agent service）**
- 哪些是**工具调用（tool adapters）**
- 它们之间如何传递结构化对象
- loop 在什么条件下终止

推荐：将“复杂推理”放进 agent，将“可重复可验证工作”下沉为 tool/service。

### 2.4 针对 `code_after_refactor` 噪声，增加“实体追踪器（Entity Tracker）”

你已经意识到 `code_after_refactor` 可能不精准，这一点非常关键。建议不要仅依赖你当前的 AST 匹配，而是实现一个 **多阶段实体追踪器**：

#### 阶段 A：版本解析
- 根据 `Version`、`begin`、`disappear` 解析候选 tag
- 使用 `git tag -l "*{Version}*"` 做初筛
- 再结合时间、提交邻近性、文件存在性做 disambiguation

#### 阶段 B：实体锚定
在 `begin` 版本定位目标实体，优先级如下：
1. `Package Name + Type Name + Method Name`
2. `File Path + method signature`
3. AST 解析出的行区间与 smell 元数据的局部文本对齐
4. 归一化方法体 token 相似度

#### 阶段 C：跨版本映射
从 `begin` 到 `disappear` 跟踪目标实体：
1. 先吃 `RefactoringMiner` 输出，看是否出现 rename / move / extract / inline
2. 若无强匹配，再用 GumTree/Spoon/JavaParser AST diff
3. 若方法被拆分，保留 top-n 候选代码块，并记录不确定度

#### 阶段 D：候选排序
综合：
- signature 相似度
- token 相似度
- AST 子树相似度
- 调用邻域相似度
- 所属类/包一致性
- `refactorings` 先验证据

最终不再输出单一“绝对正确的 code_after_refactor”，而是：
- `best_match`
- `alternative_matches`
- `confidence`
- `mapping_rationale`

这对后续训练、评测和错误分析都更稳。

---

## 3. 总体架构

推荐采用 8 层架构：

1. **Dataset Layer**  
   读取 CSV、规范化字段、构造 task record

2. **Repository & Version Layer**  
   tag 匹配、checkout、代码定位、实体追踪

3. **Case Knowledge Base Layer**  
   训练集案例结构化、向量化、索引构建

4. **Retrieval Layer**  
   粗检索、上下文门控、重排序、证据打包

5. **Agent Orchestration Layer**  
   任务图规划、agent 调度、会话记忆、loop 控制

6. **Tool Adapter Layer**  
   Git、AST、diff、build、test、smell detector、vector DB 等统一封装

7. **Validation & Review Layer**  
   编译、测试、异味复检、补丁风险审查、结构化反馈

8. **Evaluation Layer**  
   SRR / SIR / CSR / 测试断言通过率 / token / 时间 / CodeBLEU / 消融记录

---

## 4. 核心数据对象

## 4.1 RefactoringTask

每条异味样本应在系统内部转为统一对象：

- `task_id` = `unique_id`
- `project`
- `version_hint`
- `resolved_begin_tag`
- `resolved_disappear_tag`
- `file_path`
- `package_name`
- `type_name`
- `method_name`
- `smell_type`
- `smell_metadata`
- `raw_code`
- `commit_history`
- `diff`
- `refactoring_hints`
- `graph_context_path`
- `context_availability`
- `expected_outputs`

## 4.2 RefactoringCase（RCKB 中的案例单元）

一个案例不要只保存“前后代码”，而要保存以下字段：

- 基本信息：项目、版本、异味类型、unique_id
- 异味前代码片段
- 异味消失后的候选代码片段
- 重构动作序列（标准化）
- 相关提交摘要
- 上下文摘要（类级、调用级、图级）
- 编译/测试结果（若可得）
- smell 消除情况
- 向量表示：
  - `code_embedding`
  - `context_embedding`
  - `refactor_pattern_embedding`
- 质量标签：
  - `mapping_confidence`
  - `data_noise_flags`

---

## 5. 多智能体设计

## 5.1 设计原则

不是所有模块都要做成 agent。建议遵循：

- **需要策略规划与不确定性决策的** → agent
- **需要稳定执行和可验证输出的** → tool / service
- **需要共享经验但不能污染结果的** → memory

## 5.2 推荐角色划分

### A. Planner / Orchestrator Agent（保留）
职责：
- 读取任务、检索证据、决定任务图
- 选择执行路径：方法内重构 / 跨类移动 / 结构收尾
- 合并 reviewer 反馈，决定是否进入下一轮

输入：
- `RefactoringTask`
- `EvidencePack`
- 当前 episode memory

输出：
- `PlanGraph`
- 本轮 agent 调度序列
- 停止 / 重试 / 降级决策

### B. Method Refactorer Agent（保留）
适用：
- Long Method
- Complex Method
- Long Parameter List 的方法内收敛

职责：
- 仅在局部方法和必要邻域中做小到中等规模变换
- 优先采用低风险、高可验证性的操作

候选动作：
- Extract Method
- Replace Temp with Query
- Introduce Parameter Object
- Decompose Conditional
- Guard Clause
- Split Loop
- Simplify Boolean Expression

### C. Move Refactorer Agent（保留）
适用：
- Feature Envy
- 需要跨类/跨文件职责迁移的场景

职责：
- 识别主责任对象
- 规划 move method / extract class / move field 等候选方案
- 同步修改调用点、导入、访问权限

注意：
- 这类补丁风险最高，必须强依赖 AST、引用分析和 reviewer

### D. Class Harmonizer Agent（保留）
职责：
- 对前面 agent 造成的结构碎片进行收尾
- 只做低风险修饰，不应重写主逻辑

候选动作：
- 调整可见性
- 合并冗余私有辅助方法
- 清理未使用 import / member
- 参数命名和局部命名规范化
- 补最少必要注释（只在实验允许时）

### E. Reviewer-Verifier Agent（保留，最关键）
职责：
- 汇总工具结果
- 判断是否接受当前补丁
- 输出结构化失败原因
- 驱动闭环迭代

它本身不直接大改代码，而是做“诊断 + 反馈生成”。

### F. 非 Agent 服务：Patch Integrator（新增）
原因：
多 agent 同时产出 patch 时，合并逻辑不应靠 LLM 自由发挥。  
建议实现为系统服务，职责是：
- patch apply
- patch merge
- 冲突检测
- 统一 diff 生成
- 行号映射维护

### G. 非 Agent 服务：Memory Manager（新增）
职责：
- 管理 RAG 证据
- 管理 episode memory
- 管理 skill card 检索

---

## 6. Agent 系统中的“记忆、规划、行动、工具、skills”

## 6.1 记忆（Memory）
建议明确三种 memory store：

- `semantic_store`：RCKB 检索案例
- `episodic_store`：本轮执行日志、失败点、尝试过的 patch
- `skill_store`：面向 smell 的程序性规则卡

## 6.2 规划（Planning）
Planner 不要只输出自然语言说明，必须输出 `PlanGraph`：

节点示例：
- retrieve_evidence
- inspect_repository
- method_refactor
- move_refactor
- harmonize_class
- compile_check
- targeted_test
- smell_redetect
- review_decision

边类型：
- `serial`
- `parallel`
- `conditional_on_failure`
- `conditional_on_smell_type`

## 6.3 行动（Action）
agent 的行动必须通过 tool adapter 落地，而不是直接声称“我已经检查过”。

## 6.4 工具（Tools）
推荐统一工具接口，便于替换不同实现：

- `git_tool`
- `repo_browser_tool`
- `ast_tool`
- `entity_tracker_tool`
- `patch_tool`
- `build_tool`
- `test_tool`
- `smell_detector_tool`
- `retrieval_tool`
- `metrics_tool`

## 6.5 Skills
你提到希望体现 skills，这非常适合做成**可检索的任务卡**。  
每张 skill card 包含：

- 适用 smell
- 前置条件
- 推荐重构动作
- 禁忌动作
- 常见失败模式
- 验证要点
- 低风险替代策略

例如：

### Skill: Long Method / Guarded Extraction
- 适用于深层嵌套和重复逻辑
- 优先抽取无副作用代码块
- 若共享局部变量太多，则优先引入局部对象或拆分条件，而不是强行提取

### Skill: Feature Envy / Move Method
- 适用于方法对外部类字段/方法依赖显著高于本类
- 先检查目标类是否具备完整依赖
- 若 move 后会暴露太多内部状态，则退化为 Extract Helper + Delegate

---

## 7. 推荐执行状态机

每个任务建议按以下状态机执行：

1. `task_loaded`
2. `version_resolved`
3. `entity_located`
4. `evidence_retrieved`
5. `plan_generated`
6. `patch_generated`
7. `patch_integrated`
8. `static_validated`
9. `dynamic_validated`
10. `smell_rechecked`
11. `reviewed`
12. `accepted` or `replan` or `failed`

终止条件：
- reviewer 接受
- review loop 达到上限
- 工具发现不可恢复问题（如目标实体无法定位）

---

## 8. RAG 设计建议（对应 RQ2）

## 8.1 检索单元
建议检索对象不是“整条样本”，而是：
- smell code snippet
- enclosing method / class summary
- historical refactoring action sequence
- related diff hunks
- graph context summary

## 8.2 三阶段检索
与初稿一致，但更细化：

### 阶段 1：粗召回
使用代码语义向量检索 top-N

### 阶段 2：上下文门控
使用以下特征过滤或降权：
- smell 类型一致性
- 方法/类粒度一致性
- graph/context 相似度
- 项目规模相似区间
- refactor_type 先验

### 阶段 3：重排序
用加权融合或轻量 cross-encoder 排序，输出 top-k 证据包

## 8.3 缺失 GraphML 的处理
GraphML 缺失时不要丢弃样本，记录：
- `context_missing.graph = true`
- 自动切换到 `semantic + lexical + diff prior` 路径

---

## 9. 审查与验证设计

## 9.1 静态验证
至少包括：
- patch 可应用
- Java 语法解析通过
- 编译通过
- import / symbol resolution 正常

## 9.2 动态验证
优先级：
1. 与修改实体强相关的现有单元测试
2. 若无现成测试，针对方法级异味生成轻量断言测试
3. 若仍不可行，只保留静态验证并标记风险升高

## 9.3 异味复检
建议使用不少于两个检测器：
- DesigniteJava
- PMD

输出：
- 目标异味是否消除
- 是否引入新异味
- 引入了哪些异味、位于何处

## 9.4 Reviewer 的结构化反馈
反馈必须至少包含：
- `failure_stage`
- `symptom`
- `location`
- `risk_level`
- `suggested_fix`
- `should_retry`
- `recommended_agent`
- `forbidden_actions_next_round`

---

## 10. 指标定义（对应 RQ1 / RQ3 / RQ4）

## 10.1 SRR（Smell Removal Rate）
定义：
- 目标异味在最终补丁后不再被检测到的任务比例

## 10.2 SIR（Smell Introduction Rate）
建议同时记录两种口径：
1. **binary-task SIR**：任务是否引入至少一个新异味
2. **count-normalized SIR**：每个任务平均新增异味数

这样分析更细。

## 10.3 CSR（Compilation Success Rate）
最终补丁能够通过编译/静态检查的任务比例。

## 10.4 Assertion/Test Pass Rate
对方法级异味记录：
- 相关测试通过率
- 生成断言的通过率
- 若没有测试，需明确标记 `not_applicable`

## 10.5 Cost
至少统计：
- input tokens
- output tokens
- total tokens
- wall-clock time
- tool execution time
- review loop count

## 10.6 CodeBLEU
用于对比数据集中已有的 `code_after_refactor` 候选，但必须注意：
- 它只能做“相似性参考”
- 不应当作行为正确性的核心指标

---

## 11. 消融实验设计建议

## 11.1 RQ2：RAG 消融
最小组合建议：

- semantic_only
- context_only
- semantic_plus_context
- semantic_plus_context_plus_refactor_prior
- no_rag

## 11.2 RQ3：multi-agent 消融
建议维度：

- full system
- no_planner（单代理直接重构）
- no_move_agent
- no_class_harmonizer
- no_review_loop
- no_tools
- no_skills
- no_episode_memory
- no_semantic_memory
- prompt_strategy variants（CoT / one-shot / few-shot / ToT / ReAct）

注意：  
“prompt 策略”最好作为单独配置维度，不要硬编码在 agent 类里。

## 11.3 RQ4：效率成本分析
建议固定其他变量，仅改变：
- `max_review_loops = 1, 2, 3, 4`
- top-k 检索数
- 是否启用 targeted tests
- 是否启用 move agent

---

## 12. 推荐仓库结构

```text
csr-agent/
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ configs/
│  ├─ pipeline_config.template.yaml
│  ├─ agent_contracts.yaml
│  └─ model_backends.yaml
├─ data/
│  ├─ raw/
│  ├─ processed/
│  └─ indexes/
├─ docs/
│  ├─ architecture_spec.md
│  └─ experiment_protocol.md
├─ src/
│  ├─ dataset/
│  ├─ resolver/
│  ├─ kb/
│  ├─ retrieval/
│  ├─ memory/
│  ├─ planning/
│  ├─ agents/
│  ├─ tools/
│  ├─ patching/
│  ├─ validation/
│  ├─ evaluation/
│  └─ runner/
├─ tests/
│  ├─ unit/
│  └─ integration/
└─ outputs/
   └─ <project>/<unique_id>/
```

---

## 13. 建议的工程落地顺序

推荐按以下顺序实现，能最大限度降低失败概率：

### Phase 1：单任务最小闭环
- 数据加载
- tag 解析
- 实体定位
- 单一 refactor agent
- 编译检查
- metrics 输出

### Phase 2：RCKB + 检索
- case build
- semantic retrieval
- rerank
- evidence pack

### Phase 3：多 agent 协作
- planner
- move agent
- class harmonizer
- reviewer loop

### Phase 4：评测与消融
- config-driven runner
- batch experiments
- ablation switch
- result aggregation

---

## 14. 最重要的实现边界

1. **不要把所有能力塞给单个大 agent。**
2. **不要把工具输出只作为文本附注，必须结构化。**
3. **不要假设 `code_after_refactor` 绝对可信。**
4. **不要把 GraphML 缺失视为异常退出。**
5. **不要把 CodeBLEU 当作主指标。**
6. **不要把 prompt 模板和 agent 逻辑写死在一起。**

---

## 15. 最终建议

如果你的目标是“让 Codex / Copilot / Antigravity 更容易实现这个系统”，那么最佳文件形态不是单篇论文式设计文档，而是：

- 一个 `AGENTS.md`：约束代码代理行为
- 一个详细架构文档：说明为什么这样设计
- 一个机器可读契约文件：明确 agent / tool / state / schema
- 一个实验开关模板：方便后续消融实验

本规范包已经按照这个思路组织。
