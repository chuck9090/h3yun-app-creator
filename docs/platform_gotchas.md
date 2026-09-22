# 氚云 new-engine 平台坑位清单(实证记录,2026-09 料号项目)

改平台层(controls/newbuilder/dsl)前必读。全是线上样本逐字实证,别凭旧文档猜。

## 建表端点与认证
- 真实建表端点是控制台 `POST {base}/Console/SheetDesigner/OnAction`(x-www-form-urlencoded,`PostData=<JSON>`),header 带 `Authorization` + `EngineCode`;不是老的 `v1/formdesign/save`。
- LoadForm 回读的 `DesignModeContent` 是 **PascalCase**(`Options`/`ChildControls`/`NameSchema`);SaveForm 载荷 camelCase(`options`/`childControls`)。比对一律大小写不敏感。
- 表单编码 = appCode 前 7 位 + 32 hex,随机生成后注册在 registry.json;**重存必须复用编码**(换码 = 断关联引用)。
- **本工程不使用 OpenApi/业务数据接口**:建表/自动化/分组全部走个人身份授权通道
  (`Authorization` Bearer + `EngineCode`)。本方案不做表单记录(业务数据)的增删改查,
  故无数据导入/导出/查询能力(历史 OpenApi 实现与数据相关章节已移除)。

## SaveForm 载荷(controls.py/newbuilder.py 已固化)
- SchemaStr.Properties 每字段:`ControlKey` 用**新枚举**(FormTextBox=14、FormNumber=7、FormTextArea=13、FormDateTime=5、FormCheckbox=1、FormUser/Dept=26、Multi=27、FormQuery=50、MultiQuery=51);FormLayout.type 用**老枚举**(同 controls.py 常量)。
- 表单下拉/单选/复选:**存储并回显所选文本本身**(不是 code/value 对)。料号拼接要代码 → 另建字典表 名称→代码 后端转换。
- 复选无默认值 = ""/null;下拉/单选默认 null;开关(是/否)存字符串 "true"/"false"。
- 必填/只读/默认值规则(DefaultValueRule)等 **UI 侧另存**,SaveForm 载荷无对应键 —— 重存会丢,所以 build 默认跳过已存在表单,`--force` 才整体重存。
- 成员/部门控件在 FormLayout 里 key 用 **uuid + DataFieldEditable=true**(11-14 类型);普通控件 key=字段编码。

## DisplayRule 显隐(唯一支持的"规则"通道)
- 控件 Options.DisplayRule = `{"Rule": "条件串"}`;Properties.DisplayRule = 纯字符串。
- 条件串语法:`{字段}=="值"`;**OR** 连接;多值不属于 = `AND {f}!="v"` 链。**语义:匹配即隐藏**,默认显示——"仅 A/B 显示"要写成 NOT∈{A,B} 链。
- 样本里 OR 分隔带 NBSP,生成/比对时规整为普通空格。
- UI 保存后引擎会复写规则文本(`!=` 加空格、追加 ` OR TRUE`),verify 会抓这类漂移——是 UI 痕迹不是 bug。
- 关联表单控件(FormQuery)与文本比较:**按记录显示名(NameSchema)的语义写的,未 100% 实证**;AND 关键字未实证(推导,料号表 4 在用)。新项目先在小表单试一条再铺开。

## 一行多列(fourCols)
- 行节点 = `{key: uuid, type: 102, parentKey: "", options: {Layout: "fourCols", PercentageBlock: "fourCols-1111", DisplayName: "一行多列"}, columns: [子项], childControls: [子项]}`;子项 parentKey=行 key,≤4 个。
- LoadForm 回读只有 `ChildControls` 没有 `columns`;HTML 里行 div `data-controlkey="layout_fourcols"`,列 div 数据属性 `data-layoutitem="Col1..4"`。

