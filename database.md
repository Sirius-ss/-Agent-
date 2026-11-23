# 数据库设计 · 独立评审稿

以下是相对于现有 SQLAlchemy 模型的增量。三服务分别维护自己的表；同服务内使用外键，服务间使用不透明 ID。新业务 ID 使用带类型前缀的随机 UUID 字符串。日期为 DATE，时间戳为 TIMESTAMPTZ，前端按 Asia/Shanghai 展示。除注明可空外，新字段均必填。

## ecommerce-service

| 新表 | 字段与约束 |
|---|---|
| appliance_models | model_code 文本主键，product_id 唯一外键 → products，display_name，warranty_months 正整数，demo 布尔。演示型号 W-DEMO 与 A-DEMO 的期限分别为 12、24。 |
| appliances | device_id 主键，order_item_id 外键 → order_items，unit_no 正整数，serial_no 全局唯一，signed_on 可空；唯一 (order_item_id,unit_no)。从订单项的 product_id 关联型号；从 orders.user_id 推导归属。 |
| repair_previews | preview_id 主键，user_id 外键 → users，device_id 外键 → appliances，description 文本，warranty_snapshot JSONB，created_at，expires_at，invalidated_at 可空。快照含状态、期限、签收日、首个过保日和提示文案。 |
| repair_tickets | ticket_id 主键（展示编号），preview_id 唯一外键 → repair_previews，device_id 外键 → appliances，description 文本，created_at，status 固定 PENDING。对 device_id 建唯一部分索引 WHERE status='PENDING'。写入从已校验预览复制设备与描述。 |

读取设备、预览、工单时将登录主体限制放入查询谓词，订单项到订单的链路为设备归属依据。工单通过同链路过滤，无消费端 user_id 参数。按设备查询利用待受理唯一索引，按本人列表沿订单索引关联，创建时间和编号降序排序。

## customer-service

conversations 新增以下三列。handoffs 增加 context_snapshot JSONB，旧行默认空对象；沿用一会话仅一条 WAITING 或 ACTIVE 交接的部分唯一索引。

| 列 | 默认与约束 | 用途 |
|---|---|---|
| service_scene | 文本，非空，默认 ECOMMERCE，仅允许 ECOMMERCE、APPLIANCE_SERVICE | 创建时由服务端路由赋值，之后固定。旧行回填 ECOMMERCE。 |
| service_context | JSONB 非空，默认空对象 | 当前售后业务状态的权威来源；按会话行加锁更新完整 JSON 对象。 |
| context_version | BIGINT 非空，默认 0，非负 | 每次有效状态提交递增一次。版本只存此列，Worker 在领取轮次时读取。 |

将 uq_open_conversation_per_user 替换为 (user_id,service_scene) 上的部分唯一索引，谓词为 mode IN ('AI','QUEUED','HUMAN')。同一用户可以分别接续两类会话，切换入口不打断人工接待。并发首次打开时唯一冲突回滚后重读同场景活动行。旧代码按用户查活动行，迁移需短暂停写，先回填并建新索引，再删除旧索引并部署场景感知的读写端，验证后恢复流量。已有双场景活动数据时回退须先停写并恢复迁移前快照。

- service_context 存 device_id、model_code、可显示序列号、fault_code、原始描述、当前片段 ID、待反馈步骤、步骤记录（步骤 ID、文案、结果）、risk。未知标量为 null，步骤记录初始为空；设备由订单工具输出校验。
- context_snapshot 固化交接当时以上已知字段、reason、当轮用户描述、已有工单摘要及查询结果（已查到／无记录／未确定设备／待重查）。详情接口可补充当前工单。Handoff.status、Conversations.mode 与 repair_tickets.status 分属各自业务。
- 沿用 messages.content 的 JSON 承载设备选择、反馈、引用和页面动作；会话超时新建后上下文从空开始。跨会话已有工单以业务服务查询为准。

## ai-service

在 knowledge_chunks 保留 id、file_name、content、created_at，新增可空 model_code、page_no（从 1 开始）、section、ordinal、fault_code、symptom_tags JSONB、user_steps JSONB。新型号片段要求有型号、页、章节、顺序、DEMO 文档名；无步骤用空数组。每个步骤包含片段内序号及原文。建索引 (model_code,fault_code)，并唯一约束 (model_code,file_name,page_no,ordinal)。旧平台政策行型号为空。运行数据继续使用 agent_traces、agent_tool_calls。

## 初始化与兼容

新增表通过业务服务的元数据初始化；对已存在的表使用各自服务的版本化增量 SQL，先添加可空列或带默认值列，再建约束和索引。create_all 不会给已有表补列。初始化前核对当前服务目标库，在隔离库先用旧结构与旧样例升级两次，第二次应无数据变化。旧订单、知识、历史及 AfterSale 无需破坏性重建。旧知识行不参与家电检索。

固定种子按自然键更新：为 DEMO 用户甲的一条数量为 2 的洗衣机订单项生成 unit_no 1、2，为空调生成独立订单项；另设乙的设备和甲缺签收日的设备。种子事务在提交前按每个参与演示的订单项核对设备数及 unit_no 集合 1..quantity，校验失败整体回滚。旧商品不自动生成来源不明的设备。说明书导入规则见 [Spec](spec.md)。

变更记录 · v0.2（2026-11-21）：确定场景列、按场景唯一的活动会话、独立版本列、迁移与种子一致性检查。
