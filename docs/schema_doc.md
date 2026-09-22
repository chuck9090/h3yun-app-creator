# 表单定义格式(sheets/*.json)

每个文件 = 一张表单,文件名即表单 key(registry 键、跨表 assoc 引用名)。

最小完整样例(`data/projects/<项目>/sheets/product.json`):

```json
{
  "title": "产品登记表",
  "nameSchema": "{pname}",
  "useOwner": true,
  "layout": "auto4",
  "group": "主数据",
  "controls": [
    { "type": "text", "key": "pcode", "label": "产品编码" },
    { "type": "text", "key": "pname", "label": "品名", "required": true },
    { "type": "dropdown", "key": "bigcat", "label": "大类别", "dict": "大类别" },
    { "type": "number", "key": "price", "label": "参考价", "decimal": 2 },
    { "type": "switch", "key": "enabled", "label": "启用", "checked": true },
    { "type": "dropdown", "key": "status", "label": "状态", "options": ["在制", "已停产"],
      "hideWhen": "{enabled}==\"false\"" },
    { "type": "subtable", "key": "specs", "label": "规格参数明细",
      "columns": [
        { "type": "text", "key": "param", "label": "参数名" },
        { "type": "number", "key": "val", "label": "数值", "decimal": 2 },
        { "type": "date", "key": "since", "label": "生效日期" }
      ] }
  ]
}
```

项目目录 = `config.json`(凭据) + `sheets/*.json`(表单) + `dicts.json`(枚举) + `groups.json`(分组清单,可选) + `automations/*.json`(自动化,可选) + `registry.json`(编码注册表,勿手改)。自动化定义见本文末尾「自动化」章节。

## 顶层键

```json
{
  "title": "产品登记表",                 // 显示名
  "nameSchema": "{pname}",               // 记录显示名模板,{} 包字段编码
  "useOwner": true,                      // 是否要系统拥有者字段(创建人/创建人部门)
  "layout": "auto4",                     // 见下方「布局」
  "controls": [ ... ]                    // 字段列表,顺序即定义顺序
}
```

## layout

| 写法 | 效果 |
|---|---|
| 省略 | 每控件一行(flat) |
| `"auto4"` | 每 4 个控件一行一行多列;`useOwner:true` 时首行 = [创建人, 创建部门] + 前 2 字段 |
| `[["k1","k2","k3","k4"], ["k5"], ...]` | 显式行:每行 1–4 个字段 key;owner 用字面量 `"OwnerId"`/`"OwnerDeptId"` |

一行多列控件最多 4 个。`useOwner:true` 时必须显式 layout(或 auto4),owner 不占 controls。
**布局项(分组标题/描述)只能单独成行**(`["g1"]`),写进一行多列直接报错——线上它们就是整行 div。

## 控件 type 一览

通用键(所有类型):`key`(编码,短语义码如 `pname`,已实证可持久化)、`label`(显示名)、`hideWhen`(隐藏条件串,见下)。`required`/`readonly` 可写但**只是定义里的标注**(SaveForm 不携带、界面另存),设计阶段不必考虑——见下「不用管的两件事」。

### key 命名规则

`key` **就是建出来的字段编码**(载荷里的 `DataField`/`Key`),表单 key、子表 key、子表列 key 同理。命名两条硬规则,`check`/`build` 报错拦下:

