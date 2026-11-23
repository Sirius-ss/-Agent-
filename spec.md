# 智能家电售后 Agent · 技术规格

评审基线为 [PRD v0.2](PRD.md)。实体与约束见 [数据库设计](database.md)。以下接口为拟实现契约。

## 1. 业务 API 与授权

业务服务路径前缀为 /api/v1。消费接口需有效 user JWT，user_id 只取令牌主体。未登录 401，角色不符 403，他人或不存在的资源统一 404。成功响应沿用现有 tool_result 的 success、code、message、data；前端按 HTTP 状态和 code 分流，错误文案可展示。

| 方法与路径 | 输入 | 成功结果 |
|---|---|---|
| GET /devices | 可选型号 model_code | 200，devices 数组，元素含 device_id、model_code、display_name、serial_no、order_id。零个显示核验入口；多台明确选择。 |
| GET /devices/{id}/warranty | 路径设备 | 200，device_id、status（IN_WARRANTY、EXPIRED、UNVERIFIED）、signed_on、months、exclusive_end、notice。未知日期返回 null。 |
| POST /repair-previews | device_id、description（去空白后 1～500 字）；修改已有预览时带 replaces_preview_id | 201，preview_id、设备摘要、故障描述、warranty、notice、expires_at；已存在待受理工单时 200 EXISTING_TICKET，附工单及人工入口。 |
| DELETE /repair-previews/{id} | 本人未确认预览 | 204，使旧预览失效；重复撤销仍 204。已成单返回 409 并附本人原工单号。 |
| POST /repair-previews/{id}/confirm | 明确点击按钮，正文 confirmed=true | 首次 201 CREATED；同预览重放 200 REPLAY，均返回同一 Ticket。另一预览已建单返回 200 EXISTING_TICKET 并显示已有工单和转人工。 |
| GET /repair-tickets | 可选 device_id（先校验归属） | 200，按时间倒序返回本人待受理 Ticket 数组。 |
| GET /repair-tickets/{id} | 本人工单号 | 200，单条 Ticket。 |

Ticket 统一字段为 ticket_id、device（device_id、model_code、display_name、serial_no）、description、created_at（带时区）、status=PENDING。页面显示「待受理」。422 表示输入无效或确认标志缺失。依赖不可用返回 503，查询错误不显示为零记录。

保修按上海本地业务日比较。签收日期加 N 个公历月得到 exclusive_end，目标月份无同号日取当月末日。today < exclusive_end 为在保；达到或超过边界为过保。缺签收日或数据异常（未来签收日）为待核验，提示分别说明缺失或需核验日期。过保及缺失的文案逐字采用 [PRD 第 6 节](PRD.md)。不生成金额。

## 2. 工单事务与页面

用户从聊天动作或本人设备页进入预览。动作仅能填入已验证 device_id 与用户原始描述，确认页展示后端快照。点击编辑进入本地草稿并隐藏确认按钮；取消编辑可返回原预览。保存修改仅调用一次 POST /repair-previews，携带 replaces_preview_id；DELETE 仅用于用户单独撤销。预览有效期 15 分钟。

替换在单个业务库事务内完成：按 device_id 排序锁定涉及的新旧设备，再锁旧预览；验证归属、旧预览仍有效且未成单、目标设备可报修，重新计算保修。插入新预览并标旧预览失效，一并提交。校验或写入失败全部回滚。目标设备已有工单则返回 EXISTING_TICKET，旧预览不变；旧预览已确认则 409 并返回原单。竞争确认与替换按相同锁顺序串行，旧预览只可能确认或被替换一次。客户端收到成功结果才展示新确认按钮。若提交响应丢失，重试遇旧预览失效时提示重新打开新预览并核对，禁止自动确认。

1. 预览创建时校验设备归属，读取待受理工单并计算保修快照。确认时在同一数据库事务以固定顺序锁定设备行、预览行，再次验证主体与关联设备。所有确认路径共用此锁顺序。
2. 先按 preview_id 查成功工单，存在即重放，即使预览已经过期。否则校验有效期、撤销标志及重算后的保修结果。失效、过期或政策结果变化返回 409 PREVIEW_STALE，要求重新查看并确认。
3. 查同设备待受理工单：存在则返回该单并标记 EXISTING_TICKET，否则从预览写入待受理工单并提交，提交成功才回报成功。数据库以 preview_id 唯一和待受理设备唯一双重兜底。唯一冲突回滚后按预览、设备顺序重新鉴权读取胜出的记录；其他异常返回失败。
4. 确认按钮可在请求期间禁用。网络超时保留同一 preview_id 供重试，页面不得生成新的提交身份。本人维修记录支持刷新和跳转详情。其他用户不能从冲突或重放响应获知编号。

## 3. 文档入库与相关片段检索

