# P11 从质检定位片段并返工

基线为时间轴直接编辑提交 `0e4cc68`。本轮将 PostgreSQL 已持久化的技术质检片段引用接入现有多轨编辑与整剧返工。

## 实现与数据库

- 带关联片段的技术质检项可直接打开产出该结果的固定时间轴版本。编辑器选择对应片段并置入键盘焦点，在片段面板可替换素材及修改入点、时长等参数。全局问题仍可打开分集时间轴。
- 保存修改后可返回原质检批次。工作区重新读取该批次，并用现有局部返工填写新时间轴版本。项目切换清理此前的批次和定位上下文。
- 本轮改动 `App.vue`、`ProductionStudio.vue`、`TimelineStudio.vue`、`browser-p11.mjs` 与隔离回归脚本。使用已有 QC `issues[].clips`、项目归属、版本和批次记录。数据库保持 `0013`，迁移模型比对通过。

## 实测

- 本机 Chrome 在隔离 PostgreSQL 与文件根目录中运行。FFmpeg 自制样本的 0–625 毫秒被判为黑场，同时检测到缺音轨。点击黑场提示后，Chrome 焦点进入实际关联片段。替换素材并添加音轨，追加版本后返回原批次。Worker 重渲染和复检的结果有 0 条问题，成片经 Chrome 解码预览。 [浏览器证据](p11-clip-rework-browser-acceptance.json) · [焦点截图](p11-focused-clip.png)
- Vue/TypeScript 检查和生产构建通过。专项后端 4 项通过，0 失败，0 跳过，保留已有的 Starlette/httpx 上游弃用提示。对外模型费用为 0。 [后端专项](p11-clip-rework-tests.xml)

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
& ./.venv/Scripts/python.exe scripts/isolated_regression.py --test-file tests/test_production.py --browser --browser-phase p11
```

## 边界与回滚

定位使用现有 QC 区间和主画面片段的重叠关系。返回轨迹保存在当前工作台会话。返工仍按受影响的分集渲染，其他符合复用条件的分集可保留成片。镜头级渲染缓存与可编辑 DAG 待开发。回滚可停止本机应用后使用 `0e4cc68` 重新构建，现有数据库、审核证据和制作版本可继续读取。