1. **只含英文字母 + 数字,必须字母开头,不得出现任何符号**(下划线/连字符/空格/点号/括号/斜杠/中文 都不行)。`plan_begin` ✗ → `planBegin` 或 `planbegin` ✓;`客户-档案` ✗ → `customerFile` ✓;`金额(元)` ✗ → `amount` ✓;`1ab` ✗;`a1b2` ✓。
   - 例外:**布局项**(分组标题/描述)的 key 不是字段编码(它的 `DataField` 是 GUID,短码只留在本地),随便起;**流水号**的编码恒为 `SeqNo`(key 可省),不受本条约束。
   - 含符号的编码由生成侧 `clean_design` **自动驼峰化**(不丢数据);**含路径分隔符 `/ \` 或 `..` 的 key 属危险键,直接剔除**。
2. **不能占用保留字** —— 分两类,`check`/`build` 一并拦:

**(a) 平台自带编码** —— 每张表单/子表**天生就有**这些列,撞上会出问题:

```
# 主表 i_表单编码
Name  SeqNo  CreatedTime  CreatedBy  ModifiedTime  ModifiedBy
OwnerId  OwnerDeptId  Status  State  ObjectId  WorkflowInstanceId
# 子表 i_子表控件编码
ParentObjectId  ParentPropertyName  ParentIndex
# 关联表单多选中间表
ValueIndex  PropertyValue
```

**(b) MySQL 保留关键字** —— 字段编码会成为数据库**列名**(`i_表单编码`),列名撞上它会让
SQL 报表 / SQL 高级数据源里的语句失败。常见:`status` `order` `group` `key` `desc` `rank`
`system` `values` `index` `range` `select` `from` `where` `char` `int` `float` `decimal`
`date` `time` `if` `in` `is` `and` `or` `not` `null` `left` `right` `join` …(完整列表见
`h3design/dsl.py` 的 `MYSQL_RESERVED`)。**换业务别名即可**:`status → billStatus`、
`order → saleOrder`、`group → mgroup`。大小写不敏感(`Status`/`STATUS` 同样被拦)。

> 生成侧的 `clean_design` 会自动把撞字的字段/表单 key 改名(加 `Field`/`Form` 后缀)并同步
> 重映射引用;但**提示词仍要求直接产出合规编码**,避免依赖自动改名。

- 申请人在 `layout` 里写 `"OwnerId"`、申请部门写 `"OwnerDeptId"`(配 `useOwner: true`),**不要**塞进 `controls`。
- `SeqNo` 只归**流水号控件**;普通控件名叫 `SeqNo` 会被拦。
- 其余几个由平台自动维护,定义里不出现。

> **已建表的例外**:表单线上建过之后(`registry.json` 里 `created: true`),字段编码在平台上就固定了,改 key = 另起一列、老列数据留在原处 —— 所以**规则 1、2 对这类表都放过**(`clean_design` 原样保留其编码,`check` 也不拦)。**未建表**的项目一律拦(`check`/`build` 报错),生成侧 `clean_design` 自动改名。

### 不用管的两件事

1. **可写/必填**:属于界面侧另存(重存还会丢),不在工厂职责内,设计时不用问、不用配。
2. **`.cs` 业务代码**:本平台不生成,客户**单独**要求时在氚云设计器里自行编写(类名必须 = 表单 SchemaCode)。

### 控件 type 表

| type | 额外键 | 说明 |
|---|---|---|
| `text` | `default`, `placeholder` | 单行文本 |
| `textarea` | `rows`(默认3), `default` | 多行文本 |
| `number` | `decimal`(小数位), `default` | 数字 |
| `date` | `datetime`(默认 `yyyy-MM-dd`) | 日期时间 |
| `switch` | `checked`(bool) | 开关(是/否) |
| `radio` | `dict` 或 `options`, `default` | 单选 |
| `dropdown` | `dict` 或 `options`, `default`, `hideWhen` | 下拉(**存储所选文本本身**);或 `assoc` 联动形态(选项来自另一张表,见「联动下拉」) |
| `checkbox_list` | `dict` 或 `options`, `defaults`(数组) | 复选,存储分号串 |
| `member` | `multi`(bool) | 人员单选/多选 |
| `department` | `multi`(bool) | 部门单选/多选 |
| `query` | `assoc`(另一个表单 key), `multi` | 关联表单控件;assoc 编码构建时从 registry 自动解析 |
| `seq_no` | `prefix`(默认空), `datetime`(默认 `YYYY`), `increment`(序号位数,默认 8);**`key` 可省(编码恒为 `SeqNo`)** | 流水号(type 201),平台按规则发号,**不能给 default/dict/options** |
| `image` | `multiple`, `cameraOnly`, `watermark`, `compression`(均 bool) | 图片(type 16),多选上传/仅拍照/水印/压缩 |
| `attachment` | `maxSize`(单附件上限 MB,默认 10) | 附件(type 15) |
| `location` | `meters`(定位精度默认 500), `pcEnabled`, `editable` | 位置(type 10);PC 端定位/是否可改由 ControlSettingsStr 承载 |
| `address` | `areaMode`(默认 `P-C-T`), `showDetail` | 地址(type 9);省-市-县三级 + 详细地址 |
| `formula` | `rule`(必填,公式正文), `decimal`(小数位,默认 0) | 公式控件(type 304),**只能单独成行**;见下节 |
| `group_title` | `label`(=标题文字), `align`(`left`/`center`/`right`) | **布局项**,不是字段 |
| `description` | `content`(HTML,缺省用 `<p>label</p>`), `title`(设计器显示名) | **布局项**,说明文字 |

`dict` = 引用 `dicts.json` 的分类名;`options` = 字面量数组。两者必有其一(单选/下拉/复选)。

`seq_no` / `image` / `attachment` / `location` / `address` 五类的载荷(FormLayout options 键、
Properties 键集、设计态/运行态 HTML、ControlSettingsStr)**逐字对照 UI 真实保存载荷**
(`fixtures/types7_ui_save_payload.json`,2026-09-11 类型试验表实测);`verify` 会回读比对位置控件的
ControlSettings(不符打印「位置设置不符」)。

`formula` 同理,逐字对照 `fixtures/formula_ui_save_payload.json`(2026-09-16 实测)且**线上跑通**
(公式真算出值);`verify` 会回读比对公式正文(不符打印「公式不符」)。

## 子表(明细表) — type `subtable`

整行占据表单底部,不参与一行多列打包。JSON:

```json
{ "type": "subtable", "key": "specs", "label": "规格参数明细", "fixed": 1,
  "columns": [
    { "type": "text", "key": "param", "label": "参数名" },
    { "type": "dropdown", "key": "unit", "label": "单位", "options": ["mm", "kg"] },
    { "type": "number", "key": "val", "label": "数值", "decimal": 2 }
  ] }
