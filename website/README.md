# 三角洲口风琴介绍页

这是挂载在 `https://aiygzn.top/melodica/` 的静态介绍页。

- `index.html`：页面内容与下载入口。
- `styles.css`：深色产品视觉与响应式布局。
- `assets/main-window.png`：软件主界面预览图。
- `assets/display-mode-borderless.png`：游戏视频设置中的无边框窗口示意图。
- `delta-melodica-nginx.conf`：现有 Nginx 站点的独立路径配置。
- `version.json`：客户端检查更新时读取的公开版本清单。
- `songs.json`：客户端读取的线上 MIDI 曲库目录，当前包含 5 首曲目；新增条目时，`url`、`size` 和 `sha256` 必须与 `songs/` 中的文件一致。
- `songs/`：线上曲库提供下载的 MIDI 文件目录。
- `downloads/`：本地部署暂存目录，已被 Git 忽略；发布时从 `dist/三角洲口风琴_v0.13.exe` 复制为 `delta-melodica-v0.13.exe`。
- `../server/melodica_stats.py`：记录官网浏览次数和下载入口点击次数。
- `admin/index.html`：私有统计页，由服务器 Basic Auth 保护，不在公开页面显示入口。

发布路径为 `/melodica/`，统计页为 `/melodica/admin/`，不会覆盖服务器现有首页。更新版本时同步替换服务器上的下载文件，更新页面中的版本号与说明，并修改 `version.json` 的 `version` 和 `notes`。新增线上曲目时同步上传 `songs.json` 和 `songs/` 中对应的 MIDI。

统计密码只保存在服务器的 Nginx 密码文件中，不提交到仓库；统计数据保存在服务器本地 `/var/lib/delta-melodica-stats/stats.json`，不记录访客身份或曲谱内容。
