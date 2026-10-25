# 科研整理质量基准

这个小型基准验证整理工具的可重复行为，并为真实 Agent 对照提供同一组输入。它不自动证明报告语义完整，也不证明 Skill 优于传统整理或普通 Agent。哈希恢复、关系可达、接续理解分别验收，不能互相替代。

## 可重复运行的工程验收

从技能目录运行：

```powershell
python -m pytest tests/test_research_benchmark.py tests/test_organization_ops.py tests/test_evidence_index.py -q
```

`tests/test_research_benchmark.py` 的 `build_fixture(root)` 创建相同输入：一个假设、三种子结果及误写/更正、一个已完成阴性实验、一个输入缺失而中断的运行、配置和代码版本绑定、原始二进制及冻结哈希、两份同名异文笔记、无关主题和明确保护项。数据是合成测试材料，不使用私人数据、不联网、不训练模型。

集成测试预先提供参考报告，只检验确定性操作：预演不改源件，合并后的清理可逐件恢复，全部原始非保护内容仍可获取，冻结绑定不变，同名不同内容不覆盖，保护项元数据未变，现行链接可达，项目散件净减少。恢复包成员另计，不把包装压减称为信息减少。另检验一个结果文件变化只通知依赖它的结论、决策和报告；删除中断日志不会变更其科学状态或把它当作有效阴性结果。

**自动验收边界**：参考报告由测试预设，工具不会自行判断每句话是否完整、结论是否正确或接手者是否理解。结构化 `coverage` / `review` 字段只是审查声明；不是独立审查已经发生的证明。回滚包能恢复原文，也不能证明综合报告覆盖了原文。

## 工具的最小输入与调用

需要精确文件操作时，准备 JSON 计划。下例中的哈希必须替换为实际源文件 SHA256；工作根必须为真实绝对目录。目标不能覆盖既有文件：

```json
{
  "schema": 1,
  "root": "D:/Research",
  "protected_sources": ["data/raw", "frozen", "reserved"],
  "operations": [{
    "op": "move", "source": "notes/result.md", "target": "reports/result.md",
    "sha256": "<64位小写SHA256>", "reason": "归入现行报告位置"
  }]
}
```

`remove` 不需 target，但必须增加 `evidence: {"coverage": "保留位置与逐项覆盖依据", "review": "审查记录"}`；`replace` 还需 `replacement` 和 `replacement_sha256`，指向工作根内预先准备的替代文件。声明不能取代实际审阅。每个计划按可独立核验的范围编制，不以一个巨型计划替代小批次。

`protected_sources` 是项目相对路径前缀，同时限制源、目标和替代源，工具在读取payload前检查；默认还保护明显封存、凭据、Git与环境文件名。必须声明项目中名字不可识别的保护范围，工具不能自行推断所有科研语义。新版恢复包封存计划/保护前缀，回滚拒绝仅编辑state放宽范围；旧版无此绑定的包不自动回滚，可在隔离位置审查恢复，不能宣称与新版具有同等保证。

```powershell
python scripts/organization_ops.py dry-run D:/temporary/plan.json
python scripts/organization_ops.py apply D:/temporary/plan.json --state-dir D:/temporary/new-recovery-state
python scripts/organization_ops.py rollback D:/temporary/new-recovery-state
```

状态目录必须是工作根外的新目录。恢复包须保留到验收完成；回滚会检查恢复包和当前文件，遇后续修改或无法判明的丢失状态会拒绝自动覆盖。需要从完整恢复包取回独立文件时，先恢复到隔离位置再审阅，不把自动拒绝当成恢复包已丢失。该工具不管理空目录、不保留旧路径接口，也不解除环境审批。

关键证据关系可加入现有索引，最小结构如下；同一份 JSON 可保留其他业务字段：

```json
{
  "schema_version": 1,
  "objects": [
    {"id": "experiment:01", "kind": "experiment", "status": "completed", "stage": "exploration", "sources": [{"path": "results/run.json"}]},
    {"id": "claim:01", "kind": "claim", "status": "scoped", "sources": [{"path": "reports/findings.md"}]}
  ],
  "relations": [{"from": "experiment:01", "to": "claim:01", "type": "supports"}],
  "excluded_sources": ["sealed"]
}
```