```

| 键 | 说明 |
|---|---|
| `key` / `label` | 子表编码引用名 / 显示名(不写 label 时界面即显示为 key) |
| `columns` | 列数组,列 spec 同普通控件(仅列内类型受限,见下) |
| `fixed` | 固定列数(默认 1;须配显隐与列宽等 UI 手工设置) |

- 列支持类型:**text / textarea / number / date / switch / radio / dropdown / checkbox_list / attachment / image**。成员/部门/关联/嵌套子表/位置/地址/流水号/布局项作列仍未开放,会直接报错(没有可照抄的实证样本)。
- **附件/图片列(2026-09-11 开放,线上实证待补)**:列节点走 `newbuilder.grid_layout_entry` 的 `col_entry`,它把主表同款 Options **原样搬运**、只改 `DataField` 为 `<子表码>.<列编码>`(这条约定来自 `fixtures/child_ref_payload.json` UI 真样本);而附件/图片的主表 Options 已逐字对齐 `fixtures/types7_ui_save_payload.json`。所以形状是"两个已实证样本拼起来的",**不是直接抓到的子表附件列 UI 样本** —— 上线前建议先在一张试验表单实测一次。
- 子表**编码自动注册**:registry 里 `reg[key]["subs"][子表key] = {"code": "<appCode前7位>F+32位hex"}`(40 位,平台子表编码规则,与主表单 39 位不同)。**首次建表前无需手工分配**——建表流程会自动预注册;只跑离线校验时编码为空属正常。
- 布局约束:`layout` 的显式行数组里**不要写子表 key**(报错提示)——子表永远自动排在主字段行之后。
- 子表 UI 侧能配、定义里没有的(列宽/移动端/编辑子表对话框选项)照旧走**界面手工配置清单**。

## 公式控件(type `formula`)

按别的字段自动算值、实时更新,填表人不能手改(平台把输入框置灰并提示)。2026-09-16 线上实证:
工厂建的表里公式**真会算** —— 建一行 `numa=6, numb=2`,回读 `fcalc=14`
(=`6+2-6*2/6+(6+2)`)。

```json
{ "type": "number", "key": "numa", "label": "数字甲" },
{ "type": "number", "key": "numb", "label": "数字乙" },
{ "type": "formula", "key": "fcalc", "label": "公式控件",
  "rule": "{numa}+{numb}-{numa}*{numb}/{numa}+({numa}+{numb})" }