## NameSchema(表单数据标题)2026-09-10 实证
- **可拼接多个字段占位**:`{pname}{chgtype}` SaveForm 成功并保留。
- **不能夹字面量**:`{pname}-{chgtype}` 被拒,报 `表单数据标题中配置的字段不正确，请检查`(平台把占位之外的字面文本也当字段解析)。要分隔符就靠占位本身,别写 `-`/空格/斜杠。
- 失败时 SaveForm 返回 `{Successful:false, ErrorMessage:...}`,**不抛异常** —— 引擎建表逻辑的 `except` 分支捕获不到,只落 `err=""`、`detail=""`(本机日志看不出原因)。排障要手工重放 save_form_console 打印响应。

## 字段/表单编码不得占用保留字(平台自带编码 + MySQL 关键字,2026-09-22)
- **两类保留字**:①氚云平台自带编码(主表 ObjectId/Name/CreatedBy/OwnerId/OwnerDeptId/CreatedTime/
  ModifiedBy/ModifiedTime/WorkflowInstanceId/Status;子表 ParentObjectId/ParentPropertyName/ParentIndex;
  关联多选中间表 ValueIndex/PropertyValue;另 State、SeqNo);②**MySQL 保留关键字** —— 字段编码会成为
  `i_表单编码` 的**列名**,撞上会让 SQL 报表 / SQL 高级数据源失败:status/order/group/key/desc/rank/
  system/values/index/range…(完整列表见 `h3design/dsl.py` 的 `MYSQL_RESERVED`)。
- 大小写不敏感;换业务别名即可(status→billStatus、order→saleOrder、group→mgroup)。
- **编码只含字母数字**:任何符号(下划线/连字符/空格/点号/括号/斜杠/中文)都不允许;含符号的编码由
  `clean_design` 自动驼峰化(`客户-档案`→`customerFile`、`plan_begin`→`planBegin`),**不丢表**;
  但含路径分隔符 `/ \` 或 `..` 的 key 属**危险键,直接剔除**(安全边界,不尝试修复)。
- **校验范围**:字段编码、**子表列编码**、**表单 key(主表编码)**、**子表 key** —— 四者都会成为
  数据库列名/表名,一律校验。生成侧 `h3service.design.clean_design` 对撞字编码自动改名(加
  `Field`/`Form` 后缀)并同步重映射 `assoc` 与自动化 `form`/`target`;`h3design.dsl._check_reserved`
  在 build 侧兜底拦截。
- **已建表例外**:`registry.json` 里 `created: true` 的表,其字段/子表列编码**原样保留**(线上列
  已固定,改名=另起一列、丢数据);`clean_design` 与 build 侧都放过。**未建表**时才拦/改名。

## 系统拥有者字段(申请人/申请部门)
- 用户界面把申请改成系统字段后实证:FormLayout type 203(OwnerId)/204(OwnerDeptId),Options.ControlKey 仍 `FormUser`/`FormDepartment`;**不进 Properties**;OwnerId 带 `MappingControls: '{"ParentId":"OwnerDeptId"}'`。DSL 里用 `useOwner` + layout 引用(见 dsl.owner_presets,Options 逐字对照线上)。
- v1 SchemaStr controlType = FormOwner/FormOwnerDepartment(dataType 26),SaveForm 通道不需显式给。

## 布局项与新控件(2026-09-11 类型试验表 D001599e98… UI 保存载荷逐字)
- **类型号(FormLayout.type,老枚举)**:地址 9 / 位置 10 / 附件 15 / 图片 16 / 分组标题 101 / 一行多列 102 / 描述 103 / 子表 104 / 流水号 201。**Properties.ControlKey(新枚举)**:流水号 14(与下拉同码)、图片 23、附件 24、位置 55、地址 56;分组标题/描述**根本不进 Properties**(布局项不是字段,FormLayout 里 key 是 uuid、无 DataField)。
- **键集比普通控件窄**:流水号无 `DisplayRule`/`ComputationRule`(且 **FormLayout options 里就没有 DisplayRule 键**);图片/附件/地址无 `ComputationRule`;位置无 `ComputationRule`/`LocationRangeLimit`(其余四类都保留 `LocationRangeLimit:null`);地址多 `AreaMode`、`DefaultValue` 是 **JSON 串**;流水号/图片/附件/位置 `DefaultValue` 是空串 `""`(普通文本框也是 ""，下拉类才是 null)。
- **第三段 `ControlSettingsStr`**(与 SchemaStr/BizSheetStr 并列的**独立顶层段**):只有位置控件落这里 ——
  `[{"key":"F0000024","dataField":"F0000024","options":{"LocationPCEnabled":"true","Meters":"500","LocationEditable":"false"}}]`,值全字符串、compact JSON。这三个键在 FormLayout 和 Properties 里**都没有**;不发这段 → 位置控件按默认值建。
- **LoadForm 回读的 ControlSettings 是 PascalCase**(`Key`/`DataField`/`Options`),而 SaveForm 收的是小写 `key`/`dataField`/`options` —— 与 DesignModeContent/其它段同款大小写差异;verify 用大小写不敏感取值兜住。
- LoadForm **不返回** `EnableSeqNo`/`SeqNoDateFormat`/`SeqNoPrefix`/`SeqNoLength`(返回 null)——流水号表单级设置改了也**回读不出来**,只能看控件 options 与 `SeqNoStructure`(这个回读有)。所以 verify 不比这组键。
- **JSON 值进 HTML 属性只做实体转义,不留反斜杠**:线上 `data-seqnostructure="[{&quot;Type&quot;:1,…}]"`、
  `data-defaultvalue="{&quot;adcode&quot;…}"`。用 `json.dumps(s)[1:-1]`(newbuilder 的 `hq`/`_esc`)会把内部 `\"` 原样带出去,写出 `{\&quot;` —— 属性值里多出字面反斜杠。JSON 串一律用 `_escj`。