来源 path 使用项目相对 POSIX 路径，可增加 sha256 约束或 `protected: true` 声明。supports/contradicts/supersedes 从 from 向 to 传播复核，depends_on 从 to 向 from 传播。stage 可选 exploration、validated_method、formal_result；这是已有研究状态的登记，不由工具自动晋升。

```powershell
python scripts/evidence_index.py validate --index D:/Research/INDEX.json --root D:/Research
python scripts/evidence_index.py snapshot --index D:/Research/INDEX.json --root D:/Research --out D:/temporary/before.json
# 只筛选候选，不读取来源payload；所有对象仍未验证
python scripts/evidence_index.py scan --index D:/Research/INDEX.json --root D:/Research --previous D:/temporary/before.json --out D:/temporary/candidates.json
# 在实际新增/修改发生后重新生成 after 快照
python scripts/evidence_index.py snapshot --index D:/Research/INDEX.json --root D:/Research --out D:/temporary/after.json
python scripts/evidence_index.py impact --before D:/temporary/before.json --after D:/temporary/after.json
```

`direct_changes` 是严格快照的实际变化；`invalid_objects` 包含当前仍缺失或哈希错误的对象，即使两次快照相同也进入 `review_required`。`reusable_objects` 只说明此索引中严格校验后的结构未变、无绑定错误且无未验证来源依赖；保护来源及其依赖保持 `unverified_objects`，不列入可复用。`impact` 拒绝metadata scan输入。

`scan` 比较size、mtime/ctime和文件身份等元数据，返回candidate_sources/changed_sources/needs_strict_verification；旧快照缺元数据时作为需严格复核候选。即使元数据一致，内容仍可能变更，全部对象继续未验证，不能拿scan替代删除前哈希或冻结证据认证。validate/snapshot保留完整哈希及读取前后状态检查。metrics仅统计来源payload读取/哈希和显式stat，不包括索引JSON读取、路径检查、操作系统缓存和Agent阅读开销。

使用 `python scripts/benchmark_organization.py --index D:/Research/INDEX.json --root D:/Research --repeats 3` 对同一选择范围输出两次strict和一次scan的耗时与I/O。固定顺序受缓存影响；零payload读取不证明内容未变，也不证明整个整理或LLM Token提速。规模操作比较可将7b54715的脚本导出为外部本地baseline，在相同输入/路径深度/磁盘比较预演；不得为提高成绩移除并发检查或恢复验证。时间报告观测值，不在回归中断言脆弱秒数。

在Git仓库副本中可重跑规模预演（目标文件位于外部临时目录；只导入你已审阅的本地baseline，不下载或执行未知脚本）：

```powershell
git show 7b54715:scripts/organization_ops.py | Set-Content -LiteralPath "$env:TEMP/organize-old-ops.py" -Encoding utf8
python scripts/benchmark_organization.py --operations 100 --baseline-ops "$env:TEMP/organize-old-ops.py" --repeats 2
```

可用`--operations 600`或`6000`扩大规模；旧版600项可能需数分钟。无baseline参数时仅测当前实现。计时只含dry-run；计时外核对计划、文件字节/时间/mode和目录不变，记录实现源哈希。它不执行apply、不测回滚或科研语义；恢复能力另由回归覆盖。

生命周期集成测试检查：无变化二次scan/strict不写报告或增加文件；新更正影响实际依赖；stage/scope/lifecycle变更保留并触发复核；metadata-only不变成严格验收。这些是预设内容的工程测试，不能证明LLM能自动发现任意证据等级升级。

## 端到端耗时与重复工作

先定义本轮任务和固定输入：深度重构、功能开发、只读维护、软件测试及远端发布分别计时。不能把一次包含开发/调试/等待CI的任务，与已整理项目的轻量检查比较并宣称提速。30%–50%端到端降时是待验证目标；同一模型、预算、输入及质量约束的对照未做时不报达标。

### 动态阅读与快速收口

