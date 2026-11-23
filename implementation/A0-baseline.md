# A0 回归基线

Git 标签 `a0-pre-integration` 指向 `07549f9985831811e4ee00d9373fa1f8ae60f24c`。仓库仅覆盖 implementation。提交前移除了源码中两个密钥默认值，运行配置仍来自本地 .env。未上传 Git 远程。

| 真实电商输入 | 工具 | API 业务结果 |
| --- | --- | --- |
| 商城有哪些洗衣机？ | search_products | 返回 W-DEMO、W-DEMO-PLUS |
| 我的订单什么时候发货？ | list_orders | CLARIFY，候选含 ORDER_001、002、003 和发货状态 |
| 请查询 ORDER_002 的物流轨迹 | get_logistics | 包含 DEMO-TRACK-002 |
| 我的退货售后申请进度怎么样了？ | list_after_sales | 正常应答，本次未找到相应记录 |

以上均经正在运行的 AI 服务内部运行入口、真实配置的 JEV 和聊天模型执行，HTTP 200。a0-commerce.json 保存每条请求的输入、trace ID、调用名称、耗时、成功标志、令牌计数及脱敏回复摘要；令牌为运行汇总。未单独记录 JEV 置信度。

家电链路使用三个新建的本地隔离数据库、独立服务端口、独立 Redis 库及真实配置，以 smoke_test.py 从用户 HTTP 入口执行。验证设备选择、W-DEMO 引用、两次未恢复、预览后明确确认、重放同一确认返回同一工单、冒烟进入 QUEUED、客服查看两步和关联工单、接单回复及结束。测试输出 PASS。历史通过 history 接口重读。a0-appliance.json 记录运行 ID、工具和交接摘要。旧家电工具记录的 0 毫秒来自既有固定写法，不能证明 LangChain 发起了业务工具调用。浏览器与 WebSocket 重连留给 B/C。
## 验证环境说明

原电商四条请求使用已启动的 8002 服务。家电 HTTP 基线使用新启动的隔离服务；这些进程读取 implementation/ai-service/.env，当时该文件两项模型密钥均缺失，源码的密钥默认值已清空。家电诊断选择因此走原有无密钥降级，结果只证明业务闭环和人工交接。基线未把它计为真实模型工具选择。

三个 A0 隔离数据库以 a0_ 加随机标识命名，保留以便按附件中的 trace ID 复核；临时服务已停止。后续 verify_isolated.py 仅清理其当次新建的 verify_ 数据库。
