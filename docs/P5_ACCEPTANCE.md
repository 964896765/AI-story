# P5-A/B：模型治理与剧情工作流模拟验收

日期：2026-11-19（Asia/Shanghai）。本次继续实施时分支 master，HEAD `1f82c8c`（P0–P4审计记录），工作区已有本轮P5改动；保留P4实现与审计文档，在同一工程增量完成。未触碰工作区自动附件目录。

**结论：P5-A/B可配置实现与模拟工作流按以下范围通过。真实模型API调用未授权，预算0，真实AI剧情改编质量验收未执行，不能标记整个P5真实模型验收完成。** 无付费请求，无新依赖、权重下载或公网部署；图片、视频和TTS模型未接入。

## 本轮真实交付

|范围|实现与验收边界|
|---|---|
|供应商|保留统一ModelAdapter协议，新增离线Mock和OpenAI兼容HTTP适配；Base URL、模型、密钥环境变量名称、价格和限制可配置；真实配置UI默认禁用、保存不联网|
|密钥|只从环境变量/本机忽略配置读取值；数据库与前端仅有变量名称/是否配置；请求校验不回显拒绝输入；响应文本脱敏，不记录原始错误体或Authorization|
|预算|模拟/真实及币种隔离、十进制费率、整数micros、原子预留、项目限额与本机跨项目总限额；未知价格null并阻止调用；发送前重新检查授权与总限额|
|费用|供应商/模型/任务/源版本/提示词版本/费率快照/用量/核算记录；账单净实付未知时null；人工实付/退款凭证幂等登记，模拟费用不写真实成本台账|
|未知结果|超时/服务异常/发送中断保留占用，禁止自动重发；明确不计费拒绝才释放；已有响应先落库，重启仅恢复本地结算；已释放调用禁止再次开启结算|
|队列|沿用P3持久队列、全局单任务执行、租约和独立Worker；适配任务不能使用媒体通用重试；受控重试新建调用并要求潜在新收费确认|
|改编流程|固定小说/剧本/分集版本，目标/风格/观众/篇幅/约束，结构化剧情正文、对白与分集大纲；模拟输出明确“非AI生成”|
|版本与审核|草稿独立于正式版本；人工编辑追加草稿修订、历史加载后追加恢复、原稿差异、指定修订人工审核；批准后保存正式剧本和大纲，沿用P4正式历史与回滚；源版本和原始文件不覆盖|
|生产衔接|批准后固定剧本版本可引用到现有视频批次；实际FFmpeg成片经ffprobe验证后下载，不声称自动按剧情生成镜头|

## 实际验证证据

- [p5-backend-tests.xml](p5-backend-tests.xml)：**99 passed、0 failures、0 skipped**，保留1条上游Starlette/httpx弃用提示。原66项回归保留，新增33项（含参数化）。最后运行58.58秒，独立临时PostgreSQL库，执行迁移与schema check后测试，结束删除测试库。
- 新测试覆盖：预算0、未知费率、无授权/无密钥、并发预留不超额、重复调用/结算/凭证、429与5xx策略、超时与缺失用量保留占用、无效/拒绝/截断输出、取消前后、超限冻结、人工核对/退款上限、释放后不得重开结算、草稿历史追加恢复、过期源版本与审核冲突、未审核调用不能引用生产、正式源版本不变。
- 恢复测试覆盖发送前中断可恢复、发送后中断变未知且禁止重发、已落库响应结算中断恢复。另以**新Python进程**运行Worker恢复持久响应，并将适配器设为禁止调用，证明恢复不依赖原进程内存、不重发生成。含财务记录时直接降级被拒绝。
- [p5-browser-acceptance.json](p5-browser-acceptance.json)：真实Vite→FastAPI HTTP→独立Worker→PostgreSQL，使用已安装Chrome的独立配置。选择固定小说版本、创建模拟配置/预算、报价、执行、重复提交返回同一调用、差异对比、修改保存v2、键盘审核、创建固定审核版本的剪辑批次。真实自生成无音轨色彩图案剪为1秒；本机独立ffprobe确认视频流与时长；下载Range返回206，未捕获JS异常。HTTP和浏览器测试库/素材均隔离，运行结束清理，不在项目库伪造生产记录。
- [p5-review.png](p5-review.png)：已检查审核页面截图。首次键盘自动化曾缺少Enter文本而超时，修复CDP按键事件后完整浏览器验收通过；不隐藏首次失败。
- 前端最终 `npm run build` 通过Vue/TypeScript类型检查与Vite构建（26模块）；`pip check` 无依赖冲突。
- [p5-backup-migration-acceptance.json](p5-backup-migration-acceptance.json)：P5前dump恢复为0005、当前dump恢复为0006，均在新建独立库完成；各读取7项目、核对13项原素材SHA-256，正式库不替换。空库0006→0005→0006和schema check通过；正式库当前0006。备份演练是数据库恢复及原地素材校验，**没有复制全量data文件，不等于完整灾备已完成**。