从用户目标、完整变化清单、已有核验及未解决问题决定深度，不用固定文件数量阈值。下表是决策条件，无需另建永久任务规划数据库：

| 深度 | 进入条件 | 必要工作与停止条件 |
|---|---|---|
| 深度重构 | 用户明确要求，或现有综合/依赖/覆盖不足以完成目标 | 理解拟替代资料，按科研问题综合并核对独有事实；完整覆盖、现行调用及恢复验收通过才收口 |
| 局部增量 | 局部内容/依赖变化，出现矛盾，或仍有影响本轮目标的问题 | 深读变化及影响闭包；相关结论、引用和行为已核验，未解决差异有明确状态后收口 |
| 快速结束 | 仅维护或检查；范围/保护策略/目标一致；相关已有结果仍有效；无新增影响且无本轮待处理问题 | 复用有效检查，简要交付范围与结果；不重新综合、改写稳定报告或为本轮增加永久文件 |

元数据无变化只支持候选筛选，不能单独证明上述快速结束条件。排除范围外的来源、环境变化、未核验来源及未完成的既定整理不能被“零变化”隐藏；不确定时只补足该项证据。深度重构请求即使没有新增文件也照常完成，不以快速结束代替用户目标。无变化检查的结论也不自动证明项目已经全量科学整理。

阅读采用入口→来源定位/检索→相关段落→必要全文。每次深入应对应一个会改变处置的疑问，例如条件是否不同、数值属于哪个端点、阴性结果是否其实为执行失败。优先重要结论及其反证，不因扩展名或篇幅机械全读。拟删除或语义替代资料仍须全文理解，主动尝试找出目标报告未正确保留的任一独有事实；找到反例就补齐或保留源件。任务内只复用绑定当前内容身份、事实及位置的记录（`scripts/task_context.py`），矛盾、来源变化、范围/依赖改变或破坏性动作触发相关复核；摘要缓存不能代替删除前哈希和语义覆盖。

定位到数字后，仍需在该来源中找到这条结论的适用条件、失败/未完成身份及可重放边界；关键词只负责定位。实际试用曾出现解析值已改对，但同一来源中的历史checkpoint及不可重放规模未进入维护报告，或修复了重放限制却没明确共享潜变量条件。此时不能按“更快完成”验收；补齐相关事实闭包，不必重读无关研究。

独立查询合批返回带来源身份的紧凑记录，让模型集中处理冲突和取舍。用户授权多代理时，只并行互不依赖主题的读取/分析，交付事实位置、反例及未决问题，由一个执行者修改共享报告、计划与索引。先判断启动开销和共享依赖是否抵消收益，不为凑代理数重复阅读相同全文。

`task_context.py`是同一Python进程内的短期工作结果，不是后台服务或跨会话数据库。将`scripts`放入Python模块路径后使用：

```python
from task_context import TaskContext
context = TaskContext(root, opaque=('data/raw', 'sealed'))
batch = context.batch([
    {'source_id': 'reports/result.md', 'start_line': 12, 'end_line': 26},
    {'source_id': 'reports/protocol.md', 'start_line': 1, 'end_line': 20},
])
if batch['complete']:
    context.record('finding', ['reports/result.md', 'reports/protocol.md'],
                   facts={'interpretation': '已实际阅读摘录后填写的事实声明'},
                   unresolved_questions=['尚未核对误差条口径'])
    context.result('finding')              # 复用固定快照；未决项保持needs_review
    context.result('finding', fresh=True)  # 重读所选来源及依赖，变化则stale
```

`excerpt`/`batch`返回source_id、字节哈希、行号及限长原文；`record`保留这些位置、事实声明、记录依赖与未决问题，不执行LLM自动抽取。`snapshot_status=snapshot_reusable`只指已读快照，不能声明磁盘当前无变化；`fresh=True`失败或字节改变不会回退到旧缓存。根及opaque策略固定，改变目标/范围另建context。可信`source_resolver(id)->bytes`仅显式传入，保护项在调用前拒绝；其内部I/O无法计量，大小限制也不能阻止任意外部回调先行读取大文件。缓存不跨进程自动保存；多个工具往返使用同一个已持有context的会话，或将读/抽取/复核合批在一次进程内，不能重新启动Python后声称缓存命中。拟删除仍单独完成当前哈希、全来源覆盖和恢复验收。

