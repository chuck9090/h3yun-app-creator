# 本项目待完成功能

## 一、早期需求（已完成，保留备查）

> 状态：以下 6 项均已完成（2026-09-20），保留原文备查。

1. [已完成] 登录页不需要让用户填显示名称，这样应该是用户登录完成后，自己去设置自己的用户名，及上传自己的头像，未上传自定义头像前，都显示默认头像；

2. [已完成] 系统管理员可以操作添加用户进来，操作模式：新增用户->填写邮箱->完成。此时该用户密码为空，首次登录需要他通过邮箱去设置一个密码，密码在数据库需要用加密存储（用目前常用的登录管理系统的加密方式，不应存储密码原文，以及被反解密）；（注：经确认改为首次登录直接设置密码，未接入邮件服务）

3. [已完成] 普通用户不允许添加用户，只可以把自己创建的项目共享给其他用户，别人共享给自己的项目，自己不能再共享给其他人；

4. [已完成] 目前用户可以在页面看到所有阶段，并且可以任意点选跳过阶段，这是不合理的，在上一阶段内容生成完成前，后续阶段应该都要灰色，并且不允许点击，用户点击时还要提醒应该先完成xx（注：这里xx标识阶段名称）阶段；

5. [已完成] 页面上“流程图”要改为“业务流程图”，否则用户会误认为是氚云的审批流程图；

6. [已完成] 生成的业务流程图、ER图，没有全屏展示功能，包括编辑时也需要全屏展示才好；

---

## 二、复核发现待修复（2026-09-21）

> 更新（2026-09-22）：F1–F15 已全部处理完毕（F15 原为待确认项，本次按「业务流程图也参考参考资料」接入实现）。


> 来源：对「资料库 + 参考资料上下文链路 + 细粒度进度」改动的只读代码复核。
> 逐项含 位置 / 现象 / 触发 / 影响 / 建议。**请按编号逐项安排修复。**

### 高危

- [x] **F1. 资料库正文绕过 token 预算，可撑爆上下文**
  - 位置：`backend/app/api/pipeline.py:93-108`（`_reference_material`）、`:165-166` 与 `:261-262`（`blocks = [library_text, ref_text]` 拼接）；`backend/app/services/library.py:32-37`（`library_context` 无上限）
  - 现象：勾选的资料库资料（名称 + 描述 + `analysis`）无长度上限，与受预算约束的项目文档 `ref_text` 直接拼接。
  - 触发：项目勾选多份共享资料，或单份 `analysis` 很长。
  - 影响：`reference_text` 可远超 `CTX_TOKEN_BUDGET(120k)` → 模型请求超长/被拒、费用激增；绕过 `context.py` 全部预算设计。
  - 建议：把资料库资料也纳入 `context` 预算体系（计量 → 超限截断或并入 catalog 模式）；至少加单份/总量上限。

- [x] **F2. `_truncate_tokens` 中文换算错误，实际超预算约 60%**
  - 位置：`backend/app/services/context.py:239-244`
  - 现象：`keep = max(200, int(token_budget * 1.6))` 用字符数近似 token，但 `estimate_tokens`（`:26-31`）对中文按 1 字≈1 token。
  - 实测：纯中文 `share=500 → 805 token (1.61×)`；`share=2000 → 3205 (1.60×)`；`601 字 → 606 token` 且**截了等于没截**（`kept_full=True`，却仍加「已截断」标注）。
  - 触发：truncated 模式下任何中文/中英混排文件超预算。
  - 影响：truncated 档整体可达 1.6× 预算，「预算」失效；并出现不实标注。
  - 建议：改为按 token 累积截断（逐段 `estimate_tokens`），去掉 1.6 系数与「假截断」。

### 中危

- [x] **F3. 删除资料后 `library.md` 不刷新，已删内容仍喂给模型**
  - 位置：`backend/app/api/library.py:131-144`（`delete_item` 未触发重编译）；`backend/app/services/library.py:40-44`（文档承诺「删除即清空」）
  - 现象：删除只清上传件 + 删库；而 `backend/app/services/plan.py:63` 的 `_knowledge_digest` 读 `data/knowledge/library.md`，仅夜间/手动刷新时重建。
  - 触发：删除资料后、下次夜间或手动 `POST /api/knowledge/refresh` 前生成方案/ER。
  - 影响：已删资料的完整 analysis 仍进入 system 上下文（数据外泄/误导），与文档不符。
  - 建议：删除/新建/上传后触发一次 `render_library_digest()`，或在生成前按当前 DB 现算。

- [x] **F4. 夜间整理把未入模的文档也标 `learned`，导致永久跳过**
  - 位置：`backend/app/services/nightly.py:45-48`（超 `_MAX_TOTAL_CHARS` 即 `break`）、`:84-85`（`nightly_learn` 对全量 pending 标 learned）、`:115-116`（`analyze_library_item` 同理）
  - 触发：一份资料下文档正文合计超过 `_MAX_TOTAL_CHARS=40000`。
  - 影响：被 `break` 排除的文档从未进 LLM 却被标 `learned`；后续 pending 判定认为「无新文档」→ **静默永久丢失**。
  - 建议：只给真正编入 `blocks` 的文档标 `learned`；或记录未处理 id 下次优先。