```

| 键 | 说明 |
|---|---|
| `key` / `label` | 字段编码 / 显示名(公式本身仍是一个**字段**,占 Properties 一个条目) |
| `rule` | **必填**,公式正文。字段引用写花括号里的**字段编码**:`{numa}+{numb}`;加减乘除 `+ - * /` 与括号 `()` 照引擎语法 |
| `decimal` | 小数位(默认 0) |
| `bindType` | 结果类型,目前**只开放 `number`**(线上只实证过数字型公式,写别的直接报错) |
| `hideWhen` | 显隐条件,同其它控件 |

- **引用的字段必须是本表字段**(构建时校验,写错报「不是本表字段」并列出本表有哪些)。
  子表列、别的表的字段**引用不了**——引擎只认裸 `{字段编码}`,跨表/子表列的写法未实证。
  定义顺序上把被引用的字段写在前面(UI 也是这么干的)。
- **只能单独成行**:`layout` 里写成 `["fcalc"]`,不能进一行多列(线上样本的公式是 FormLayout
  顶层条目,进多列行未实证)。
- 公式字段**可以被别的公式引用**(Properties 侧 `Referenceable: true`)。
- 载荷三处(逐字对照 UI 真实保存载荷 `fixtures/formula_ui_save_payload.json`):
  ① `SchemaStr.Properties` 的 `ControlKey` 是 **7**(与数字控件同存储型)、`IsFormula: true`、
  `ComputationRule` 存**纯文本**公式;末尾多 `Referenceable/DataFormatType/DecimalPlaces/ShowMode`
  四键,且**不带**数字控件那套 `RollupSettings/ShowBarChart`;
  ② `FormLayout` 条目 `type: 304`、`ControlKey: "FormFormula"`、`ComputationRule` 是 `{"Rule": 文本}`、
  `BindType`/`DecimalPlaces`/`DateTimeMode`/`ShowMode`/`Referenceable`;
  ③ 设计态/运行态 HTML 的 `data-computationrule`(实体转义、不留反斜杠)。
- `verify` 会回读比对公式正文(空白规整后),不符打印「公式不符」。

## 布局项(分组标题 / 描述)

只占版面,**不是字段**:不进 `SchemaStr.Properties`、不进 NameSchema 可选字段、`verify` 按 key 单独比对。

```json
{ "type": "group_title", "key": "g1", "label": "基础信息", "align": "left" },
{ "type": "description", "key": "d1", "content": "<p>填表前请阅读…</p>" }
```

- 分组标题(FormGroupTitle,type 101)载荷里**连 ControlKey 都没有**,只有 `{DisplayName, Title, Alignment}`;
  描述(FormDescription,type 103)带 `ControlKey` + `Content`(富文本 HTML)+ `DisplayRule: {}`。
- 两者在 FormLayout 里的 key 是 **uuid**、没有 `DataField`——定义侧写的 `key` 只是引用名,工厂用
  `uuid5(固定命名空间, 定义 key)` 定值成 GUID(`controls.layout_key`),同一布局项每次构建同号,
  verify 才能复算期望键。**别拿短码当 key**:2026-09-11 线上实证,短码保存后平台把 key 吞成
  `null`,回读时该布局项整个消失、verify 报缺字段(详见 platform_gotchas)。
- 布局项在 FormLayout / HTML 里是**顶层条目**(线上样本 `parentKey=""`、不在 102 行里),工厂照此输出;
  普通"单独一行"的字段仍包 1 子项的 102 行(既有表就是这么建的,改了会让 verify 行组期望对不上)。
- 子表仍然永远排在最后;布局项可与字段混排在各行之间,顺序即定义/layout 顺序。

## 流水号(type `seq_no`)

```json
{ "type": "seq_no" }                                  // 全默认:编码 SeqNo、标题"流水号"、YYYY+8 位
{ "type": "seq_no", "datetime": "YYYYMM", "increment": 6 }
```

- **`key` 可省,编码固定就是 `SeqNo`**(平台/界面的惯例,别另起名);`label` 省了默认"流水号"。
  layout 行里引用的就是 `"SeqNo"`。一张表只能有一个(多个会因编码重复被拦)。
- 值是**表单级**设置(`SchemaStr`):`EnableSeqNo=true` / `SeqNoDateFormat` / `SeqNoPrefix` /
  `SeqNoLength`(= 前缀长 + 日期段长 + 序号位数) / `SeqNoStructure`(JSON 串
  `[{"Type":1,"Value":"YYYY"},{"Type":2,"IncreNum":8,"Value":"1"}]`)。工厂按控件**自动推导**,
  无需在顶层另写;`datetime: "YYYY"` + `increment: 8` → `SeqNoLength=12`。
- `datetime` 段长按字符串长度算:支持 `YYYY`/`YYYYMM`/`YYYYMMDD` 等(线上样本为 `YYYY`)。
- 控件本体 Options 另有 `Prefix`/`DateTimeMode`/`SeqNoStructure`/`IncrementNum`;**没有 `DisplayRule` 键**
  (线上如此,隐藏规则配不上)。
- `default`/`dict`/`options` 会被报错拦下——值由平台发。
- 序号位数用满后平台自动进位加宽,定义侧不用管。

## 位置 / 地址 / 图片 / 附件

- **位置(FormMap)**:`Meters`/`LocationPCEnabled`/`LocationEditable` 三个键**不在 FormLayout,也不在
  Properties**——走载荷顶层独立的第三段 `ControlSettingsStr`
  (`[{"key","dataField","options":{...}}]`,值全是字符串)。建表流程自动带上;
  改定义后 `verify` 会连这段一起回读比对。`data-locationrangelimit` 线上写死 `"undefined"`。
- **地址(FormAreaSelect)**:`Properties` 侧多一个 `AreaMode` 键,`DefaultValue` 是 **JSON 串**
  (`{"adcode":"","adname":"","Detail":""}`),不是普通文本;`areaMode` 目前只实证 `P-C-T`。
- **图片/附件**:`Properties` 里 `DefaultValue` 是空串、无 `ComputationRule` 键(与文本框不同);
  附件 `MaxUploadSize` 单位 MB。多附件/必填/只读、拍照/水印等由界面另存(见界面手工配置清单)。
- 这几类在 FormLayout options 里键集**比普通控件窄**(无 `PlaceHolder`/`DataLink*`),工厂按类型裁剪。

## 表单分组(应用菜单归类)

表多了把应用菜单按模块分组。**分组属于应用菜单层,不影响表单设计**:建表照旧,全部建完跑一条命令归组。

```json
// sheets/xxx.json 顶层加一行
{ "title": "产品登记表", "group": "主数据", "controls": [ ... ] }
```

- `group` = 归入分组的显示名,多表单可同组;表单定义时**不必**提前建组(group 命令会自动建)。
- 项目可选 `groups.json` —— 有序分组清单(顺序 = 应用菜单从上到下的创建顺序,也即最终展示顺序):

```json
[ "基础信息", { "name": "项目管理" }, "合同收支", "数据分析" ]
```

- **有 groups.json 时**,分组顺序以它为准(**顺序 = 应用菜单从上到下的创建与展示顺序**);
  **没有** groups.json 时按表单出现顺序归组(推荐大项目都建 groups.json)。
- **部署时自动归组**:`POST /api/projects/{id}/deploy` 在**建表后**按各表 `group` 建分组并把表移入:
  - 幂等:分组编码 + objectId 存 registry `_groups` 段;已有组跳过不重建,重复运行安全
  - 每次运行都会把声明的表**重新移回**所属分组(界面上被人拖走的会拉回来)
  - 平台**没有分组读列表/删除接口**(已实证),分组码只认 registry —— 手删 `_groups` 段后,组会以新码重建
  - 工厂认不出界面手工建的同名组(无读接口),会再建一个同名的 → 手工建过同名组就把界面上那个删掉,让工厂自建
  - Web 端在「ER 设计 → 分组」页可调整分组**顺序**、补充分组名;各表单的「分组」字段决定归属。

## dicts.json(枚举)

```json
{
  "申请类型": ["新料号", "升版", "变更"],                    // 简写:仅名称(显示即存储)
  "大类别": [ {"code": "SJ", "name": "塑胶件"},              // 全写:有代码(如料号中段要代码)
              {"code": "DZ", "name": "电子料", "enabled": false} ]  // enabled:false 跳过
}
```

数组顺序 = 下拉排序。代码为空的条目显示名即代码。

## hideWhen —— 显隐条件(DisplayRule)

语义:**条件匹配时隐藏**,默认显示。只支持这套语法(引擎实证,别写别的):

```
{字段编码}=="值"                等于 → 隐藏
{字段编码}!="a" AND {字段编码}!="b"     不属于集合 → 隐藏(多值 NOT∈S 用 AND != 链)
条件A OR 条件B                 任一满足 → 隐藏
```

已知边界:**关联表单控件与文本比较是否按显示名未最终实证**(奥驰 rulecfg 按记录显示名语义写的,新项目若遇异常先在界面试一条)。隐藏规则由界面另存/引擎复写后可能与定义漂移 —— 回读核对(verify)会抓出来。

## 跨表引用(assoc)

`query` 的 `assoc` 写目标表单 key(如 `"table1"`),构建时从 registry.json 取目标编码。**先建被引用表**。若用 legacy forms.py 定义,assoc 依赖 `table1`/`table4` 两个 key 在 registry 中存在(奥驰约定),新 JSON 项目则支持任意 key。

## 联动下拉(下拉选项来自另一张表 + 级联过滤)

下拉框原生支持把选项池接到另一张表单的数据上,并按别的字段值实时过滤 —— 级联下拉。**运行时已实证**(2026-09-09 类型试验:大类别→特性代码 切换过滤,出选项数与源表行数一致),可下生产。`assoc` 源表必须是同项目 registry 里已注册的表(编码在 build 时解析;跨项目的旧表如奥驰通用字典表,手工往 registry.json 补一条 `"字典key": {"code": "<线上编码>"}` 即可引用)。

```json
{ "type": "dropdown", "key": "proptype", "label": "特性代码",
  "assoc": "dictionary",                   // 选项来源表单 key(registry 已注册,先建被引用表)
  "assocField": "code",                    // 存值列 = 源表字段编码:选中后把源行该列文本存入本字段
  "filter": [                              // 级联过滤,AND 连接;可空 = 不过滤(整表选项)
    { "field": "dictcategory", "value": "特性代码" },   // 常量等值 → {源表.字段}=="特性代码"
    { "field": "applyto", "op": "contains", "ref": "bigcat" }  // → CONTAINS({源表.applyto},{bigcat})
  ] }
