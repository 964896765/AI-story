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

P2 未增加第三方运行依赖或复制外部实现。FFmpeg 继续作为本机外部程序调用，使用已有 libx264、AAC、libass；未分发二进制或字体。本机字体的字形与商用分发授权需单独核验。Windows Job Object 通过标准库 ctypes 调用系统 API。浏览器验收使用本机已安装 Chrome，不打包浏览器。

P3继续使用现有依赖与Python/Node/PowerShell标准能力，无新增模型、外部代码或运行依赖；本阶段没有重新跑漏洞源扫描，不能把P1审计日期当作P3的最新漏洞数据库结果。

P4没有新增依赖或下载权重，未复制外部项目代码；规则整理使用自编逻辑，适配器只有禁用实现。新增参考图/文本仍要求自有或授权来源，授权说明由用户记录，不代表系统已核验权利。没有重新执行最新漏洞源扫描，不沿用旧扫描日期声称新的全供应链安全结论。
