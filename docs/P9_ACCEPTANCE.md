# P9 本机角色配音与字幕

基线为 P8 提交 `8d68eb2`。本地分支使用已安装的 Windows 离线系统语音。没有下载权重或系统音色，也没有调用云端 TTS。 [Microsoft 系统语音 API](https://learn.microsoft.com/en-us/DOTNET/api/system.speech.synthesis.speechsynthesizer?view=netframework-4.6)

## 实现

- 固定分镜、对白、镜头时间窗和角色版本。每个角色可绑定一款已安装的离线音色、语速和使用授权说明。把正文作为纯文本处理。
- 独立 Worker 分句生成真实 48 kHz 单声道 PCM，验证可听信号、采样率、时长和产物哈希。超出镜头窗口时失败并报告实际用时。成品用实际波形采样数构造 SRT 和 VTT 毫秒时间戳。
- 支持试听、下载与人工采纳。采纳后生成可被原有剪辑入口选择的 WAV 和 SRT 项目素材，保留固定版本、授权说明和任务 ID。

## 实测

- Chrome 实际提交两角色、两种离线语音，生成中文和英文样本。验证 WAV 媒体读取、Range 206、字幕时间与键盘采纳，未捕获浏览器异常。 [浏览器证据](p9-browser-acceptance.json) · [试听截图](p9-voice-review.png)
- PostgreSQL 维持 0008，复用已有任务、事件、素材和创作版本表。隔离库 Alembic 模型检查通过，前端类型检查和生产构建通过。后端 108 项通过，0 项失败，0 项跳过，保留 1 条上游 Starlette/httpx 弃用提示。覆盖实际系统语音、声段间静音、时间与码流导出、角色音色拦截及采纳幂等。 [回归证据](p9-backend-tests.xml)
- 实际平台/API 费用 0 元。样本为自编中文和英文短句。

源码新增 `backend/app/voice.py`、`scripts/synthesize_dialogue.ps1` 和 `frontend/src/VoiceStudio.vue`，接入现有路由、Worker 和工作台。新增真实音色集成测试与 Chrome 脚本。

```powershell
.\.venv\Scripts\python.exe scripts/isolated_regression.py --browser-phase p9 --browser --junitxml data/tmp/p9-backend-tests.xml
Set-Location frontend
npm.cmd run build
```

## 限制与回滚

- 当前支持本机已安装并列入适配范围的中文和英文系统音色。商用发布需要核对具体声音及素材许可。情绪、读音词典、字级对齐、声源分离、音效生成和云端语音仍未交付。
- 当前合成的是按镜头对齐的对白轨。音乐和音效混音、底噪/响度与转场处理将在多轨时间轴中验证。
- 回滚前等待配音任务结束，保留队列和已采纳产物。需要 P8 时可从独立副本启动对应代码，仍使用 0008，旧 Worker 应与已排队的新任务隔离。
