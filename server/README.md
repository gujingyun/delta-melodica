# 账号与私有云端曲库

账号 API 与静态官网、客户端界面分开运行。保留原有 3002 端口统计服务，新增 3003 端口账号服务。Python 3.13；客户端无需安装后端依赖。

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements-test.txt
.\.venv\Scripts\python.exe -m unittest -v test_accounts
.\.venv\Scripts\python.exe -m uvicorn server.accounts:create_app --factory --host 127.0.0.1 --port 3003 --no-access-log
```

默认数据目录 `work/account-server`。未配置 SMTP 时发验证码会明确返回 503；不会跳过邮箱验证，也不会将验证码回传给客户端或写入日志。自动化测试使用临时目录与注入的假邮件投递器，不发送真实邮件。

## 发信与部署

2026-09-13 已部署至阿里云现有服务器：[账号页面](https://aiygzn.top/melodica/account/)、[服务健康检查](https://aiygzn.top/melodica/account-api/health)。服务由 `delta-melodica-accounts.service` 管理并设置开机启动，仅监听 `127.0.0.1:3003`。真实邮件注册、找回密码、重置撤销旧会话及原生令牌／网页 Cookie 会话曲库互通均已通过线上 HTTPS 验证，结果见[验证记录](../验证记录.md)。网站原入口与 Nginx 配置备份位于 `/var/backups/delta-melodica/accounts.XIXVd4mr`。

1. 为 `aiygzn.top` 配置独立发信子域名，按供应商控制台配置域名验证、SPF、DKIM 和 DMARC。可选择阿里云邮件推送或 Resend。
2. 参照 `account.env.example`，在服务器环境中填写 SMTP 主机、端口、用户、密码、发件地址。当前使用阿里云华东 1（杭州），发信地址 `no-reply@mail.aiygzn.top`，触发邮件类型；发信域名的 SPF、2048 位 DKIM、DMARC、MX 已在控制台验证通过。465 使用 `SMTP_TLS=ssl`，587 使用 `SMTP_TLS=starttls`。始终校验 TLS 证书，不支持明文 SMTP。密码只保存在服务器受限环境文件中。
3. 将仓库及后端依赖安装到 `/opt/delta-melodica`，创建专用系统用户 `melodica-accounts` 与数据目录 `/var/lib/delta-melodica-accounts`。数据目录权限 0700，环境文件权限 0600；不要置于网站静态目录。
4. 安装 `delta-melodica-accounts.service`。Nginx 将 `/melodica/account-api/` 反代到 `127.0.0.1:3003/`，账号路由使用 HTTPS、`client_max_body_size 2m`，关闭访问日志，不对外暴露后端端口。
5. 生产 `MELODICA_ORIGIN=https://aiygzn.top`。仅在本机 HTTP 联调时设 `MELODICA_DEV_HTTP=1` 并配置对应 Origin；生产不得开启。
6. 部署后验证注册及重置验证码到达测试邮箱、垃圾邮件分类、重置后旧会话失效、三端互通。SMTP 可连接或认证成功并不代表真实投递已验证。

