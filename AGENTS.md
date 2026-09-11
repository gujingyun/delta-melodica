# Repository Guidelines

## 项目结构与模块职责

本仓库是 Windows 本地 MIDI／简谱自动演奏工具，使用 Python 3.13、Tkinter 和 Mido。

- `app.py`：界面入口、曲库与设置；`overlay.py`：游戏悬浮窗。
- `music.py`：曲谱解析、旋律整理和八键映射；`player.py`：播放调度；`win_input.py`：Windows 输入、热键和权限检查。
- `test_music.py`、`test_overlay.py`：根目录中的单元测试与窗口集成测试。
- 内置曲谱位于 `music.py` 的 `DEMO_SCORES`；`export_demos.py` 导出示例 MIDI；`third_party/` 保存依赖许可证。
- `dist/`、`releases/`、`work/` 分别保存成品、历史发行包和临时数据，均已忽略；使用说明见 `README.md`，验证结果见 `验证记录.md`。

## 安装、运行与构建

在仓库根目录的 PowerShell 中执行，需要包含 Tkinter 的 Python 3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

常用验证与打包命令：

```powershell
# 曲谱、调度及模拟输入测试
.\.venv\Scripts\python.exe -m unittest -v test_music
# 悬浮窗集成测试，会操作自建的本地窗口
.\.venv\Scripts\python.exe -m unittest -v test_overlay
# 界面冒烟测试，使用独立数据目录
.\.venv\Scripts\python.exe app.py --smoke --data-dir .\build\smoke-data
# 安装构建依赖，运行 test_music，再用 PyInstaller 打包
.\build.ps1
```

构建输出为 `dist\三角洲口风琴.exe`，带管理员权限清单。普通源码启动也会请求提权，冒烟模式除外。

## 代码风格与命名

使用四空格缩进；函数、变量及模块采用 `snake_case`，类采用 `PascalCase`，常量采用 `UPPER_SNAKE_CASE`。代码注释、文档字符串及协作回复使用中文。沿用现有类型标注和 `dataclass` 风格，曲谱算法放在 `music.py`，系统调用集中于 `win_input.py`。仓库未配置格式化或 lint 工具，修改时保持周边风格，避免无关重排。

## 测试要求

测试使用标准库 `unittest`，文件命名为 `test_*.py`，测试方法命名为 `test_<行为>`；目前没有覆盖率百分比门槛。逻辑修改应补充相关回归用例，重点覆盖时值、重复音、焦点丢失、停止与异常后的按键释放。悬浮窗测试需要交互式 Windows 桌面，建议在管理员终端运行。界面修改需执行冒烟测试并检查截图；记录通过、失败及仍需游戏内验证的项目，不能用模拟测试代替实机结论。

## 提交与 Pull Request

沿用历史中的中文动词短句，例如 `修复钢琴曲伴奏碎音并增加旋律连奏模式`。按独立阶段提交并推送到已确认的 GitHub 远程；遇到 443 等网络错误先检查网络和 VPN。PR 应说明问题、行为变化和验证命令及结果，关联已有 issue；界面改动附截图。行为或发行流程改变时同步更新 `README.md` 和相关验证记录。

## 数据与配置约定

曲库、设置和诊断日志保存在 `%LOCALAPPDATA%\DeltaMelodica`，保持该目录兼容。测试使用临时目录或 `--data-dir` 隔离数据，不提交个人 MIDI、日志、虚拟环境或构建产物。保留前台窗口检查及停止释放机制；`--game-test` 会实际发键，仅用于明确安排的游戏内验证。