- [x] **F5. PDF 内嵌图 + 扫描件整页各按 limit 计数，最多 2×**
  - 位置：`backend/app/services/extract.py:208-224`（内嵌循环用 `len(images) >= limit`）、`:226-245`（扫描件 `range(min(len(doc), PDF_OCR_MAX_PAGES, limit))` 未扣减已有数量）
  - 触发：PDF 既有可提取图片、文字量又 `< PDF_OCR_MIN_CHARS(40)`。
  - 影响：默认最多 6+6=12 次视觉调用，费用/时延翻倍。
  - 建议：扫描件循环用 `remaining = limit - len(images)` 约束。

### 低危

- [x] **F6. 内嵌图片 MIME 硬编码 `image/png`**
  - 位置：`backend/app/services/extract.py:144, 220, 237`
  - 现象：实测 xlsx 内嵌 JPEG（`im.format == "jpeg"`，魔数 `ffd8ffe0`）被包成 `data:image/png`。
  - 影响：严格校验 MIME 的视觉 API 可能失败/降质。
  - 建议：按 `im.format` / `part.content_type` / 扩展名映射真实 MIME。

- [x] **F7. DOCX 仅取 `inline_shapes`，浮动（锚定）图片静默漏掉**
  - 位置：`backend/app/services/extract.py:171`
  - 影响：这类图片既不识别也无 note（连「检测到图片」提示都没有）。
  - 建议：补充浮动图片扫描（`document.element.body` 遍历 `a:blip`）。

- [x] **F8. 角色门槛不一致：viewer 可建/传/删资料，却无法「立即整理」**
  - 位置：`backend/app/api/library.py:87`（create）、`:148`（upload）、`:131`（delete）用 `require_user`；`:189`（analyze）用 `require_editor`；前端 `frontend/src/pages/Library.tsx` 对所有 `canManage` 者显示该按钮。
  - 影响：viewer 创建的资料点「立即整理」必得 403。
  - 建议：统一为 `require_editor`，或放宽 analyze 权限。

- [x] **F9. 前端 accept 与后端白名单不一致**
  - 位置：前端 `frontend/src/pages/Library.tsx:313, 360`、`frontend/src/components/RequirementStep.tsx:227`（含 `.doc/.xls`）vs 后端 `backend/app/api/documents.py:22-23`（不含 `.doc/.xls`，但含 `.log/.yaml/.yml`）
  - 影响：选到 `.doc/.xls` 必报 400；后端支持的类型前端选不到。
  - 建议：双向对齐。

- [x] **F10. 文档字段名与代码不一致**
  - 位置：`docs/ARCHITECTURE.md:76` 写 `ref_docs`，实际列为 `projects.ref_items`（`backend/app/main.py:52-56`）。
  - 建议：更正文档。

- [x] **F11. 配置陷阱：`CTX_CATALOG_THRESHOLD < CTX_TOKEN_BUDGET` 时阈值失效**
  - 位置：`backend/app/services/context.py:190, 201, 206`（`total <= max(budget, threshold)`）
  - 影响：运维把阈值调小于预算时，`truncated` 档不可达，直接进 catalog，与预期不符。
  - 建议：文档注明 `threshold >= budget`，或启动时校验/取 `max`。

- [x] **F12. 抽取缓存不随「事后启用视觉模型」失效**
  - 位置：`backend/app/services/context.py:39-58`（`get_or_extract` 有 `extract_json` 即复用）
  - 影响：先未配视觉 → 缓存里是「需配置视觉模型」的 note；事后配好视觉也不会重识别。
  - 建议：缓存键纳入视觉开关/版本，或提供清缓存入口。

- [x] **F13. catalog 模式单件超预算仍纳入**
  - 位置：`backend/app/services/context.py:313-315`（`if spent + cost > budget and used:`，首件 `used` 为空 → 不 break）
  - 影响：目录模式单份可超预算（有界约 1.6×budget，随 F2 修复后收敛）。
  - 建议：单件仍超预算时截得更短，而非直接纳入。

### 测试缺口

- [x] **F14. 本次改动无自动化测试，需补最小回归**
  - 现状：`backend/tests` 对 `extract / context / vision / library / nightly` 零覆盖；smoke 仅新增 1 条「进度含百分比」断言（`backend/tests/smoke_real_server.py:140-142`）。
  - 建议补：
    1. `estimate_tokens`：空/纯中文/ASCII/混排边界；
    2. `_truncate_tokens`：中文下 `after_tokens <= share`（当前必失败 → 验证 F2）；
    3. `build_reference` 三档边界（含 `threshold < budget`，F11）；
    4. `resolve_catalog`：无 provider 回退取前 N、首件超预算（F13）、返回不存在文件名、两轮去重；
    5. `extract`：xlsx 表头+样例、`_data` 字节链路与 JPEG MIME（F6）、DOCX 内嵌图失败走 note、PDF 内嵌+扫描件合计不超 limit（F5）、`status=ok` 时图片 note 仍进 notes；
    6. `nightly`：新文档触发重算并覆盖、超 `_MAX_TOTAL_CHARS` 只标实际入模文档（F4）；
    7. `library` API：重名 409、权限 403、删除清文件顺序、删除后 `library.md` 刷新（F3）；
    8. `pipeline._reference_material`：勾选多份大 analysis 时总上下文受预算约束（F1）。

### 待确认（非缺陷）

- [x] **F15.（待确认）业务流程图生成未使用参考资料**
  - 位置：`backend/app/api/pipeline.py:207-219`（flowchart runner 仅加了 pct，未接入 `_reference_material`）。
  - 说明：若期望流程图也参考上传资料/资料库，则属遗漏；否则维持现状。
