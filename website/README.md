# 三角洲口风琴介绍页

这是挂载在 `https://aiygzn.top/melodica/` 的静态介绍页。

- `index.html`：页面内容与下载入口。
- `styles.css`：深色产品视觉与响应式布局。
- `assets/main-window.png`：软件主界面预览图。
- `delta-melodica-nginx.conf`：现有 Nginx 站点的独立路径配置。
- `downloads/`：本地部署暂存目录，已被 Git 忽略；发布时从 `dist/三角洲口风琴_v0.10.exe` 复制为 `delta-melodica-v0.10.exe`。

发布路径为 `/melodica/`，不会覆盖服务器现有首页。更新版本时同步替换服务器上的 `downloads/delta-melodica-v0.10.exe`，并更新页面中的版本号与说明。