- **流水号运行态 HTML 的 `data-seqnostructure` 是设计器的 JS 拼串瑕疵** `"[object Object],[object Object]"`(设计态才是真 JSON)。运行态 HTML 只是渲染模板(结构以 FormLayout/Properties 为准),工厂照抄这串。
- 地址运行态那条 `data-defaultvalue` 线上**没有 `=` 两侧空格**(设计器单独拼串),其余属性都是 `data-x = "v"` 形态——工厂逐字照抄;这是唯一残留的空白差异(HTML 语义无影响)。
- 分组标题的删除按钮图标是 `icon-remove-block`、描述是 `icon-delete`;两者的**设计态** class 带 `row`、**运行态**去掉 `row`(线上如此)。

## 布局项的 key 必须是 GUID(2026-09-11 线上实证,工厂建试验表 D001599132f51bd09ee9c2613ac37e5ddcfc1f7)
- **短码当 key 会被平台吞掉**:SaveForm 用 `"key": "g_base"` 保存分组标题,回读 `Key=null`
  → 该布局项在设计树里整个消失,`verify` 报 `缺字段: ['g_base','d_note']`。换成
  `uuid5(固定命名空间, 短码)` 出的 GUID 后回读 `Key="5ad722f6-a176-598e-…"` 原样保留、PASS。
  (UI 每加一个布局项都发新 GUID;工厂用定值 uuid5 是为了 verify 能复算期望键。)
- **布局项是 FormLayout 顶层条目**(`ParentKey=""`、`DataField` 缺、`ChildControls: null`),不在
  102 行里。工厂把**单独一行"的布局项**照此输出(普通单控件行仍包 1 子项 102 行,不动既有表)。
- 同一张表的其余实证(与线上逐字一致):`ControlSettings` 按定义值落库
  `[{"Key":"loc_here","DataField":"loc_here","Options":{"LocationPCEnabled":"true","Meters":"300","LocationEditable":"true"}}]`
  (PascalCase 回读);行组 3/3 `[1,2,3]`;8 字段(6 字段控件 + 2 布局项)全数回读 —— 7 类新控件
  线上建表链路(DSL → 三段载荷 → SaveForm → LoadForm → verify)整条走通。
- **参数不写 = 平台默认**(2026-09-11 全默认版试验表线上 PASS,与 UI 拖入即默认一致):图片
  `UploadMultiple/CameraOnly/HasWatermark/Compression` 全 false、附件 `MaxUploadSize` 10、
  位置 `Meters 500` + PC 可用 + 不可编辑、地址 `AreaMode P-C-T` + `ShowDetailAddr true`、
  流水号 `YYYY` + 8 位。定义里只写 `type/key/label` 就能建出这些默认;流水号连 key 都能省
  (编码恒为 `SeqNo`,见 schema_doc)。