#### 证据闭包与紧凑输出

对本轮受影响的重要结论，在阅读前按实际问题确定必要维度；通常包括结果、条件、协议、证据等级、限制与执行状态，涉及历史重放再加入重放边界。不适用项在已有审阅中说明理由，不能为获得通过而缩减必要维度。优先核对缺项对应的原文及反例，未知保持待复核；不要重新读无关全文。拟替代/删除资料的全文覆盖规则不变。

`record(required_context=..., context_reviews=...)`在现有任务记录内保存此声明，不建立另一套事实库。维度名称由调用者选择，每项审阅包含`status`（`reviewed`或`unknown`）、具体`note`及非空`citations`。引文使用`excerpt`返回值，工具核对来源归属、已返回的行范围、SHA256和原文；未读、篡改或失效的摘录不能作为新审阅依据。缺失和`unknown`均进入`context_gaps`，依赖中的缺口也使`closure_status`保持`needs_review`。`reviewed`引文不能是纯空白。

```python
context = TaskContext(root, opaque=('data/raw', 'sealed'))
value = context.excerpt('reports/result.md', 12, 14)
context.record('finding', ['reports/result.md'], facts={'result': '实际观察到的结果'},
               required_context=['result', 'conditions', 'replay'],
               context_reviews={'result': {
                   'status': 'reviewed', 'note': '已核对结果身份及统计口径', 'citations': [value]}})
brief = context.result('finding', compact=True)
# brief['context_gaps'] == {'finding': ['conditions', 'replay']}
# 只追查这两项；核对后重写该条record，保留全部仍必要的维度、事实与审阅。
```

`result(compact=True)`省去事实正文和审阅引文，保留签名、来源哈希/位置、所有未决问题、缺失维度和失效状态；仅在具体决策需要时请求完整结果。它是所选记录的紧凑状态，不是跨调用自动增量传输；调用者只输出本轮需要的记录。`record`返回完整记录便于调试，正常流程不必打印该返回值。完整变化清单仍保存在外部并处理全部影响，不能将stdout预览当作全量。

`result`不再返回含混的通用`status`：`snapshot_status`仅回答缓存绑定是否可复用，`closure_status`回答整个依赖闭包的已声明维度是否完成。任一传递依赖未声明必要维度，会列入`unassessed_records`并阻止`declared_covered`；无其他缺口时返回`not_assessed`。`closure_status=declared_covered`仅表示声明绑定齐备，它不证明维度选择完整、引文支持解释、报告覆盖充分或审阅独立发生，也不是任务完成许可。重要报告由独立内容审阅者从原始资料重新检查条件与反例，不能只核对同一整理者声明的维度。审阅缺口须补齐或明确部分完成，不能由缓存状态放行。`fresh=True`只重读字节并撤销失效绑定，不自动更新事实或完成语义审阅。阅读侧缺口关闭后，报告仍按`claim_coverage.py`及独立内容审阅核验；这两种检查不能互代。

结束一个修改步骤时，将已核验输入、命令/环境身份和修改后产物摘要记入外部任务状态一次，后续复用同一条记录；只有源文件摘要而缺少修改后报告绑定，不能直接继承报告验收。使用`TaskContext`时，先摘录修改后报告，将报告路径与来源一起列入验收记录的`source_ids`，需要当前身份时调用`result(..., fresh=True, compact=True)`；报告变更也会使记录stale。范围/环境改变则另行复核，不能只靠字节判定。这些状态用于本任务接续，不是项目内新增报告；无法匹配时补足必要核验，而非默认再次全文综合。

收口按本轮授权义务判断：`COMPLETE`仅用于必要检查通过且无验收缺口；`PARTIAL`用于可独立交付的工作已完成但仍有明确缺口；`BLOCKED`用于必要条件不足、无法继续相关动作。工具快照状态不等于任务完成状态。未知项如实列出，不升级为已验证；证据不足时保留受影响资料。无变化维护无需制造结论审阅记录。

#### 质量约束下的配对性能评价

