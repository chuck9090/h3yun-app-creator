# fixtures/ —— 氚云载荷实证基准(开发资产)

本目录是**引擎逆向与生成的权威参照样本**:从氚云设计器 UI 真实操作中抓取的
SaveForm / SaveTrigger 原始载荷,逐字固化为"金标准"。
`h3design/controls.py`、`newbuilder.py`、`automation.py` 与 `h3verify/autoverify.py`
的生成逻辑**逐字对照**这些样本;改平台层前必读。

> **不是运行日志**。运行报告在 `data/projects/<项目>/logs/`(verify/autoverify/group)。
> 这些是**代码资产**,随仓库提交;删除会让生成逻辑失去可核对基准。

## 文件

| 文件 | 内容 |
|---|---|
| `types7_ui_save_payload.json` | 7 类新控件(流水号/图片/附件/位置/地址/分组标题/描述)UI 保存 PostData |
| `formula_ui_save_payload.json` | 公式控件(type 304)UI 保存载荷 |
| `child_ref_payload.json` | 子表(附件/图片列)列节点 UI 真样本 |
| `automation_*.json` | 6 份自动化(触发器)真实 SaveTrigger 载荷(新增/更新/删除、主表↔子表、条件) |
| `anchor_dsl/*.json` | 上述 6 份载荷的 DSL 复刻锚点(离线比对用) |

相关的线上实证记录见 `docs/platform_gotchas.md`;DSL 格式见 `docs/schema_doc.md`。
