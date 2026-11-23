# A 阶段补充证据

真实 DeepSeek 调用使用统一 ToolExecutor 执行了 `list_my_devices`。A2 隔离验收记录为 trace `trace_d18f5a21135242cfa481e78b4edef52f`，模型工具调用 ID `call_00_p5Ew8R075V2nEyoOmVvh6272`，执行成功，耗时 330 ms。

| 浏览器联调实际观测点 | 输入模型的工具范围 |
| --- | --- |
| 首轮，Skill 未加载 | load_skill |
| 首轮，加载 appliance_service 后，设备未核验 | list_my_devices、load_skill |
| 设备选择轮，设备已核验，Skill 尚未加载 | load_skill |
| 设备选择轮，设备已核验且 Skill 已加载 | search_manual、get_device_warranty、list_my_repairs、prepare_repair_preview、load_skill |

工具范围来自 SkillScopeMiddleWare 实际模型调用日志。首轮 trace 为 `trace_ba8922f29b554e64aed98adaca1109a1`，设备选择轮为 `trace_cd214eb8da8149c9a6ab18edda9aead0`。Skill 在每轮运行中加载。设备核验发生在当轮运行上下文构造阶段，工具需要已核验设备与已加载 Skill 同时满足才披露。

| 概念 | 当前实现 |
| --- | --- |
| service_scene | 会话表持久化的业务领域，随 Worker 请求传入 Agent，约束 Skill 及工具权限。 |
| skill_code | LangChain 运行状态中的 SkillCode 值。电商可由 JEV 预选，家电由 load_skill 加载。 |
| intent_code | 当前没有独立字段。JEV 分类返回候选 SkillCode，执行器用它决定电商 Skill 或生成进入家电售后的引导。 |
| workflow_stage | service_context 内的可选业务状态，当前显式记录自查恢复和可报修，待反馈步骤由 pending_step 表示。 |
| context_version | 会话表中的业务状态版本，客服服务校验诊断反馈版本，Worker 核对版本后才应用异步结果。 |