- **`--force` 曾经换码**(`code = None if force else rec.get("code")`):force 会新发一个
  表单编码,线上留一张孤儿表、断掉所有关联引用。已改成**编码一律复用**,force 只跳过"已存在即跳过"
  的短路(且仅管理员可用)。要真正重建新表:先删 registry 里该表的记录。

## 公式控件(2026-09-16 类型试验 UI 载荷逐字 + 工厂建表线上实证)
- **类型号**:FormLayout `type = 304`、`ControlKey = "FormFormula"`;但 **SchemaStr.Properties 的
  `ControlKey = 7`**(与数字控件同存储型)。参照载荷 = `fixtures/formula_ui_save_payload.json`
  (用户 UI 真保存 PostData,无凭据;离线比对脚本为开发期工具,结论已固化于引擎与本文)。
- **规则正文落两处、形态不同**:Properties 的 `ComputationRule` 是**纯文本**;FormLayout options /
  HTML 的 `ComputationRule` / `data-computationrule` 是 `{"Rule": 文本}` 字典。
- **Properties 键集是独立一套**:公共空键基础上 `IsFormula: true`,末尾追加
  `Referenceable: true` / `DataFormatType: ""`(数字控件是 `"0"`)/ `DecimalPlaces: 0` / `ShowMode: 0`,
  且**不带** `RollupSettings`/`ShowBarChart`/`PlaceHolder`/`DataLink*`(数字控件那套一个都不带)。
- **FormLayout 条目的 key 用 GUID** + `DataFieldEditable: true`(UI 样本 `bae5d897-…`),与布局项同理;
  工厂用 `uuid5(公式命名空间, 字段编码)` 定值。**线上实证:平台回读时把 key 归一成字段编码**
  (`fcalc`)——GUID 只是送进去时的形态,回读侧稳定为编码,verify 无漂移。
- **公式控件是"顶层条目"**:`ParentKey=""`、不在 102 行里;工厂把公式行按此输出,并**禁止**进一行多列。
- **HTML 里有逐字样本**,所以这段走 `_rule_attr_exact`(compact JSON + `_escj` 实体转义,不留反斜杠),
  不用 `_rule_attr`(那是 `hq`,非空规则会写出 `\&quot;`;线上容忍、已建表都这么发,**不动**)。
  公式的 `data-datetimemode` 在 HTML 里是 `yyyy-mm-dd hh:ii`,FormLayout 里是 `yyyy-mm-dd hh:mm`——照抄。
- **线上端到端实证(2026-09-16,工厂建试验表 `D001599ed15b4dd2235137a58e60a0fdaa0eb18`)**:定义
  `trial10`(数字甲/数字乙 + 公式 `{numa}+{numb}-{numa}*{numb}/{numa}+({numa}+{numb})`)→ build →
  LoadForm 回读 `type=304`、`ComputationRule` 逐字保留;写入测试数据后回读 **`fcalc=14`**
  (= `6+2-6*2/6+(6+2)`)。**公式是真算的**,链路可下生产。
- 顺带实证:UI 样本里被公式引用的两个数字控件在 FormLayout 里是 GUID key + `DataFieldEditable:true`,
  但那是"UI 新加控件"的形态,不是公式的要求——工厂发的**短码 key**(`type=4`、无 GUID)一样被平台
  接受、回读正常(`numa`/`numb` 原样)。
- LoadForm 顶层有个 **`RollupSettingsMap`**(汇总配置的回读面),无汇总时为 `{}` —— 做**汇总控件**时
  从这里对期望值。

## 设计态/运行态 HTML 是装饰,结构以 FormLayout + Properties 为准(2026-09-11 复核)
- 佐证:奥驰 table4 的 **38 条隐藏规则全部挂在 FormDropDownList 上**,而现有生成器下拉分支的
  `data-displayrule` 一直写的是空规则常量(规则文本没进 HTML)——线上表照样按规则隐藏。
  另有 `style="width: 100%%;"` 这类字面 `%%`(字符串没走 `%` 格式化)也照样能用。
  → **改 HTML 生成只会影响与 UI 样本的逐字一致性,不影响表单行为**;别为了"修 HTML"去动已上线表的生成路径。