首版资料为可提取文字的两份 DEMO PDF。每份按固定章节编写，每个故障条目在单页内，以「故障码」「症状」「说明」「用户自查」标签和编号步骤划分，专业检修写在独立条目且无用户步骤。文档标题、型号印在正文中；测试数据含同码异义及无关条目。

症状标签由编写 DEMO 说明书的人维护在各条目单行字段，例如「症状：不排水｜桶内积水｜洗完还有积水」。导入器对字段和值执行 Unicode NFKC，按竖线分隔、去首尾空白、英文小写、稳定去重，保存为该片段的 symptom_tags。每条至少一个非空标签；字段缺失或解析为空时返回 422 并指出页与条目，保留上一版。查询文本使用相同规范化，再按下述子串计分。调整词表通过修订对应 PDF 后重新导入；标签不由模型推断，不增加向量数据库。

- 沿用 POST /api/v1/knowledge/upload（管理员、multipart file），新增可选 model_code。传型号时必须为两款 DEMO 型号之一，验证 PDF 声明型号与参数一致。按页提取、按章节/故障条目切片，每条只绑定本条步骤、症状标签与来源。空页跳过，空文档、缺少定位信息或无法解析的条目 422，事务内整体失败。相同型号和文件名在一个事务内替换旧片段，失败保留旧版。相同输入重复导入数量一致。无型号走现有平台知识入口。
- 家电检索仅接受服务端确认的型号。查询先在数据库 WHERE model_code 限定候选。抽取到故障码时规范大小写并精确匹配；指定码无命中直接空集，不退回其他码。无故障码时按标准化的症状标签子串匹配，按命中标签数降序，零分排除，同分按页码、顺序、ID 排序。最多返回 3 个片段。多个不同原因并列时询问区分症状，不混合步骤。
- 返回 chunk_id、model_code、DEMO 文件名、页码、章节、相关正文和允许的步骤。页面引用例为「DEMO 洗衣机说明书 · W-DEMO · 第 2 页 · E3」。NO_MATCH 返回空数组，先澄清或给人工入口。工具失败单独提示读取失败。对于只有两个型号的固定资料，采用可直接核验的标签与故障码检索，无需新增检索服务。
- 旧平台知识查询显式限定 model_code 为空；家电技能只暴露新检索工具。重导入导致旧步骤 ID 无法核对时，保留历史展示文本，重新检索并提示重新核对当前步骤。

## 4. Agent、会话与输出校验

保留现有 create_agent、技能裁剪、AgentTrace、工具执行器及 JWT 传递。入口、会话和内部路由遵循同一契约：

| 调用 | 服务端行为 |
|---|---|
| 用户端「家电售后」→ POST /api/v1/chat/appliance/conversations，空正文 | 需 user JWT。customer-service 根据该固定路由确定 APPLIANCE_SERVICE，在本人同场景下创建或接续活动会话并返回 conversation_id、service_scene、conversation_mode（新建 201、接续 200）。 |
| POST /api/v1/chat/messages；GET /api/v1/chat/history | 家电页分别在正文、查询参数携带返回的 conversation_id。按本人和 ID 查消息与状态，他人 ID 返回 404；已关闭会话可查历史，发送返回 409 并由入口重开。未带 ID 的旧客户端仅在 ECOMMERCE 下沿用原有建会话、超时及历史查询。显式 ID 的过期 AI 会话先关闭再要求重开。客户端提交的 scene、skill 或消息正文均无权修改路由。 |
| Redis/WebSocket 与历史刷新 | 用户事件携带 conversation_id，以当前打开的 ID 过滤；旧格式无 ID 的事件仅触发按当前入口重取历史。普通聊天及其历史排除家电会话。 |
| Worker → POST /internal/v1/agent/runs | 领取时从数据库取 service_scene、service_context、context_version，连同 conversation_id、轮次消息快照和原有双重鉴权传递。ai-service 在调用 JEV 分类前分支；APPLIANCE_SERVICE 固定同名技能，继续执行工具和证据校验。用户请求人工由客服服务处理。ECOMMERCE 及旧内部调用缺省值沿用原 JEV，未知枚举值返回 422。 |

conversations.service_context 是当前业务状态的权威来源，messages.content 保存操作和消息记录，历史裁剪或重新加载不参与重建当前状态。每次有效变更（选设备、更正描述、提供或反馈步骤、风险标记、会话模式变化）在同一锁内将 context_version 加一；同一事务内多个字段变化算一次，纯读取、重复消息或无变化不加。Worker 领取时持有版本与消息快照；提交成功、重试或降级前均重新锁会话，比对场景、版本、mode 和最新用户消息 ID。过时则将轮次标为 SUPERSEDE，不提交其回复、上下文、事件或错误引起的交接；后续新轮次读取最新状态。

