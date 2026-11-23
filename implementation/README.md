# 智能家电售后服务 Agent 系统

正式实现位于 implementation，包含三套 FastAPI 服务、两个 Vue 前端、PostgreSQL 迁移及 DEMO 数据。项目根目录的 PRD 和 Spec 是验收依据。

## 本机入口

- 用户端 http://127.0.0.1:5183/appliance，选择演示账号李明。
- 客服端 http://127.0.0.1:5184，切换到客服小周。
- 普通商城入口 http://127.0.0.1:5183/mall。

## 从空环境启动

准备 Python 3.12、Node.js 24、PostgreSQL 和 Redis。先创建三个专用于演示的 PostgreSQL 数据库。每个 Python 服务使用自己的虚拟环境。在 ecommerce-service 执行 pip install -r requirements.txt，在另外两个服务执行 uv sync。两个 frontend 子目录分别执行 npm ci。

在每个后端服务目录放置独立的 .env。三个服务配置相同的 JWT_SECRET，客服与 AI 额外共享 INTERNAL_SERVICE_TOKEN。数据库 URL 使用 postgresql+psycopg:// 格式，各自指向演示库。不要使用参考项目的远程数据源。

| 服务 | 本地设置 |
|---|---|
| ecommerce-service | ECOM_DATABASE_URL |
| customer-service | DATABASE_URL、REDIS_URL、API_HOST=127.0.0.1、AI_SERVICE_URL=http://127.0.0.1:8002、ECOMMERCE_BASE_URL=http://127.0.0.1:8001 |
| ai-service | AI_DATABASE_URL、API_HOST=127.0.0.1、ECOMMERCE_BASE_URL=http://127.0.0.1:8001；真实模型配置使用 LLM_PROVIDER、LLM_MODEL、LLM_API_KEY、LLM_BASE_URL |

依次在三个服务各自目录运行 python migrate.py。电商迁移创建新表并初始化演示订单与设备，AI 迁移导入 manuals 下两份 PDF，客服迁移升级场景及轮次索引。迁移已有库前停写并备份，历史 COLLECTION 重复行需先核查。迁移命令可重复执行。

- 电商服务运行 python -m uvicorn ecommerce_service.main:app --host 127.0.0.1 --port 8001。
- AI 和客服服务各自运行 python -m atguigu.main。该入口在 Windows 使用 psycopg 支持的 Selector 循环。
- 两个前端分别运行 npm run dev -- --host 127.0.0.1。

## 演示与验证

输入洗衣机 E3，选择具体序列号，核对引用并逐步反馈。打开维修预览后明确确认，查询本人记录。输入「设备正在冒烟」后，切换到客服端查看交接、接入并回复。家电场景与电商共用 LangChain Agent 和 ToolExecutor。AI 服务需要在 .env 配置 LLM_API_KEY、TYPESAFE_API_KEY 及对应供应方地址，JEV 代理可通过 TYPESAFE_PROXY 配置。无聊天模型凭据时无法完成真实家电工具调用。


电商、客服目录各运行 python -m pytest -q tests，AI 目录运行 python -m unittest discover -s tests -v。三服务运行后，可从本目录执行 python smoke_test.py 验证 HTTP 闭环。该脚本会创建 DEMO 工单与交接记录，使用初始样例库验证首次建单。测试结果与文件范围见 DEVELOPMENT.md。

## 多场景回归

A0-baseline.md、A1-status.md 和 A2-results.md 分别记录基线、受控转入及工具整合验收。verify_isolated.py A2 在本地 PostgreSQL 新建临时数据库，使用 18100–18102 端口和 Redis 56379 的 14 号库。仅在这些资源可用于测试时运行。TEST_AI_PYTHON 与 TEST_SERVICE_PYTHON 可指定已有服务运行环境，测试会真实调用配置的模型。