- 新控件(流水号/图片/附件/位置/地址)的 HTML 已按 UI 样本逐字生成 + 离线比对(设计态 7/7 一致,
  运行态仅剩地址那条属性前的空格差异)。**参照载荷**:`fixtures/types7_ui_save_payload.json`
  (UI 真保存 PostData,无凭据;离线比对脚本为开发期工具,结论已固化于引擎与本文)。

## 项目缺 config.json 会静默回落到运行目录 config —— 落到**另一个应用**(2026-09-11 踩坑)
- `cfg_for(proj)` 的项目级 config 不存在时回落运行目录 `data/config.json`。该配置指向哪个应用是**会变的**
  (调试期临时指到试验应用、事后又改回业务应用),于是同一个 `data/projects/<名>/` 隔天 `build`
  可能整批建到别的应用里。
- 症状有迷惑性:SaveForm 返回 **`ParentInvalid:父对象必须为OU或公司`**,看着像认证/组织问题,
  实际是 `ParentCode`(那个应用的 appCode)对不上目标应用。**401 反而是好事**(token 过期,一眼能认)。
- 判据:表编码前 7 位 = appCode 前 7 位,两个应用**同前缀时看不出来**。稳妥做法——
  `data/projects/<名>/config.json` 一律自己放一份,别依赖运行目录配置。
- 反向坑:**改 config 前先确认它没被别的项目复用**;多个项目共用同一 appCode/凭据时,
  `build` 会把表建到那个应用里,别误以为建在了运行目录配置的应用。
- **Web 工作台已强制禁止回落运行目录 config**(`h3service.engine.resolve_config(allow_root=False)`),
  每个项目凭据加密存库、单独使用,从根本上避免误建到别的应用。

## 自动化(触发器)载荷与线上行为(2026-09-16 实测)

改 `h3design/automation.py` / `autodsl.py` 前必读。全部来自用户 UI 抓的 6 份真实 SaveTrigger 载荷 + 线上建表回读 + 真数据 E2E。

- **另一个端点**:自动化走 `POST {base}/Automatic/OnAction`(`PostData=<JSON>`),与建表那套 `Console/SheetDesigner/OnAction` **并列但不同**;认证头同款(`Authorization` + `EngineCode`)。保存用 `SaveTrigger`、回读用 `LoadTriggers`(传表单编码 → `ReturnData.Triggers`)。
- **触发时机 `ExcuteType`**:数据生效时 `111` / 数据失效时 `113` / 数据生效或者更新时 `114`。平台的定时触发、按钮触发、日期字段触发 DSL **未开放**(没有样本)。触发条件在 `Condition.Expression`,是 **DNF**:外层数组 = 或、内层 = 且。
- **动作插件 `PluginCode`**:新增 `insertdata` / 更新 `updatedata` / 删除 `removedata`;`PluginAction` 永远是**同名单元素数组**(`["insertdata"]`)。动作挂 `Trigger.Action[]`,写目标子表时**只能嵌一层**(外层定位/新建父记录,内层写子表行,见 `ChildrenTriggerAction`)。
- **`DataSetType` 必须按插件/作用域分档**(踩过,症状是删除动作**静默不生效**):
  | 动作 | DataSetType |
  |---|---|
  | insertdata / updatedata | `1` |
  | removedata 删**主表记录** | `2` |
  | removedata 删**子表行**(动作 SourceId 是子表编码) | `4` |
  删除动作写 `1` 平台**不报错也不执行**,目标行原样留着。6 份样本 + 线上在跑的自动化一致。
