# AI 漫剧工厂 V2.0 能力矩阵

基线 Git 提交为 `5a988dab6e941049a106eea5c0b14e850d049239`。审计开始时工作区已有未提交的 0006 迁移、文本服务、Worker 接入与测试。初始回归覆盖这些变更和 P0–P4，独立 PostgreSQL 由空库迁移到 0006，模型差异检查通过，82 项测试通过，0 项失败，0 项跳过。前端类型检查与构建通过。早期浏览器、HTTP 和数据库恢复结果按各阶段证据标注。

|模块|回归基线|未交付或待验项|
|---|---|---|
|01 生产总控台|部分。项目选择、Worker 状态、任务和费用汇总，见 [App.vue](../frontend/src/App.vue)、[QueuePanel.vue](../frontend/src/QueuePanel.vue)|阶段进度、待审统一视图、恢复最近工作|
|02 漫剧资源库|部分。原始文件、SHA-256、单文件授权说明、范围读取；见 [storage.py](../backend/app/storage.py)、[P4 验收](P4_ACCEPTANCE.md)|作品/剧集登记、来源权利、去重、分页检索、引用感知归档、存储配额|
|03 智能解析|部分。Worker 实际执行 ffprobe，数据库保存原始探测 JSON，见 [media.py](../backend/app/media.py)|分轨、代理、抽帧、切镜、波形和版本化证据；ASR/OCR/说话人/视觉理解待实现与实测|
|04 深度二创|本地剪辑已验收，P5 初始后端支持模拟剧情改编，见 [P2 验收](P2_ACCEPTANCE.md)、[文本测试](../backend/tests/test_text_governance.py)|真实模型与授权参考视频解析、人物重构、局部生产闭环|
|05 漫剧定制|部分。小说/剧本、规则拆分、结构化分集分镜、固定引用及版本历史，见 [creative.py](../backend/app/creative.py)|章节与长文本分层、故事圣经、跨集逻辑和生成式镜头策划|
|06 创作资产|部分。角色、场景、人物关系、图片/声音参考与不可变版本，见 [story_schemas.py](../backend/app/story_schemas.py)|道具、服装/多角度、风格圣经、版本化提示词、音色许可与一致性|
|07 AI 生成|模拟文本通过基线测试，图片/视频/语音只有禁用契约，见 [model_adapters.py](../backend/app/model_adapters.py)|候选生成、选用、复用、可追踪外部任务与真实模型验收|
|08 智能剪辑|部分。本地单视频裁剪、画幅调整、字幕烧录、原音或替换、真实渲染，见 [render.py](../backend/app/render.py)|专业多轨时间轴、静图运镜、混音/转场、代理、回退与工程交换|
|09 批量生产|部分。固定引用、原子批次、持久队列、取消重试、尝试记录、租约与检查点，见 [P3 验收](P3_ACCEPTANCE.md)|整剧 DAG、资源池、依赖失效和分层并发/磁盘背压|
|10 质量检测|部分。输出流、时长、尺寸、音轨与哈希技术校验，见 [render.py](../backend/app/render.py)|黑帧/冻结/静音/字幕、可定位问题、人工验收与局部返工、发行门槛|
|11 模型算力|部分。模拟预算与费率、有界报价、固定配置、未知结果占用，见 [text_service.py](../backend/app/text_service.py)|真实供应商能力价格/条款、分层配额及基准测试、云 GPU、外部账单采集|
|12 交付|部分。成片下载与创作清单分别可用，见 [main.py](../backend/app/main.py)、[P4 验收](P4_ACCEPTANCE.md)|整剧包、权利/质检守门、制作证据和交付清单闭环|
|13 发行运营|缺失。原有运营入口显示未实现，见 [App.vue](../frontend/src/App.vue)|平台规格、蓝V剧场/账号、发行计划、合规推广包、人工上传与实际状态|
|14 经营分析|部分。已有费用与尝试时间汇总，币种分列，见 [P3 验收](P3_ACCEPTANCE.md)|结算导入与去重、现金/广告金、成本归集、分账、利润与回本|
|15 工作流与模板|部分。结构化剪辑参数及可版本化模型输入计划，见 [VideoEditor.vue](../frontend/src/VideoEditor.vue)、[story_schemas.py](../backend/app/story_schemas.py)|版本化 DAG、参数和模板库、克隆及交换|
|16 系统管理|部分。只监听本机、Host/Origin/IP 边界、健康检查、启停身份核验和历史数据库恢复，见 [启动脚本](../scripts/start.ps1)、[P4 验收](P4_ACCEPTANCE.md)|完整文件快照恢复、滚动日志、磁盘监控、依赖持续审计、发布与升级策略|

P1 历史依赖漏洞审计的时间和范围见 [阶段记录](ACCEPTANCE.md)。本轮运行了 `pip check`。商业分发前仍需核对实际 FFmpeg 构建、容器与二进制依赖、字体及模型许可。 [依赖许可证记录](LICENSE_REVIEW.md)

证据：[基线测试 XML](v2-baseline-tests.xml)、[P4 HTTP](p4-http-acceptance.json)、[P4 浏览器](p4-browser-acceptance.json)、[P4 历史迁移](p4-migration-acceptance.json)、[P4 历史恢复](p4-backup-acceptance.json)。

## 阶段增量

|模块|最新实现与证据|待办|
|---|---|---|
|03 智能解析|P6-A 本地流清单、分轨、转封装、代理、抽帧、切镜、字幕、波形接入异步 Worker。P6-B 增加版本化人工审核、证据对齐和正式创作采纳。见 [本地分析引擎](../backend/app/analysis_engine.py)、[审核契约](../backend/app/analysis_review.py)|接入并单独验证 ASR、OCR、说话人、音源分离与多模态；扩展超长片、异常封装与色彩|
|04 深度二创|P5-B 模拟改编、草稿历史、人工批准、版本固定生产已通过。P6 人工确认的解析剧本可直接进入 P5。见 [P5 验收](P5_ACCEPTANCE.md)、[解析工作区](../frontend/src/MediaAnalysis.vue)|真实文本模型质量、跨集剧情策略、局部再编|
|07 AI 生成 / 11 模型算力|P5-A 兼容文本契约、费用闸门、项目与跨项目真实上限、未知状态、离线模拟、人工账单与退款。见 [P5 模型契约](P5_MODEL_CONTRACT.md)|真实供应商报价和授权后的样片、更多预算层级、账单自动对账、图片/视频/语音/远程算力|
