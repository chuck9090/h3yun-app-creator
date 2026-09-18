# 设计知识库(设计记忆)

把**用户自己过去建过的系统**编译成 AI 可检索的设计底座,让"粗需求 → 设计"时有旧账可查、
按同类系统惯例补齐没想到的表/字段/关系。

> **资料来源 = 用户上传/建立的资料,不含任何内置样本。**
> AI 出方案与表单结构时的参考有两块:
> ① **用户在本项目上传的文档**(已有系统/需求/会议等,直接作为上下文喂给模型);
> ② **本部署已建项目的语料**(下方知识库编译产物)。

## 代码与数据分离

| 内容 | 位置 | 性质 |
|---|---|---|
| 编译产物 | `data/knowledge/corpus.json` / `corpus.md` / `patterns.md` | 运行数据(可再生产) |
| 语料来源 | `data/projects/<名>/` 的 `sheets/*.json`、`dicts.json`、`automations/*.json` | 运行数据 |

运行数据目录默认 `<仓库根>/data`,可用 `H3F_DATA_DIR` 覆盖。

## 生成

- **自动**:Web 端建/改项目、或夜间批处理会触发重新编译(`engine_bridge.refresh_knowledge`)。
- **手动**:`POST /api/knowledge/refresh`(需 designer 及以上)。
- 编译结果完全来自 `data/projects/` 下用户的项目;无项目时保留现有产物(不会被空扫描清空)。

## 产物

| 文件 | 内容 | 谁用 |
|---|---|---|
| `data/knowledge/corpus.md` | 各项目每张表的字段/子表/关联/`uiNote` | AI 出方案时读 |
| `data/knowledge/patterns.md` | 跨项目共识:枚举字典 / 常见字段语义码 / 表关系图 / 自动化样例 | AI 出方案时读 |
| `data/knowledge/corpus.json` | 全量机器可读(启发式回退时读) | AI/工具 |

自动化定义格式见 `docs/schema_doc.md` 的「自动化」章节。
