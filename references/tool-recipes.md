# 日常工具示例

仅在任务需要对应能力时读本节；命令从 Skill 根目录执行，示例项目/临时路径须替换。只读局部问题通常直接检索和读取更便宜，不要求先盘点、建索引或运行所有工具。

## 显式文件操作

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

## 已有证据索引

有跨文件证据依赖且需要持续维护时才使用；不为一次检查建库。最小结构如下，同一份 JSON 可保留其他业务字段：

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
# 需要快照时只调用snapshot并检查errors/verification_complete；不保存快照时才改用validate
python scripts/evidence_index.py snapshot --index D:/Research/INDEX.json --root D:/Research --out D:/temporary/before.json
# 只筛选候选，不读取来源payload；所有对象仍未验证
python scripts/evidence_index.py scan --index D:/Research/INDEX.json --root D:/Research --previous D:/temporary/before.json --out D:/temporary/candidates.json
# 在实际新增/修改发生后重新生成 after 快照
python scripts/evidence_index.py snapshot --index D:/Research/INDEX.json --root D:/Research --out D:/temporary/after.json
python scripts/evidence_index.py impact --before D:/temporary/before.json --after D:/temporary/after.json
```

`direct_changes` 是严格快照的实际变化；`invalid_objects` 包含当前仍缺失或哈希错误的对象，即使两次快照相同也进入 `review_required`。`reusable_objects` 只说明此索引中严格校验后的结构未变、无绑定错误且无未验证来源依赖；保护来源及其依赖保持 `unverified_objects`，不列入可复用。`impact` 拒绝metadata scan输入。

`scan` 比较size、mtime/ctime和文件身份等元数据，返回candidate_sources/changed_sources/needs_strict_verification；旧快照缺元数据时作为需严格复核候选。即使元数据一致，内容仍可能变更，全部对象继续未验证，不能拿scan替代删除前哈希或冻结证据认证。validate/snapshot保留完整哈希及读取前后状态检查。metrics仅统计来源payload读取/哈希和显式stat，不包括索引JSON读取、路径检查、操作系统缓存和Agent阅读开销。

## 元数据盘点

跨目录重构或需要完整变化候选时，先读入口与存储政策，明确 `--opaque` 后盘点一次；本轮无目录变化就复用结果。范围明确的只读检查无需新建快照。示例快照必须在项目外，包含文件元数据及必要排除范围，不能上传原始会话日志：

```powershell
python scripts/workspace_scout.py --root D:/Research --opaque data/raw --opaque data/external --opaque tmp --snapshot-out C:/temporary/before.json
# 一次遍历同时保存after及全部变化；输出均在项目外且互不覆盖
python scripts/workspace_scout.py --root D:/Research --opaque data/raw --opaque data/external --opaque tmp --previous C:/temporary/before.json --snapshot-out C:/temporary/after.json --changes-out C:/temporary/changes.json
```

第二次仍遍历未排除目录，变化报告只用于挑选候选。`entry_stat_calls` 是目录项stat接口调用次数，未等价于底层磁盘I/O；`source_payload_files_opened=0`仅针对盘点。默认保护不能识别项目所有语义，必须先显式排除数据/包/环境；快照大小写按平台规则处理，不能借父级链接写回项目内。

默认stdout只保留`change_preview`及每类`change_preview_truncated`，截断不是变化范围。API调用`delta(..., include_changes=True)`取得完整`change_paths`，或读取`--changes-out`中的`changes`；仅含baseline/added/metadata_changed/missing，不把未变全量路径再次送入上下文。敏感文件、目录和链接均仅计数，不记录敏感相对名。

## 同进程来源复用（可选）

单次读取或没有重复来源时，普通文件读取更便宜；不要为了调用 API 新建事实库。确需在同一进程中重复使用同一来源时，下面一次调用读取两段，返回来源哈希、行号和读取计数：

```powershell
@'
import json, sys
sys.path.insert(0, 'scripts')
from task_context import TaskContext
context = TaskContext('D:/Research', opaque=('data/raw', 'sealed'))
result = context.batch([
    {'source_id': 'reports/result.md', 'start_line': 1, 'end_line': 10},
    {'source_id': 'reports/result.md', 'start_line': 11, 'end_line': 20},
])
print(json.dumps(result, ensure_ascii=False))
'@ | python -
```

检查 `complete`、每项状态及实际 `start_line/end_line`；文件尾部不足会截断，不能因 `complete=true` 就假定请求行数齐全。超限、受保护等缺项不能当成功。片段和缓存命中不代表结论已审阅。每次新启动 Python 都是新缓存，`fresh=True` 重读并检查失效；需要保存经审阅的事实与报告绑定时，再读[TaskContext API 与证据闭包](task-execution.md#证据闭包与紧凑输出)，正常复用输出用 `context.result(key, compact=True)`。工具不自动提取事实，也不替代删除前完整哈希、覆盖与恢复验证。

## 重要报告与导航

已有重要结论需要结构化绑定时，`claim_coverage.py` 的 `audit_claims` 是 Python API，并非一条 CLI 即完成科学核查；输入与审阅绑定见[事实级覆盖门控](research-governance.md#事实级覆盖门控)。普通局部核查可直接核对来源与报告，不为调用接口制造字段。

已有研究索引的链接或正文变更时，按[导航一致性](research-governance.md#索引导航一致性轻量检查)使用 `research_navigation.py`；路径存在不等于对应正确研究。历史来源 ID 须通过已审查读取器核验，不能仅凭旧哈希宣称可复用。