| 只读工具 | 输入来源 | 返回与边界 |
|---|---|---|
| list_my_devices | 用户令牌，可选型号 | 本人候选设备；多候选返回选择卡，单个可自动选定。 |
| get_device_warranty | 已验证的当前 device_id | 透传业务服务的保修结果及文案。 |
| search_manual | 用户故障码或症状；型号从当前设备取 | 相关片段、步骤及引用，或 NO_MATCH。 |
| list_my_repairs | 当前设备 ID 或本人全部 | 待受理工单五项信息。 |

运行上下文扩展为设备、轮次、步骤和场景。设备选择使用已存在的 POST /api/v1/chat/messages，保留 message_id，新增 type=device_choice 和 content.device_id；后端按令牌重查候选。步骤卡使用 type=step_feedback，携带 step_id 和 outcome（resolved、unresolved），普通文字反馈仍可解析，含义不清时只澄清。API 回复与 WebSocket 事件沿用原形状，在消息 content 增加可选 citations、step、choices、page_action。历史消息缺字段按文本渲染。

| 当前条件或输入 | 服务端状态变化与输出 |
|---|---|
| 无设备或多候选 | 保留原始描述、故障码；查询候选或人工核验。选择后核实归属，选错后允许更换。更换设备清空当前诊断进度、故障关联及旧页面动作，保留历史消息。 |
| 有已选设备且命中资料 | 仅展示该条目的一个用户步骤，记录待反馈的 step_id；收到未恢复才推进下一步。已恢复结束自查。需专业检修、步骤耗尽或直接要求维修时发 OPEN_REPAIR_PREVIEW。 |
| 用户插话、切人工、结束会话 | AI Worker 随 run 发送 context_version；finish_turn 持会话锁检查 mode、最新消息快照及版本，通过才一次提交回复、步骤变化、事件。旧轮次的成功与错误都丢弃。恢复 AI 后从已记录上下文继续，已完成步骤不自动重复。 |

模型输出是候选。家电专用校验在现有“仅知识工具即返回”分支之前执行：核实引用属于本次成功检索及当前型号，步骤只能取命中条目的用户步骤原文；保修、工单字段、预览按钮由后端成功工具结果构造。缺证据时使用资料不足或读取失败模板。禁止生成维修价格和确认成功消息。预览与确认均不注册为模型工具。

## 5. 自动转人工与接待

状态按[现有枚举](电商小二/customer-service/atguigu/app/models/enums.py)分别赋值，同一转换在同一事务提交：

| 动作 | Conversations.mode | Handoff.status |
|---|---|---|
| AI 会话开始 | AI | 尚无交接 |
| 请求人工、冒烟或失败降级 | AI → QUEUED | 新建 WAITING |
| 客服接单 | QUEUED → HUMAN | WAITING → ACTIVE |
| 客服结束接待 | HUMAN → AI | ACTIVE → RESOLVED |
| 排队中或人工中追加风险 | 分别保持 QUEUED 或 HUMAN | 分别复用 WAITING 或 ACTIVE |

CLOSED 属于会话模式；PENDING 属于维修工单。接单和结束只允许上表的起始组合；人工结束后保留已解决交接历史。

在家电场景的客服消息入库事务内，先处理当前用户明确陈述的「正在冒烟」。首版以当前肯定陈述为匹配条件，演示输入为「空调显示 E3，而且正在冒烟」；过滤否定和假设示例「没有正在冒烟」「如果正在冒烟怎么办」。不依赖模型判断、设备识别或业务服务在线。首次转接立即保存「请停止使用设备，已为您转接人工客服」、risk=SMOKE_ACTIVE、原始描述与已知故障码；已有排队或人工接待会话按上表追加风险并通知当前接待渠道。家电页「转人工」发 type=request_handoff，明确文本“转人工”同样在客服服务处理。普通电商沿用原流程，共用交接构造函数。

变更记录 · v0.2（2026-11-21）：补齐入口 API、可信场景分流、会话状态与版本校验、人工状态映射、PDF 标签提取契约和原子预览替换。

同事务写 Handoff、上下文快照、消息与实时事件。已有活动交接复用原 ID。设备未知时显示「设备未确认」；尚未执行步骤时显示空列表，待反馈步骤标注「未反馈」，不写成已执行。客服详情列出每个已反馈步骤及结果，risk 无标记显示「无已报告风险」。

扩展既有 GET /api/v1/handoffs/{id}/messages，加上 handoff_context，保留 messages。客服服务先验 staff 角色及交接可见范围，从 Handoff 取 user_id，从快照取 device_id，用现有服务端用户身份转发方式调用业务 GET /repair-tickets?device_id=…；成功时返回工单五项信息，可缓存至快照并标注查询时间。设备未定则标示未确定，读取异常标示「待重查」，重新打开详情可重试。禁止浏览器指定被查询的用户。排队列表显示接入所需摘要，活动交接的详情、回复、结束校验当前接单人；接单锁行，只接受 WAITING，结束恢复 AI。人工接待完成不改变维修工单状态。
