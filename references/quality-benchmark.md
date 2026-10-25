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
  "operations": [{
    "op": "move", "source": "notes/result.md", "target": "reports/result.md",
    "sha256": "<64位小写SHA256>", "reason": "归入现行报告位置"
  }]
}
```

`remove` 不需 target，但必须增加 `evidence: {"coverage": "保留位置与逐项覆盖依据", "review": "审查记录"}`；`replace` 还需 `replacement` 和 `replacement_sha256`，指向工作根内预先准备的替代文件。声明不能取代实际审阅。每个计划按可独立核验的范围编制，不以一个巨型计划替代小批次。

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
# 在实际新增/修改发生后重新生成 after 快照
python scripts/evidence_index.py snapshot --index D:/Research/INDEX.json --root D:/Research --out D:/temporary/after.json
python scripts/evidence_index.py impact --before D:/temporary/before.json --after D:/temporary/after.json
```

`direct_changes` 是实际变化；`invalid_objects` 包含当前仍缺失或哈希错误的对象，即使两次快照相同也进入 `review_required`。`reusable_objects` 只说明此索引中结构未变且无当前绑定错误；保护来源仍在 `unverified_sources`，不能宣称已核验其内容。

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

## 指标及判定

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