- **两种条件形态别混**:触发条件 `Condition.Expression` 与动作 `RequestMapping.ParentCondition` 是 **`{Id, PropertyName, Operator, ValueType, Value}`,无 `SubOperator`**;写子表时外层动作的 `ParentConditionV2` **没有 `Id`、有 `SubOperator: null`**。服务端回读会给 Expression 条件补 `SubOperator: null`(归一化噪音,比对忽略)。
- **别名约定**:`RelatedSchemaCodeAliases = [{"Alias": "<码>@1", "SchemaCode": "<码>"}]`。源字段串 `<源别名>.<字段码>`;源侧子表列 `<主表别名>.<子表别名>.<列码>`;目标主表字段裸码;目标子表列 `<子表码>.<列码>`。`RelationSchemaCodeAlias` 每条 = `[主别名, 子别名(无子表则同主别名), 表单名]`,**目标表那条主别名写两次**(子表别名不进这里)。
- **`SourceId` 判定**:动作读到触发表的**子表列** → SourceId = 那个子表编码(按子表行触发);否则 = 触发表主表编码。
- **键集细节**:顶层叶子动作 `ChildrenTriggerAction: []`,**嵌套**叶子是 `null`;`FinishStartActivity` 只在**顶层**动作有;`GroupByPropertyMappings` **只有删除动作是 false**,其余 true。
- **服务端会归一化**:界面新建时发的是精简键集(`Operation:"isAdd"`,见 `fixtures/automation_删除时.json`),平台照收;工厂发的是规范全量。回读比对**必须按语义比**(`h3verify/autoverify.py`:忽略 ObjectId/SortKey/Operation/Modified*/DisplayName/Code,字段映射与别名表按**集合**比,空值形态 None/[]/{} 互认),逐字节比没有意义。
- **ObjectId 用 uuid5 定值**(`automation.trigger_object_id` / `action_object_id`):重复 autobuild 是**更新同一条**,不会越建越多;`Operation` 由工厂自己按"线上有没有这个 ObjectId"选 `isAdd`/`isUpdate`。
- **平台没有删除触发器的接口**:定义里删掉 `automations/*.json`,线上那条仍在,**只能界面删**。
- **`useOwner: true` 时 layout 必须显式引用 `"OwnerId"`/`"OwnerDeptId"`**,否则表单少这两个字段(实测 6 != 8)。

## 环境
- Windows 控制台 GBK:`python -X utf8` 全命令前缀;报告文件 UTF-8。
- 请求间 sleep 0.3-0.5s;表单保存后回读前 sleep 0.5s(一致性)。
- 接口响应统一 `{Successful, ErrorMessage/ErrorCode, ReturnData}`;LoadForm 查不到表时 ErrorCode 含 "isnull"。

## 表单分组(v1/functionnode,2026-09-09 线上实证)
- 建组 `POST {base}/v1/functionnode`,body `{appCode, parentCode(=appCode 即顶层), displayName, nodeType: 230, icon: ""}` → 响应 **`{id: GUID, code: 32位hex}`**。分组码是裸 32hex,**不是**表单那种 `appCode前7位+hex` 格式。
- 改名/落定 `POST v1/functionnode/update`:create 全字段 + `code` + `objectId` + `summary:""`。UI 建组是两步(先 create 默认名再 update 真名),客户端照抄两步最稳;update 的 `objectId` 就是 create 响应里的 `id`(同一个 GUID)。
- 归组 `PUT v1/functionnode/sort`,body `{code: 表单编码, parentCode: 分组码}`;表单置回顶层 = `parentCode: appCode`。**请求只发 code+parentCode**,组内先后 = 移动顺序(拖拽排序参数未抓到)。
- 认证同 SaveForm 通道:`Authorization`(Bearer)+ `EngineCode` 头即可,无 cookie;三接口均返回 `True` 或简单对象。成功与否看 HTTP 无 4xx/5xx + 非错误 JSON。
- **没有分组读列表/删除接口**(GET list/tree、DELETE/POST delete 探测均 405 或 HTML 错误页)——分组码只能持久化在 registry `_groups` 段;多余分组只能在界面删。因此:工厂认不出界面手工建的同名组(会再建一个),别手工和工厂抢建同名组。
- 分组属应用菜单层,不进表单设计树 —— `verify` 不查分组;分组信息改动不触发表单重存。

