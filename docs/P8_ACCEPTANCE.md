# P8 本地静图运镜与候选采纳

基线为 P7 提交 `9c3b90d`。本阶段验证了混合制作中的本机 CPU 分支。图片生成、视频生成、供应商回调与远程 GPU 待接入和实测。

## 已实现

- 从本项目授权 PNG、JPEG 或 WebP 原件生成最多三种 24 fps H.264 运镜候选。支持推进、拉远、横移和三种常见画幅。输入哈希在执行前核对，输出校验编码、尺寸、帧率和实际帧数，原件保留。
- 提交候选批次原子入队，重复或不同参数调用受幂等校验。候选复用前复核指纹，候选文件和实际任务状态独立记录。支持固定 P7 批准版本的镜头 ID。
- 真实候选可预览和 Range 读取。人工采纳后建立继承来源授权的项目视频素材，保留源图、候选任务、计划/镜头和审核说明，供原有剪辑任务选用。

## 实测与数据库

- 全量后端 107 项通过，0 项失败，0 项跳过。保留 1 条上游 Starlette/httpx 弃用提示。端到端验证实际解码 12 帧且存在画面变化，两种候选输出哈希不同，缓存命中、提前采纳拦截、审核幂等和采纳后真实 FFmpeg 剪辑可执行。 [后端测试](p8-backend-tests.xml)
- Vue/TypeScript 与 Vite 构建通过。Chrome 验证真实两个候选、代理媒体元数据、Range 206、键盘采纳和剪辑页选用，未捕获浏览器异常。 [浏览器证据](p8-browser-acceptance.json) · [候选截图](p8-motion-candidates.png)
- 使用 PostgreSQL 0008 及已有 `tasks`、`task_events` 和 `assets`，本阶段无需新增 DDL。独立库 Alembic 模型差异检查通过。源码新增 `generation.py`、`GenerationStudio.vue`、测试和 Chrome 验收，接入当前路由及 Worker。

本地候选没有外部模型调用费用。电费、存储和人工成本未计量。尚需供应商授权和可核验上限，才能连接 AI 生成或远程 GPU。回滚前等待本地任务完成并保存可用产物，保留已采纳素材与任务记录；需要退回 P7 时可通过独立副本启动 P7，并确保旧 Worker 不领取仍排队的 P8 任务。

```powershell
.\.venv\Scripts\python.exe scripts/isolated_regression.py --browser-phase p8 --browser --junitxml data/tmp/p8-backend-tests.xml
Set-Location frontend
npm.cmd run build
```
