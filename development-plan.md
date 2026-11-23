# 两天开发计划 · 待独立评审

两天按 16 个工作小时估算，需求、此次设计、评审、编码及验收共同占用。下表是总预算，不从设计完成时重新计两天。产品负责人确认技术评审意见后开始编码。路径相对「电商小二」；同名 atguigu 包按服务分别修改。

| 总周期 | 预算 | 工作与主要文件范围 | 结束条件 |
|---|---:|---|---|
| Day 1 · 需求与评审 | 2h | 根目录 PRD、Architecture、Spec、数据库、开发与测试文档；折算前序已用时间。 | 评审确认接口、数据边界、验收目标。 |
| Day 1 · 基线与样例 | 1h | 核对三 FastAPI 服务、前端登录和现有消息往返；customer-service/atguigu/infrastucture/redis.py 与 common/settings.py 改为读取测试连接配置。准备隔离 PostgreSQL、DEMO 数据与两份定版 PDF。 | 无生产数据访问；本人订单可查，基线故障与外部依赖单独记录。 |
| Day 1 · 业务纵向切片 | 3h | ecommerce-service/ecommerce_service 的 models.py、schemas.py、seed.py、main.py；新增维修路由/服务与业务库增量 SQL。先设备/保修，后预览/确认/查单。 | 用两个用户从 HTTP 验证 AC-01、04～08 核心路径，验证唯一索引。 |
| Day 1 · 知识纵向切片 | 2h | ai-service/atguigu/app 的 models/models.py、routers/admin.py、services/knowledge.py 及 AI 库增量 SQL；补充两份 DEMO PDF 导入样例。 | 实际提取切片，同码不同义、无匹配及引用通过 AC-02。 |
| Day 2 · Agent 与状态 | 2h | ai-service/atguigu/agent 下的 harness/{tools,rules,run,validator}、llm/{prompt,output}.py，app/schemas.py 与 infrastructure/client.py；customer-service 的 app/services/chat.py、app/workers/ai.py、app/models/models.py 及客服库增量 SQL。 | 正常聊天入口可选设备、查证据、逐步反馈、打开预览；插话时旧结果不覆盖。 |
| Day 2 · 人工与界面 | 3h | customer-service/atguigu/app 的 services/{chat,admin,realtime}.py、router/admin.py；frontend 下用户端与管理端各自的 src/App.vue、src/api.js。复用现有详情、列表、上传与消息渲染。 | 用户端可确认并查询，客服端可看完整交接；「正在冒烟」绕过模型。 |
| Day 2 · 集成、修复、验收 | 3h | 三服务中对应功能的定向测试、DEMO 固定样例，两套前端构建和浏览器验收。 | 留存 AC-01～09 证据、修复和复验结果，产品负责人验收。 |

**依赖顺序。** 首先冻结设备、片段、Ticket 响应结构；业务 API 与知识检索可独立验证；随后接模型与会话；最后通过正常用户入口和客服入口验收。每段结束即执行对应测试，末段用于跨服务及现场演示。

**进度处理。** 若实际前序用时或环境恢复超预算，先压缩 UI 美化、额外演示文案和非必需样例，保持安全转接、证据校验、授权、唯一建单与现有验收标准。真实模型链路受外部服务影响时可先用固定响应定位问题，最终记录真实运行结果；剩余阻塞报告给产品负责人，不借用 Day 3～5。

两档方案都在客服服务 app/router/chat.py、app/schemas.py 与 app/services/chat.py 落实入口、会话归属和历史过滤；在 services/realtime.py 与双端消息处理接入会话 ID。核对当前活动会话、活动交接和领取轮次索引。源码收集轮次索引谓词使用 COLLECTING，枚举实际为 COLLECTION；迁移前检查重复收集轮次，按现有枚举修正谓词并在隔离库验证并发领取与插话。发现旧重复行时先停迁移，梳理关联消息再处理。

## 每天 6 小时的压缩方案

同一两天总周期的备选估算，前序设计和评审计入 Day 1。采用既有 Vue 页面、按钮和表格，直接展示五项工单信息及结构化交接；复用上传 API 导入两份固定 PDF。可省去独立工单详情页面、管理端新增上传控件、视觉润色、额外同义词和展示资料。工单详情 API、实际 PDF 导入、浏览器真实入口及全部 AC 仍须验收。

| 日期 | 时段（按工作小时） | 交付顺序与检查点 |
|---|---|---|
| Day 1 | 0～2 | 已用需求/设计/评审与隔离环境基线合并核算；先验证两个入口所需迁移和服务连通。 |
| Day 1 | 2～4.5 | 设备归属、数量一致、保修边界、预览替换、显式确认、重放与设备唯一约束。用真实 PostgreSQL 验证写入。 |
| Day 1 | 4.5～6 | 固定 PDF 切片、标签匹配、型号过滤及证据校验；验证同码异义与无匹配。 |
| Day 2 | 0～2 | 接入双场景、Worker 版本校验、售后技能与已有聊天页面；验证普通电商回归。 |
| Day 2 | 2～4 | 接通逐步反馈、预览与查询；完成冒烟自动转接、人工交接上下文及客服详情。 |
| Day 2 | 4～6 | 运行 AC-01～09 与本轮补充用例，完成真实模型联调、双端构建、复验和产品验收。 |

前序实际耗时与环境准备是压缩方案的可行性条件；若剩余时间不足以通过核心验收，报告缺口，核心能力继续作为交付门槛。

变更记录 · v0.2（2026-11-21）：保留两天 16 小时基线，增加两天各 6 小时方案、入口改动范围和迁移检查点。
