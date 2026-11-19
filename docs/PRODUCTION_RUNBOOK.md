# 本地生产运行手册

1. 按 [README](../README.md) 准备本机 PostgreSQL、FFmpeg、Python 和 Node，运行项目的启停脚本。
2. 升级前停止已核验身份的 API、Worker 和正在写文件的进程，备份 PostgreSQL 和与该数据库匹配的 data 文件。验收时使用独立库与存储。健康检查、迁移和业务用例都通过后切换。
3. 用户在当前项目导入自有或已授权的素材，保存创作版本。剪辑批次只能使用本项目素材，验收后可下载实际输出。
4. 碰到任务失败，在批量生产页核对错误、输入快照、尝试及日志。核验失效原因后重试本地任务。文本请求状态未知时先查凭证，避免重复发送。
5. `python scripts/isolated_regression.py` 使用本机 PostgreSQL 临时创建独立回归库，执行迁移、模型比对和后端测试。前端运行 `npm run build`。可在 [阶段记录](ACCEPTANCE.md) 查看实际运行证据。

## V2.0 本机发布检查

在已配置 PostgreSQL、虚拟环境、锁定前端依赖、FFmpeg 和本机 Chrome 的 Windows 机器上运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/check_release.ps1 -ProductionBrowser
```

浏览器使用独立数据库、文件根目录和备用回环端口。若要复验 P5 到 P14 的已实现浏览器路径，构建后运行 `.\.venv\Scripts\python.exe scripts/isolated_regression.py --browser-only --all-browsers`。本地检查可以接入已有 Windows CI runner。双角色配音验收使用中文和英文系统音色，OCR 验收使用已安装的 `zh-Hans-CN` 识别器和 SimHei 测试字体。

构建并迁移后可用 `scripts/start.ps1 -Production` 从本机回环地址预览生产构建。运行 `scripts/package_local.ps1` 从 Git 提交生成源码 ZIP 和 SHA-256。源码包含锁文件、迁移和文档。输出位于忽略目录 `data/releases`，兼容环境在本机按锁文件构建。备份数据库、素材、凭据和本机环境独立保管。

## 独立恢复与回滚

P14 验证覆盖一致 PostgreSQL 转储、原件、已发布输出、分析派生和关联任务文件，另用恢复目录复验项目、素材和 Range。回滚先停写并保存当前库及文件，在独立目标恢复升级前备份，再配套切换对应代码与连接配置。 [P14 验收](P14_ACCEPTANCE.md)