PR #3的单次真实文本试用存在两版条件遗漏及不同重试，不能作为同质量提速结论。下一轮先在合成反例上调试，再固定未用于开发的项目、事实答案、初始字节、模型、环境、预算和验收规则，评价者单独持有答案。至少覆盖首次整理、无变化、局部增量和条件缺失/矛盾情形。当前自动回归只检验预设声明及绑定行为，不算未见项目Agent评价。

需要决定保留哪些优化时，用同一修复版本作配对消融：固定质量义务，比较完整策略与分别关闭自适应阅读、任务内复用、紧凑输出的变体，每次只改变一项。所有变体仍须处理完整变化清单，不能用截断清单作为对照。先检查实际调用轨迹确实触发差异；未调用某接口的运行不能证明其收益。跨进程缓存仅在轨迹证实重复读取成本后另作设计。

每个任务/变体至少5次配对运行，随机化执行顺序；保留所有失败、重试、取消和纠错成本。墙钟从接收任务计到质量验收，另报首次交付与纠错时间；未能修复者计为失败，不从正确完成率分母剔除。先报告关键事实/条件遗漏、独有证据损失、证据升级、受影响对象漏查和行为破坏，再在质量通过的配对中报告耗时中位数、范围与每对差值。不得只选最快成功案例。

从真实用量记录分别报告输入、缓存输入、输出Token、调用数、源读取/哈希次数及读取字节；缺测写N/A，序列化字节减少不等于Token减少。保存代码提交、输入/产物身份和匿名结果于外部任务目录，必要汇总进入仓库既有报告。30%–50%仅为待检验目标；没有完成这些对照时，交付明确标注“工程验证通过，端到端收益未测”。

真实比较分别固定首次深度整理、无变化二次检查、局部增量三个任务。每类用同一初始快照、模型、工具/质量约束和预算，对比原版与新版，评价者单独持有事实答案；记录从接收任务到验收的墙钟、实际调用/Token、重复读取、事实覆盖、证据恢复与当前行为。局部增量应检查受影响对象没有漏查、无关主题没有重写；快速结束应检查未决问题和深度请求不会被跳过。未执行同条件Agent对照时，工具计时与人工策略描述不能填作端到端收益。

先读入口与存储政策，明确 `--opaque` 后盘点一次；本轮无目录变化就复用结果。示例快照必须在项目外，包含文件元数据及必要排除范围，不能上传原始会话日志：

```powershell
python scripts/workspace_scout.py --root D:/Research --opaque data/raw --opaque data/external --opaque tmp --snapshot-out C:/temporary/before.json
python scripts/workspace_scout.py --root D:/Research --opaque data/raw --opaque data/external --opaque tmp --previous C:/temporary/before.json --snapshot-out C:/temporary/after.json
# 超出stdout预览的全部变化写到项目外，不覆盖previous或snapshot
python scripts/workspace_scout.py --root D:/Research --opaque data/raw --opaque data/external --opaque tmp --previous C:/temporary/before.json --changes-out C:/temporary/changes.json
```

第二次仍遍历未排除目录，变化报告只用于挑选候选。`entry_stat_calls` 是目录项stat接口调用次数，未等价于底层磁盘I/O；`source_payload_files_opened=0`仅针对盘点。默认保护不能识别项目所有语义，必须先显式排除数据/包/环境；快照大小写按平台规则处理，不能借父级链接写回项目内。

默认stdout只保留`change_preview`及每类`change_preview_truncated`，截断不是变化范围。API调用`delta(..., include_changes=True)`取得完整`change_paths`，或读取`--changes-out`中的`changes`；仅含baseline/added/metadata_changed/missing，不把未变全量路径再次送入上下文。敏感文件、目录和链接均仅计数，不记录敏感相对名。

将实际流程分段记录在外部任务目录：盘点/快照，来源读取与哈希，Agent理解/综合，计划执行/恢复同步，质量检查及发布等待。记录工具调用、分析对象和重复读取；没有可靠的文件读取/模型计量时，相关指标写N/A，不用字符数推算Token。只重查变化对象及依赖；批量读必要引文并保留来源/行号，避免先输出整份报告、随后逐段重读。严格快照、事实门控可在同一短进程共享已固定身份的来源字节；活文件、删除前或无法证实稳定时仍重新核验。源读取器调用数、唯一源读取数及缓存命中分别记录，不能混为零读取。