```

- `assoc` 与 `dict`/`options` **互斥**(选项来自表不是枚举);`default` 暂不支持(联动存值/回显语义未实证);`hideWhen` 照常可用。
- `assocField` **必填**(存 code 还是 name 由料号拼接口径定——存什么字段,库里就是那列文本)。
- `filter` 条目:`field` = 源表字段编码;`op` = `=`(缺省)或 `contains`,二选一搭配:
  - `=` + `value`(字符串常量,须带引号形态序列化)、`=` + `ref`(本表字段 key,动态引用,引擎按 ref 当前值实时过滤——**级联就靠它**);
  - `contains` + `ref`:源表该列是分号串多值(如 适用类别=电子料;磁性材料),按"包含"匹配。
  - 生成的规则文本:常量带双引号、`==` 无空格、条件间 ` AND ` 连接、源表引用带编码前缀 `{源表编码.字段}`、本表引用裸写 `{key}`。UI 重存会在规则里插 NBSP/给符号加空格——`verify` 自动规整比对,定义侧永远写干净文本。
- **受限**(未实证,`check` 直接报错):radio/checkbox_list 不支持 assoc;子表列内不支持;filter 只开放 `=`/`contains` 两 op;常量只能是字符串(数字列等值未实证)。
- 存值只有一列文本;要展示/换算另一列(如显示名↔代码),业务代码里按存值查一次源表。

## 自动化(automations/*.json)

表单上的**触发器**:某张表的数据生效/失效/更新时,自动往别的表增删改数据,可带触发条件。
一个文件一条自动化,文件名即 key。定义放 `data/projects/<名>/automations/`。

```json
{
  "title": "源表→目标表:主表字段回写(没有则新增)",
  "form": "atrg",                    // 触发表单:本项目表单 key,或直接写 schema 编码
  "trigger": "生效或更新",            // 生效 | 失效 | 生效或更新
  "sortKey": 1,                      // 可选;缺省按文件名排为该表单内第 1、2…条
  "names": {},                       // 可选:外部编码 → 显示名(别名表里的人话名)
  "when": [ {"field": "t3", "value": "GO"} ],        // 可选;触发条件
  "actions": [
    { "do": "新增",                  // 新增 | 更新 | 删除
      "target": "atgt",              // 目标表单
      "state": "生效",               // 写入后目标记录的状态:生效(缺省) | 发起流程
      "isInsert": true,              // 仅 do=更新:匹配不到就新增(缺省 true)
      "match": [ {"field": "g3", "ref": "$ObjectId"} ],   // 定位**目标**里的哪条
      "set":   [ {"to": "g1", "from": "t1"},              // 源字段 → 目标字段
                 {"to": "g3", "from": "$ObjectId"} ],
      "owner": true,                 // 可选,缺省 true:自动补拥有者两条映射
      "sub": {                       // 写**目标表的子表**
        "table": "sub2",
        "set": [ {"to": "d1", "from": "sub1.c1"},
                 {"to": "d2", "from": "sub1.c2"} ] } } ]
}
```

| 键 | 说明 |
|---|---|
| `form` | 触发表单。写本项目表单 key(推荐,字段会校验存在性),或直接写完整 schema 编码(外部表,字段不校验) |
| `trigger` | `生效`(数据生效时) / `失效`(数据失效时) / `生效或更新`(生效或者更新时)。**平台的定时/按钮/日期字段触发未开通**,写别的直接报错 |
| `sortKey` | 同一表单内多条自动化的执行顺序(界面上的排序号) |
| `when` | 触发条件,**只支持触发表的主表字段**。外层数组 = 或,内层 = 且;单组可省一层 |
| `names` | 外部表编码 → 显示名。别名表里要写"采购订单"这种人话名,而本项目表单自动取 `title`,外部表取不到就写这里 |

**字段引用写法**(`when.field` / `set.from` / `sub.set.from` / `match.ref` 用的都是这套):

| 要引用的东西 | 写法 |
|---|---|
| 触发表主表字段 | 裸 key,如 `t1` |
| 触发表子表列 | `子表key.列key`,如 `sub1.c1` |
| 系统字段 | `$ObjectId` / `$OwnerId` / `$OwnerDeptId`(子表行的写 `sub1.$ObjectId`) |
| 目标字段(`set.to` / `sub.set.to`) | 目标表主表字段写裸 key;目标子表列写进 `sub.set`,不带子表前缀 |

**actions 语义**:

- `do`:`新增` / `更新` / `删除`,分别对应平台的 insertdata / updatedata / removedata。
- `match`:定位**目标**里哪些记录,**`更新`和`删除`必填**(不写会全表更新/删除,直接报错拦下)。
  `field` 是**目标表**字段,`ref`/`value` 是**源**侧取值。
- `set`:源字段 → 目标字段的映射。`do=删除` 不能带 `set`/`sub`。
- `sub`:要写**目标表的子表**。平台是"外层动作定位/新建父记录 + 内层动作写子表行"两级结构,定义里写一层就行,工厂自动展开。
  - `sub.set` 里 `to` 是目标子表列,`from` 是源字段(可以来自**触发表的子表列**,即"子表行抄到子表行")。
  - **只写 `sub` 不写 `set`** = 外层只负责找到/新建父记录、不覆盖父记录字段(线上样本同款)。
- `owner`:写主表字段时自动补 `OwnerId`/`OwnerDeptId` 两条拥有者映射(源同名 → 目标同名),不带的话目标数据归属为空、**数据权限会丢**。只写子表(无 `set`)时不补。想要目标归属别人就给 `"owner": false` 后自己用 `set` 映射。

**执行方式(Web 平台)**:

- 离线校验:生成/保存表单结构时自动执行(引用表/字段存在性、枚举值),结果随接口返回。
- 建自动化:`POST /api/projects/{id}/deploy` 在**建表后自动建/更新**自动化(ObjectId 定值,重复跑=更新同一条)。
- 回读核对:`POST /api/projects/{id}/verify`(LoadTriggers 只读比对)。

- ObjectId 用 **uuid5 定值**(按 项目+key+动作路径 算),所以 **重复运行是更新同一条,不会越建越多**;线上是否已存在由工厂自己判断(`isAdd`/`isUpdate` 自动选)。
- `autoverify` 是按语义比的(不比 ObjectId/SortKey/Modified* 这些服务端字段,字段映射与别名表按**集合**比),因为平台对键集是归一化的、映射列表无序。
- **删掉一条自动化只能用界面** —— 平台没有删除触发器的接口。定义里删掉文件,线上那条还会留着。

**实证状态(2026-09-16)**:用户 UI 抓的 6 份真实载荷用本 DSL 复刻,**未知差异 0 条**;线上建 3 条回读比对 **ALL PASS**(自动化回读核对);真数据端到端 **ALL PASS**(覆盖 主表→主表 新增/更新、主表子表→目标子表、`when` 条件拦截、失效删除四种行为)。

## legacy 兼容

`data/projects/<名>/forms.py`(奥驰样式:`BUILDERS` 字典 + `build(key, app_code, rule_table_code=, apply_table_code=)` 返回 `{key,title,name_schema,fields,layout,assoc}`)会被自动加载并和 sheets/*.json 合并。新项目请用 JSON,forms.py 仅迁移用。
