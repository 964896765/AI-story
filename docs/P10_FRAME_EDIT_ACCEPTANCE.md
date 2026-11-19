# P10 时间轴拖动、裁剪与吸附

基线为 `0378dc4`。本轮把直接编辑接入已有 24 fps 时间轴，编辑仍由既有版本、校验与渲染入口保存和执行。

## 使用与实现

- 拖动片段可在同轨移动。在可放置的范围内，移动吸附启用时会识别时间轴端点和已启用轨道的片段边界。按住 Alt 可临时关闭吸附。
- 选中片段后，左右边缘可直接向内裁剪。画面、声音或字幕左裁时同步移动源入点。静图源入点保持零，淡入淡出帧数随时长保持有效。精确数值编辑保留在片段面板。
- 片段与裁剪手柄支持方向键逐帧操作，Shift 加方向键操作 10 帧。拖动中按 Esc 可取消。锁定轨道阻止指针及键盘编辑。同轨片段保持无重叠。
- `TimelineStudio.vue` 接入交互，`timelineGestures.ts` 负责整数帧位置与合法边界计算。`browser-p10.mjs` 验证真实指针和键盘、提交的版本以及 FFmpeg 产物。PostgreSQL 保持 `0013`，保存格式与 API 路径沿用现有契约。

## 验收

- Chrome 试图将主画面第一段拖入第二段，验证保持无重叠。拖动字幕接近对白开头时吸附到第 6 帧。左右键验证逐帧移动和锁定。裁剪后从服务器清单读取位置第 10 帧、源入点第 4 帧、时长 36 帧，与界面一致。
- 编辑前后均通过 Worker 真正渲染 48 帧 MP4，验证两份文件哈希不同。原成片由 Chrome 解码并通过 Range 读取，追加恢复的 v3 与 v1 时间轴完全一致。样本为自行生成媒体，外部调用与费用为 0。 [Chrome 证据](p10-frame-edit-browser-acceptance.json) · [编辑截图](p10-frame-edit.png)
- `vue-tsc`、Vite 生产构建、隔离库迁移与 Alembic 检查通过。专项后端 2 项通过，0 失败，0 跳过，保留已有的上游 Starlette/httpx 弃用提示。 [专项 JUnit](p10-frame-edit-tests.xml)

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --test-file tests/test_timeline.py --browser --browser-phase p10
```

## 限制与回滚

直接手势支持同轨移动和缩短片段。向外延长可用数值控件，并由后端验证源区间。跨轨拖拽、实时合成预览、工程交换和复杂转场仍待开发。回滚可关闭本机应用后退回 `0378dc4` 并重新构建，使用相同 0013 数据库和时间轴版本记录。历史版本、成片及素材可保留。