已有明确授权且可取得本地Codex会话JSONL时，可用现有基准工具输出匿名汇总：

```powershell
python scripts/benchmark_organization.py --trace C:/temporary/rollout.jsonl
# 可用 --turn-id 指定某一轮；不从会话内容执行命令
```

工具统计实际 `token_usage_record` 的独立response用量，去重而不累加重复的 `token_count` 累计事件；区分输入、缓存输入及输出，reasoning是输出子集。缺少用量写null。`Reasoning`、`CommandExecution`、`ContextCompaction`等为运行时标记区间，其并集仅描述观测墙钟时间，不是CPU时间，也不等于科研理解/综合阶段；各类区间可能重叠，不能直接相加。未归因时间保留未知，不归咎于模型或磁盘。仅含当前trace，子代理另计且并行时间不能加到主任务总墙钟。输出不含提示词、命令、思维原文或文件内容；日志原件留本地。

验收按受影响行为选测试；发布前完成该树所需检查。绑定同一树、环境、输入及命令的通过结果可以复用；代码/数据改变、失败或未解疑点使相关结果失效，再测受影响部分。不要每完成一段文档就重跑全项目，再在相同树重复跑全套来“增加信心”。

执行日志优化先实测 `_save`时间、次数/写入字节、恢复包和哈希成本；如果实际整理没有文件变更，改造执行日志不能降低这轮耗时。追加式日志尚不是当前执行路径。只有它在目标任务中占主导且恢复一致性回归覆盖中断、尾部损坏、并发修改、回滚重入后，才考虑替换全量state；保留fsync及严格恢复保障，不能用孤立JSON写入速度冒充完整apply/rollback提速。

## 三组同输入对照

在需要比较方法时另行执行；不要把上述测试结果当成比较结果。

1. 评价者生成一个输入目录并保存不可由被测整理者访问的原始快照、事实答案和文件计数。复制为三个独立工作区，逐文件核对初始字节相同。设置相同保护项、可用工具、时间/Token预算和清理授权，禁止新增实验与外部数据。
2. A 组仅用预先固定的扩展名/日期/重复哈希规则；B 组用普通 Agent，提示“整理科研项目，保全信息并便于使用”，不加载本 Skill；C 组加载当前 `organize-files`。记录模型、提示、工具、技能提交/工作副本哈希、真实预算和操作轨迹。若普通 Agent 实际获得了 Skill 上下文，不能算独立 B 组。
3. 三组接受相同的科研检索与接续问题，并交付其方法实际产生的入口、报告、证据和代码；规则组不能被暗中补写科学综合报告，未生成的能力如实记为缺失。以相同问题的答题与追溯表现比较，不把某种输出格式本身作为胜负条件。允许重构及清理完整被替代的散件，不要求旧路径或旧命令继续存在。评价恢复源可在隔离位置保存，不制造项目内平行入口。
4. 评价者核对所有独有事实和冻结字节。另请未看原目录、聊天、方法标签和预期答案的接手者，仅从整理后入口完成相同问题；记录实际查找步骤、耗时及可得 Token 用量。没有这样的独立接手过程就标为“未开展盲测”。
5. 在各组复制件中对同一个结果文件作同样小修改，再维护一次。核对哪些对象重新检查、报告是否更新以及无关资料是否被重写。比较实际成本，不能只以“支持增量”这一功能存在推断成本更低。

要导出输入，可从技能根目录运行下例；目标目录必须尚不存在：

```powershell
python -c "import runpy; from pathlib import Path; runpy.run_path('tests/test_research_benchmark.py')['build_fixture'](Path('D:/temporary-research-benchmark/input'))"
```

测试源码含评价答案。正式盲测时整理者只取得生成的输入目录；评价者单独持有测试源码、原始快照及问题答案。不要将预设参考报告交给被测 Agent。为了避免学会固定题，真实比较还需追加未见过的同类项目和独立事实答案。