开发使用的HTTP MockTransport只在内存返回响应；测试内的授权标记和伪密钥仅作用于测试进程，未发送外部请求。真实请求数 **0**、实际支出 **0**；每条模拟调用的实际费用字段仍为null，不将模拟用量核算当真实费用。未来真实单次改编预计费用 **未知/null**。

## 修改文件

新增业务源码：

- `backend/app/text_schemas.py`、`text_adapters.py`、`adaptation_policy.py`、`text_service.py`、`text_routes.py`。
- `backend/migrations/versions/0006_text_governance.py`、`backend/tests/test_text_governance.py`。
- `frontend/src/TextAdaptation.vue`、`TextProviderConfig.vue`、`money.ts`。
- `scripts/browser-p5.mjs`、`scripts/p5_recovery_check.py`。

修改现有源码/配置：

- `backend/app/models.py`、`model_adapters.py`、`worker.py`、`main.py`、`creative.py`，以及 `backend/tests/test_render_postgres.py` 当前迁移断言。
- `frontend/src/App.vue`、`StoryStudio.vue`，`scripts/isolated_regression.py`，`.env.example`。
- README、`docs/ACCEPTANCE.md`、`ARCHITECTURE.md`、`LICENSE_REVIEW.md`；新增本报告、[模型契约与接入步骤](P5_MODEL_CONTRACT.md)、测试XML、验收JSON与截图。

未提交.env、数据库转储、素材视频、临时浏览器数据或密钥；自动附件保持不变且不加入本次提交。

## 启动与复验

项目数据库已迁移0006；正常本地启动方式保持 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1`。界面 http://127.0.0.1:15173 ，API文档 http://127.0.0.1:18000/docs 。进入漫剧定制选择固定版本，然后进入剧情改编配置模拟额度和模拟模型。本轮恢复启动时显式关闭真实调用开关、真实本机额度为0。

完整隔离复验：先通过本项目stop脚本停服务释放15173/18000，然后运行：

```powershell
.\.venv\Scripts\python scripts/isolated_regression.py --junitxml docs/p5-backend-tests.xml --browser
.\.venv\Scripts\python scripts/p5_recovery_check.py
```

前端在frontend执行 `npm run build`。只跑后端时可省略 `--browser`，不要求停止正常工作台；脚本仅操作自己创建的随机测试库。恢复检查依赖现有Docker PostgreSQL容器与忽略目录中的P5前备份。

## 未完成与限制

- 真实供应商、模型、价格尚未选定；真实API兼容性、创作质量、账单准确性未验收。后续选择建议、官方文档与实际配置顺序见[模型契约](P5_MODEL_CONTRACT.md)。必须先明确授权素材外发和费用上限，不能直接启用真实调用。
- 预算以已核验Token上界和费率作保守预留，不提供精确tokenizer或长小说自动分块。推理/缓存/额外工具等计费条款须逐模型核对；供应商违反上界时只能记账冻结，须结合供应商侧硬限额控制风险。
- 未知调用依赖人工凭证对账，无供应商账单自动查询；超额冻结没有自动解除入口。发送后取消无法保证供应商不收费，网络超时不是远端生成终止保证。
- 当前为本机可信用户单Worker串行，不提供多租户权限、跨实例云端队列或公网部署。
- 全文件自动备份、外部账单自动对账、智能分镜、角色一致性、付费图片/视频/TTS及P6质检运营仍未实现。

## 回滚

1. 禁用供应商、关闭真实调用开关并停本项目API/Worker；保留全部调用、未知占用、账单、版本和文件，先核对已发送请求，不自动重放。
2. 停止写入后备份当前PostgreSQL和完整data。数据库备份记录中P5前路径为 `data/backups/p5-before/database.dump`，当前快照路径见恢复JSON；这些目录忽略且不随Git提交。
3. 已有财务记录时迁移拒绝直接downgrade。新建独立数据库恢复P5前备份为0005，核对原文件/版本后，再用独立checkout检出 `1f82c8c` 并指向恢复库启动；保留当前0006数据库与全部data用于审计和数据合并。不得让旧Worker连接0006继续领取文本任务。
4. 仅无P5账本/文本任务的可丢弃测试库可演练0006→0005降级；不对正式库删表回滚，不删除Docker卷或覆盖源素材。
