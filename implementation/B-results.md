# Phase B 验收记录

2026-11-23 使用 Edge 无头浏览器、Vue 生产构建、隔离 PostgreSQL、Redis、真实 JEV 与 DeepSeek 执行 `verify_isolated.py B`。命令退出码为 0。

- 电商商品咨询返回洗衣机结果，原历史可以查看。切到家电后会话 ID 变化，切回电商后恢复原会话，无家电故障消息混入。
- 场景切换前后共用一条 WebSocket。主动关闭后浏览器重新连接，仅有一条处于打开状态，且可继续通过当前诊断卡反馈。
- 洗衣机 E3 选择本人设备后显示 W-DEMO.pdf 来源。推进到下一步后旧按钮禁用。打开维修预览后整页刷新，恢复同一会话和预览，明确确认后打开对应工单，列表显示该工单。当前消息 ID 无重复。

## 改动范围

| 文件 | 职责 |
| --- | --- |
| frontend/user-frontend/src/App.vue、api.js | 入口、归档和每个登录会话的唯一实时连接。 |
| frontend/user-frontend/src/ChatWorkspace.vue、chatFormat.js | 两个入口的消息、输入、操作、按会话加载及消息 ID 去重。以请求版本和组件生命周期过滤迟到响应。 |
| frontend/user-frontend/src/ApplianceCards.vue、删除 ApplianceService.vue | 家电卡片使用工作台提供的上下文与发送函数。预览按账号、会话和版本恢复，恢复时重新验证后端预览。 |
| customer-service/atguigu/app/router/chat.py、services/chat.py、services/realtime.py | 历史返回消息 ID 和场景，实时消息携带消息 ID，统一归档按账号读取。 |
| ecommerce-service/ecommerce_service/appliances.py | 增加预览读取，核验归属、有效期、保修快照及已建工单。 |
| ai-service/atguigu/agent/harness/middleware/scope.py | 记录实际向模型披露的工具名单。 |
| verify_isolated.py、verify_workspace.py | 隔离服务启动与 Edge 验收。 |

同次浏览器验收中，真实 `list_my_devices` 调用的 trace 为 `trace_79564cd5b12a43ea84265fdac35f0e5c`，工具调用 ID 为 `call_00_oP1KXg8q9L4UviR6G5im7427`，统一 ToolExecutor 记录成功，耗时 396 ms。设备选择后的说明书检索 trace 为 `trace_e543a59ba526421ab8682a6ff9c291fe`。各阶段工具范围见 A-stage-supplement.md。
## 后续回归

AI 6 项、客服 5 项、电商 7 项，共 18 项自动化测试通过。隔离环境的真实请求再次命中商品、订单、物流、售后工具，并通过 JEV 家电引导、同型号引用、保修、维修预览和本人维修工单查询。HTTP 验收通过明确确认、重复确认、冒烟转人工及客服接单、回复和结束。

OpenAI 兼容适配器通过离线 HTTP 契约测试，覆盖工具声明和返回解析。该测试未调用第二家真实供应商。浏览器重连测试验证用户端恢复，未联合打开管理端验证双端 WebSocket。