## 联动下拉(选项来源=表单数据,2026-09-09 类型试验 实证)
- 下拉框原生支持"选项来自另一张表 + 级联过滤",字段仍是 FormDropDownList(ControlKey 14),只是 DataSource 从 `Custom` 切到 `Association`。
- **三处落点键集(权威:类型试验 F0000021 SaveForm 载荷逐字)**:
  - Properties(ControlKey 14 + 标准空键集):`AssociationSchemaCode` = 源表编码、`MappingField` = 存值列、`AssociationFilter` = **纯文本**(不带 Rule 包壳);**无** DataSource/BOSchemaCode/BOSchemaInfo/AssociationFields 键;
  - FormLayout type-7 options:`DataSource="Association"` + `BOSchemaCode` + `BOSchemaInfo`(JSON串:AppPackage/AppGroup/AppMenu=源表码/IsChildSchema) + `MappingField` + `AssociationFilter={"Rule":文本}` + `AssociationFields`(JSON串 {"isDefault":true,"fieldSetting":[]}) + `MappingControls=""`/`MappingProperties="{}"`;DefaultItems/ItemColors 残留占位项(UI 改型不清,见下);
  - 设计 HTML:`data-datasource="Association"` + `data-boschemacode=..` `data-boschemainfo="{&quot;..&quot;}"` `data-mappingfield=..` `data-associationfilter="{&quot;Rule&quot;:&quot;..\&quot;..&quot;}"`(双层转义,同 DisplayRule 的 _rule_attr 生成法)+ `data-mappingcontrols=""` `data-associationfields=..`。
  - JSON 串一律 compact(无空格):`{"isDefault":true,"fieldSetting":[]}` 这种,带空格会跟样本逐字漂移。
- `MappingField` = **存值列**:选中记录后把源行该列文本存入本字段(试验存 code 列;想保持老口径可存 name 列——存值是选列不是锁死)。
- `AssociationFilter` 规则:右值裸写本表单字段编码做动态引用,**级联就靠它**(切上级 → 选项池按条件实时过滤)。
- 切 Association 后 Properties `OptionalValues`/FormLayout `DefaultItems` 残留创建时占位选项(选项1/2/3)——UI 不清空;**工厂直建不带**(OptionalValues=""/DefaultItems=[],干净)——引擎对残留的取舍未单独观察,**大类别为空时的选项池表现仍待确认**。
- **h3yun-app-creator DSL 已支持(同日落)**:sheets JSON dropdown 声明 `assoc/assocField/filter`(细则见 schema_doc「联动下拉」章节),构建自动落三处 + verify 规整比对;filter 只开放 `=`/`contains` 实证集合,radio/checkbox_list/子表列内 assoc 直接报错。
- **实证进展(同日晚第二轮)**:AND 连接多条件成立;checkbox_list 多值列(分号串)的"包含"匹配用函数式 `CONTAINS({源表.字段},{本表控件})`,第二参数同样支持动态控件引用;一条规则可同时引用多个本表控件。UI 会在 Rule 文本里插 NBSP、给 `==`/`!=` 两侧加空格(与 DisplayRule 同款漂移,生成/比对先规整)。
- **运行实证(同日,类型试验 运行时)**:过滤条件 `dictcategory=="特性代码" AND CONTAINS(applyto,{大类别下拉})` **运行时真实生效**——切 磁性材料 下拉出 4 条、电子料 出 13 条,与字典表行数一致;常量等值 / AND / CONTAINS + 动态引用全部按预期对源表执行。机制可下生产(料号申请表的大类别→特性代码/品类级联直接照此形态配)。
- **未实证(剩 2 项,非阻塞)**:①存值口径——MappingField=code 是否真存 code 文本(需实际保存一条记录才能钉死,本方案不做数据写入,列此存疑);②重开记录回显(显示列 vs 存值列)。
- **语义坑**:奥驰字典表里 分类列 存的是「特性代码/品类/大类别…」,大类别在 适用类别 列(44 行特性代码为单值、品类 11 行为多值)——探测轮用的 `dictcategory=={大类别}` 映射不到真实结构;正确形态应为 `dictcategory=="特性代码" AND CONTAINS(applyto,{已选大类别})`。
