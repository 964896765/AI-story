# 初步依赖许可证审查

未引用 xhongc/ai_story 或其他漫剧项目源码。没有引入 NC（非商业）模型或代码，也未下载权重。

|组件|上游许可|当前使用|
|---|---|---|
|Vue、Vite、TypeScript、vue-tsc、FastAPI、SQLAlchemy、Alembic、python-dotenv、pytest、httpx|MIT / Apache-2.0（TypeScript）|开发/运行依赖，保留上游通知|
|Uvicorn、Starlette|BSD-3-Clause|后端服务|
|python-multipart|Apache-2.0|上传解析|
|Psycopg 3|LGPL-3.0|数据库驱动；binary wheel 的捆绑库须单独核验|
|PostgreSQL|PostgreSQL License|官方容器，首次拉取才获取|
|本机 FFmpeg|实际输出 GPL v3 or later|仅外部调用，不复制/分发二进制|

以上为直接依赖初筛，不是完整法律审查。发布前必须审核锁定依赖的 LICENSE/NOTICE、Psycopg wheel 的 libpq/OpenSSL 等捆绑库、PostgreSQL 镜像系统组件，以及 FFmpeg 所有编译组件与编解码专利。没有发现直接依赖带非商业限制的依据，但不宣称整个供应链已完全审计。

安全审计以阶段记录中的真实工具结果为准。许可证允许商用不等于没有漏洞。当前仅本地开发版本，不能直接作为公网生产部署配置。