生产依赖固定在 `requirements.lock`（包含传递依赖及 SHA-256 校验值），使用 `pip install --require-hashes -r server/requirements.lock` 或 `uv pip sync --require-hashes server/requirements.lock` 安装。服务器自带 Python 3.6，账号服务使用单独安装的 Python 3.13.15，目录 `/opt/delta-melodica-python`，项目虚拟环境位于 `/opt/delta-melodica/.venv`。系统 Python 和统计服务继续使用原环境。运行环境由 [uv 官方安装方式](https://docs.astral.sh/uv/guides/install-python/) 安装，后续补丁升级需重新运行账号回归测试。

## 接口约定

所有写请求使用 JSON。原生客户端登录／注册传 `client: "native"`，从响应取得随机会话令牌并使用 `Authorization: Bearer ...`。官网传 `client: "web"`（默认），使用 HttpOnly、Secure、SameSite=Strict Cookie，不把令牌放入浏览器存储。浏览器写请求要求 Origin 匹配。会话有效期 30 天，退出撤销当前会话，密码重置撤销所有会话。

| 方法 | 相对账号 API 路径 | 内容 |
| --- | --- | --- |
| POST | `/auth/request-code` | `email`, `purpose: register/reset`；通用响应避免直接暴露账号存在性 |
| POST | `/auth/register` | `email`, `password`, `code`, `client`；先验证邮箱再创建账号 |
| POST | `/auth/login` | `email`, `password`, `client` |
| POST | `/auth/reset-password` | `email`, `password`, `code` |
| GET | `/auth/me` | 当前账号 |
| POST | `/auth/logout` | `{}` |
| POST | `/library/claim` | `guest_token`；同一游客批次只能归属一个账号，可重复请求 |
| GET | `/library/songs` | 当前账号目录，最多 500 首 |
| POST | `/library/songs` | 标准曲谱 JSON；按内容去重，只添加到当前账号 |
| GET / DELETE | `/library/songs/{id}` | 读取／移除当前账号的曲目；删除写请求带 `{}` |

密码为 10～128 字符，使用 Argon2id。验证码 6 位，10 分钟有效，最多错 5 次；同邮箱发信间隔 60 秒，每小时最多 5 次，IP 每小时最多 10 次。登录按邮箱和 IP 限流。验证码使用服务器密钥 HMAC，会话仅保存摘要。密钥 `otp-secret` 不可提交 Git。

## 曲谱和数据恢复

交换格式为 `{version: 1, title, duration, notes}`，时间均为整数毫秒；每个音符为 `[start, end, pitch, track]`。支持 1～30000 音符、最长 30 分钟、曲名最多 100 字符。完整音符和音轨编号跨端同步；端特有的音轨名称、速度、移调、演出片段、校准不在本期云同步范围。

标准化曲谱 JSON 随曲目归属一起保存在 SQLite，保证上传和归属原子提交。原始 MIDI／简谱仍保留在导入设备；云端保存可跨端演奏的音符副本。内置示例随各端程序提供，不重复上传。

SQLite 采用默认回滚日志与短事务，密码计算、网络请求均在事务外完成。SQLite 的写入串行，适合初期单机服务。备份使用 Python `sqlite3.Connection.backup()`，同时安全备份 `otp-secret` 和环境配置；不要在运行中直接复制数据库文件。恢复前停止账号服务，恢复后核对文件权限及 `/health`，再恢复服务。

安全设计参考：[OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[SQLite 适用范围](https://www.sqlite.org/whentouse.html)。

## 浏览器与桌面联调

桌面账号回归：`python -m unittest -v test_accounts test_account_client`（Windows，含 Tk 窗口测试）。浏览器测试先在仓库根目录运行 `python server/test_web_server.py`，然后在另一终端执行 `npm --prefix website install` 和 `npm --prefix website run test:accounts`，需要本机 Chrome。也可用环境变量 `PLAYWRIGHT_MODULE` 指向已安装的 Playwright 模块目录。

浏览器脚本访问本机 `127.0.0.1:8767`，使用虚构邮箱，不发送真实邮件。临时数据库由测试服务退出时清理，测试截图与假邮件位于忽略目录 `work/accounts-web/`。这个测试服务放宽验证码发送间隔，仅供联调，绝不能用于生产。正式服务仍使用 `server.accounts:create_app`。

## DDoS 应急防护

官网主机出现应用层洪泛或 SSH 连接爆发时，可在云控制台或现有管理终端执行仓库中的防护脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/gujingyun/delta-melodica/master/server/harden-ddos.sh | sudo bash
```

脚本会自动备份现有配置，并配置官网/API 的 Nginx 按来源限速、连接数限制、基础 TCP 参数和 SSH Fail2ban；Nginx 配置测试失败时会恢复本次修改。执行前必须确认云控制台或备用管理入口可用，因为任何主机级防护都不能替代云厂商的 DDoS 清洗。

脚本不会修改云安全组，也不会自动开放或关闭 SSH 端口。仍需在云厂商控制台开启 DDoS 清洗/WAF，并让源站只允许 CDN/WAF 回源；带宽型攻击必须由上游清洗。