## 发布后的干净检出检查

发布任务另用拟提交树建立外部检出，不借用工作目录的忽略文件或数据包。检查入口及代表性结论能否定位协议、实现、更正/负结果与固定版本；浅克隆缺历史对象应明确取回，不视为通过。关键文本来源与数据级复现分别验收，真实资产检查只在显式启用时运行，缺资产应失败。记录新增文件类型/体积、删除覆盖和实际未上传范围；CI变绿不能替代发布范围与来源核对。

## 指标及判定

第三轮真实案例回归使用 `tests/fixtures/maestro_claim_coverage.json`：保存MAESTRO固定来源的真实文本、原报告与更正后选定引文、独立抽取的六维事实。覆盖数值归属、有效阴性停止、工程失败与未执行；不使用换数字的玩具实验代替这些案例。回归故意变更阈值、解析/估计身份、证据等级、执行状态、限制及来源绑定，以检查能否阻塞。此夹具仅是已见案例的选定事实回归，既不穷举项目事实，也不是普通Agent/旧skill/新skill的模型对照；后者未执行则N/A。

| 指标 | 分子 / 分母或记录方式 | 验收边界 |
|---|---|---|
| 精确信息保留率 | 仍能按哈希读取的唯一原始对象 / 所有要求精确保留对象 | 冻结/唯一原始证据须 100%；保护项只检查范围边界，不能为计分打开 |
| 语义信息覆盖率 | 独立审查确认在报告或可读证据中准确保留的事实项 / 预先列出的独有事实项 | 数值、条件、失败、更正和未知状态分别计；摘要存在不算覆盖 |
| 证据追溯成功率 | 从现行结论找齐研究身份、数据、参数、代码版本、结果及更正的成功题数 / 适用题数 | 来源可达是必要条件；仅路径存在不等于结论被支持 |
| 接续成功率 | 盲测接手者准确回答并给出证据的题数 / 适用问题数 | 未实施盲测则 N/A，不用自动图遍历代替 |
| 有效检索成本 | 每道成功问题的耗时、工具步骤和实际可得 Token | 错答/找不到单列，不能用提前停止降低均值 |
| 破坏性错误 | 误删、错误合并、不可恢复对象、覆盖独有同名文件及当前引用破坏的各项数量 | 任一独有/冻结证据不可恢复即失败；按授权移除旧路径不是错误 |
| 增量维护范围与成本 | 直接变化、受影响依赖、实际重读/重写对象数及时间/Token | 漏检影响和无关重写都记录；哈希变化不是科学结论自动翻转 |
| 文件压减 | 各类文件、全部子目录、字节的同口径前后数量；研究包成员另计 | 不能只展示 Markdown 或根目录数，也不能为减少数量丢证据 |

分母为零写 N/A，不默认为满分。单个混杂目录只能揭示特定失败，不能估计一般错误率。工程回归要求关键完整性与边界错误为零；模型/Agent 方法优劣需报告原始逐题结果、失败原因、重复运行和未测条件，不能只给综合分数。

## 接续问题与独立审查

评价者至少检查这些事实关系，而不只核对关键词：

- 当前有效均值是什么，先前数值为何被更正；依据对应哪几个种子、代码版本、输入和参数？
- 哪个扩展已经完成但没有通过，哪个运行只是输入缺失未完成？不能把两者都称为方法失败。
- 有限阳性支持什么，为什么不能推广到供体泛化或独立确认？
- 两份同名结果是否真重复，各自独有事实在哪里？
- 结论依赖的数据被修改后，哪些报告需要重审，哪个无关主题应复用？
- 哪些方法属于探索、哪些已验证、哪些是正式成果；没有晋升记录时不能凭目录名称晋升。

独立审查须对照具体事实、来源与覆盖，记录未解决差异；不以“另一个 Agent 说通过”作为保证。删除前确认恢复源真实可读、语义覆盖达到本次清理范围，并遵守已有授权；不要把基准协议变成对每个已授权动作重复请求人工确认。发现未获授权的不可恢复信息丢弃，才停下依赖该动作的部分。
