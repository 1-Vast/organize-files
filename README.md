# organize-files · 文件科学整理

供 Codex 按实际用途核查、维护和重构科研资料的 Skill。让结论对应正确证据，保留实验条件、更正与失败经验；深度整理时综合报告、迁移现行依赖，并按授权清理已完整替代的散件。

## 使用

给出目标路径、任务目标和保护范围。已有会话授权继续有效，检查任务不自动变成整理任务。

| 目标 | 示例请求 |
|---|---|
| 只读检查 | `使用 $organize-files 检查 D:/Project 的报告均值及其适用条件，只读回答问题。` |
| 局部维护 | `核对新增结果及受影响引用，只修复明确缺口；无实质变化不改写文件。` |
| 深度重构 | `整理 D:/Project，按研究问题综合零散报告；保留唯一证据，允许在覆盖、恢复及当前使用验证后清理旧散件。` |
| 评价 Skill | `在隔离副本中做同模型、同输入的配对评价，保留失败与修复成本。` |

例如，旧记录的 0.71 已被同一运行更正为 0.70123：现行报告保留准确数值、更正原因和来源身份；另一协议的低分仍有独立含义。环境错误导致运行未完成，也不能被写成科学方法无效。

维护先只读。没有具体事实、引用或当前使用缺口，就直接交付检查结论，不为本次检查追加 README、导航或永久收据。明确深度重构则不能因文件未变而跳过。

## 阅读入口

只加载当前任务所需内容；不要求逐份阅读参考文件。

| 需要 | 文档 |
|---|---|
| 任务分流、边界与交付 | [SKILL.md](SKILL.md) |
| 阅读深度、停止条件、证据复用 | [执行规则](references/task-execution.md) |
| 最小命令与工具适用条件 | [工具示例](references/tool-recipes.md) |
| 数值冲突、条件差异、证据纠错 | [内容判断](references/evidence-review.md) |
| 代码退役、报告生命周期、事实绑定 | [科研治理](references/research-governance.md) |
| 目录结构、命名规范与冗余清理 | [整齐与命名标准](references/tidy-standard.md) |
| 大型混杂目录、特殊资料或操作受阻 | [深度流程](references/deep-organization.md) · [场景规则](references/scenarios.md) · [故障处理](references/cleanup-troubleshooting.md) |
| 工程回归和独立 Agent 评价 | [质量基准](references/quality-benchmark.md) |
| 历史实践及版本变化 | [MAESTRO 案例](references/maestro-example.md) · [更新日志](CHANGELOG.md) |

## 安装

The repository is public. The following PowerShell example installs it in the default skills location and stops if the destination already exists to protect local changes:

```powershell
$skillRoot = if ($env:CODEX_HOME) {
    Join-Path $env:CODEX_HOME 'skills'
} else {
    Join-Path $env:USERPROFILE '.codex/skills'
}
$skillPath = Join-Path $skillRoot 'organize-files'
if (Test-Path -LiteralPath $skillPath) { throw '目标已存在，请先核对本地版本。' }
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
gh repo clone 1-Vast/organize-files $skillPath
```

在 Codex 重新加载 skills 后使用。其他 agent 也可从 `SKILL.md` 开始阅读，再按任务读取相关参考文件。

## 验收与限制

- 独有资料、原始／冻结证据及必要元数据须保全；凭据、未授权封存内容、环境与 Git 管理状态受保护。项目特有范围须显式声明，工具不能靠文件名识别全部语义。
- 删除前核对全文信息覆盖、完整哈希、现行依赖及外置恢复源。`organization_ops.py` 提供可恢复的逐文件操作，回滚拒绝覆盖后续修改；它不是跨文件原子事务或完整 NTFS 备份，也不绕过执行权限。
- 元数据相同不证明内容相同；哈希相同不证明结论正确；原文可恢复不证明报告已综合。知识接续、数值复核和实验复现分别验收，不能升级证据等级。
- 默认迁移现行消费者，不新增旧路径兼容层；未知外部依赖列为缺口。科研重构与物理清理分别交付，证据不足保留源件。

从仓库根运行 `python -m pytest tests -q`（Python 3.11+，pytest）。测试覆盖保护边界、恢复、冻结绑定、增量影响和报告生命周期，不能证明 Agent 在任意真实项目中都不遗漏事实。

2026-10-26 的首轮 30 次合成 Agent 任务中，首次整理耗时中位数下降约 8.3%，局部增量增加约 4.5%，实际 Token 未稳定下降。后加写入约束的两次检查通过，但不能与此前对照混算。完整协议、数据与局限见[首轮实测](references/agent-evaluation-2026-10-26.md)。

后续任务分流与文档精简的真实材料评价先后遇到两类额度错误，仍属待验证。另行预定的34次补充评价中6次首轮通过、3对可比，未证明稳定整体提速；完整调度、失败成本、计量修复和续跑问题见[部分评价记录](references/lean-evaluation-2026-10-26.md)。
