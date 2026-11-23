# A2 工具与业务验收

在新建的三个 PostgreSQL 数据库及隔离的后端进程中运行 verify_isolated.py A2，通过真实 JEV 与 DeepSeek 调用。以下 ID 来自该轮实际 ToolExecutor 记录。临时测试数据库已清理。

| 场景 | 真实业务工具 | trace ID | 工具耗时 |
| --- | --- | --- | --- |
| 洗衣机 E3 | search_manual | trace_7542f1b10e0e4ee8a42012c1ec096c7f | 13 ms |
| 空调 E3 | search_manual | trace_46337e49b1494e8eb67941538ee8e8be | 10 ms |
| 空调保修 | get_device_warranty | trace_49a1bee8987949ac986c3111ad589ab1 | 309 ms |
| 空调维修预览引导 | prepare_repair_preview | trace_e7b5d16b50044f64bf386b638995c564 | 620 ms |
| 本人工单 | list_my_repairs | trace_741f4a4be5834e28acd1c86b5111f8ef | 302 ms |

洗衣机和空调同码分别引用对应型号。模型通过 LangChain 工具调用读取证据，诊断卡从本轮成功记录与重新核对的说明书片段生成。四种家电查询前后，维修工单列表一致。真实用户确认、重复确认同单、冒烟交接和客服接单回复另通过 smoke_test.py 验证。两次未恢复各自增加一个状态版本；重新提交过期版本均返回 409。旧卡可按原片段 ID 读取同型号诊断计划，跨型号查询返回 404。

商品、订单、物流、售后四个基线输入均再次触发相应工具。一次订单查询在 list_orders 成功后还尝试了一次失败的 get_logistics；工具记录保留了该失败。不能据此承诺生成式回答的措辞或每次调用顺序完全相同。

AI 测试 5 项通过，包含无证据、错误型号和伪造片段拒绝。客服测试 5 项通过，电商测试 7 项通过；用户端生产构建通过。验证环境使用当前配置的 DeepSeek；另一种聊天适配器、浏览器工作台及 WebSocket 断线恢复属于 C 阶段。运行步骤见 README。
