# 水月无尘_C4_skill说明：submission-auditor（提交包质检员）

> 一句话：**输入**一个挑战/作业的提交文件夹，**输出**一份"缺什么、命名错、空文件、缺章节、踩红旗"的质检报告 + 退出码，让你在点"提交"之前就把问题修掉。

---

## 解决什么问题

交挑战/作业时最常见的尴尬，不是内容写得不好，而是——

- 交上去才发现少了一个必需文件（比如忘了打包 `.skill`）；
- 文件名没按规范写（缺 `_C4_` 段），批改人不知道这是谁的；
- 某个文件是 0 字节（保存失败自己没发现）；
- SKILL.md 没写 YAML frontmatter，别人装了根本触发不了；
- demo 截图只有 5 KB，糊成一团；
- AI 日志一句话打发，被判定"一句话指令直接提交"；
- `.DS_Store` / `__pycache__` 混进了交付包。

这些问题**不需要判断力，只需要被检查到**。这个技能把它们全部自动化：一条命令，30 秒，出报告。

## 使用场景

- 每次交 C1~C7 挑战**之前**，跑一遍，心里有底再上传群；
- 助教/班长收作业前，批量扫一遍所有人的提交包，定位谁没交齐；
- 把它挂进 pre-commit 钩子或 CI，提交即检查（退出码 2 直接拦住）。

## 输入

| 项 | 必填 | 说明 |
|---|---|---|
| 提交文件夹路径 | ✅ | 例如 `./我的C4提交/` |
| `--challenge` | 可选 | 如 `C4`；不传则自动从文件名里猜 `_Cx_` |
| `--rubric` | 可选 | 自定义 rubric YAML；默认带 Elite20 C1~C7 规则 |
| `--md / --json` | 可选 | 把报告落盘成 Markdown / JSON |
| `--strict` | 可选 | 有 warning 也按失败退出（用于 CI） |

## 输出

1. 终端打印一份 Markdown 报告，顶部直接给结论：
   - ✅ **READY TO SUBMIT** —— 干净，交；
   - ⚠️ **SUBMIT WITH FIXES** —— 没致命问题，但有警告；
   - ❌ **DO NOT SUBMIT YET** —— 有缺件，别交。
2. 每个问题带 `[CODE]` + 一句"怎么修"。
3. **退出码**：`0`=干净，`1`=有警告，`2`=有致命问题，`3`=环境错（缺 PyYAML）。
4. 可选 JSON sidecar，给程序读。

## 使用步骤

```bash
# 0. 一次性准备（只做一次）
pip install pyyaml

# 1. 解压 .skill 包（它就是个 tar.gz）
tar -xzf 水月无尘_C4_submission-auditor.skill

# 2. 跑
python3 submission-auditor/scripts/submission_auditor.py ./我的C4提交 --challenge C4
```

就这两步。看到 ❌ 就按报告里的 💡 提示改，改完再跑，直到变 ✅。

## 真实案例（实测）

我拿一个**故意做坏**的文件夹测它：里面只放了一个 40 字节的 `张三_C4_skill说明.md`、一个没命名的 `教学说明.md`、一个 9 字节的假 `demo.png`、一个 `__pycache__/`。

输出：

```
Critical: 5 | Warnings: 10 | Info: 1
Verdict: ❌ DO NOT SUBMIT YET
🔴 MISSING *.skill（缺技能包）
🔴 MISSING *AI日志*（缺 AI 日志）
🔴 EMPTY_FILE × 3（三个必需文件都近空）
🟡 NAMING_OFF × 2（demo.png / 教学说明.md 缺 _C4_）
🟡 MISSING_SECTION × 7（skill说明 缺"解决什么问题/输入/输出/..."）
🟡 DEMO_TINY（demo.png 才 0 KB）
⚪ CRUFT（__pycache__ 不该交）
```

退出码 = 2。修完这些问题再跑，退出码变 0。

## 为什么它"被用得多"

- **频率高**：Elite20 每个人每交一个挑战前都会跑一次，一学期 7 个挑战 × 几十人 = 高频复用；
- **零门槛**：一条命令，不需要懂 Python；
- **可扩展**：rubric 是 YAML，你自己往 `challenges:` 里加一条新作业，脚本一行不改；
- **和现有示例互补**：wechat-doc-mapper 盘点群里的文件，skill-explainer 分析别人的 skill，本技能检查**你自己的提交能不能交**。
