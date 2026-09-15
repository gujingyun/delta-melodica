#!/usr/bin/env bash

# 三角洲口风琴官网主机级应急防护脚本。
# 该脚本面向 AlmaLinux/RHEL 系统，执行前必须确认云控制台或 SSH 备用入口可用。

set -Eeuo pipefail

readonly app_name="delta-melodica"
readonly backup_dir="/var/backups/${app_name}-ddos-$(date +%Y%m%d-%H%M%S)"
readonly nginx_zone_file="/etc/nginx/conf.d/00-${app_name}-ddos.conf"
readonly fail2ban_jail_file="/etc/fail2ban/jail.d/${app_name}.local"
readonly sysctl_file="/etc/sysctl.d/99-${app_name}-ddos.conf"

log() {
    printf '[三角洲口风琴] %s\n' "$*"
}

warn() {
    printf '[三角洲口风琴][警告] %s\n' "$*" >&2
}

fail() {
    printf '[三角洲口风琴][失败] %s\n' "$*" >&2
    exit 1
}

backup_file() {
    local source_file="$1"
    if [[ -e "$source_file" ]]; then
        cp -a "$source_file" "$backup_dir/$(basename "$source_file").before"
    fi
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || fail "请使用 sudo bash 执行此脚本。"
    command -v nginx >/dev/null 2>&1 || fail "未找到 nginx，已停止，未修改系统。"
    command -v systemctl >/dev/null 2>&1 || fail "未找到 systemctl，已停止，未修改系统。"
    command -v python3 >/dev/null 2>&1 || fail "未找到 python3，无法安全修改 Nginx 路由配置。"
}

find_route_file() {
    local result
    result="$(grep -RIl --include='*.conf' 'location /melodica/' /etc/nginx 2>/dev/null | head -n 1 || true)"
    if [[ -z "$result" ]]; then
        result="$(grep -RIl 'location /melodica/' /etc/nginx 2>/dev/null | head -n 1 || true)"
    fi
    [[ -n "$result" ]] || fail "未找到包含 /melodica/ 路由的 Nginx 配置，已停止，未修改系统。"
    printf '%s' "$result"
}

write_nginx_zone_file() {
    mkdir -p "$(dirname "$nginx_zone_file")"
    cat > "$nginx_zone_file" <<'EOF'
# 三角洲口风琴官网的边缘限速区，配置文件位于 Nginx 的 http 上下文中。
limit_req_zone $binary_remote_addr zone=delta_melodica_web:20m rate=20r/s;
limit_req_zone $binary_remote_addr zone=delta_melodica_api:20m rate=3r/s;
limit_conn_zone $binary_remote_addr zone=delta_melodica_conn:20m;

# 缩短异常连接占用资源的时间，不能替代云厂商的 DDoS 清洗。
client_header_timeout 10s;
client_body_timeout 10s;
send_timeout 15s;
keepalive_requests 100;
EOF
    chmod 0644 "$nginx_zone_file"
}

patch_route_file() {
    local route_file="$1"
    ROUTE_FILE="$route_file" python3 - <<'PY'
import os
from pathlib import Path

route_file = Path(os.environ["ROUTE_FILE"])
text = route_file.read_text(encoding="utf-8")


def find_block_end(source: str, signature: str):
    start = source.find(signature)
    if start < 0:
        return None
    opening = source.find("{", start)
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return opening, index
    return None


patches = {
    "location /melodica/ {": [
        "    # 官网静态页面按来源地址限速，避免单个攻击源耗尽 Nginx worker。",
        "    limit_req zone=delta_melodica_web burst=80 nodelay;",
        "    limit_conn delta_melodica_conn 40;",
        "    limit_req_status 429;",
        "    limit_conn_status 429;",
    ],
    "location /melodica/account-api/ {": [
        "    # 账号接口使用更严格的限速，保护验证码、登录和曲库接口。",
        "    limit_req zone=delta_melodica_api burst=15 nodelay;",
        "    limit_conn delta_melodica_conn 20;",
        "    limit_req_status 429;",
        "    limit_conn_status 429;",
    ],
    "location /melodica/api/ {": [
        "    # 统计接口使用更严格的限速，避免高频查询拖垮后端。",
        "    limit_req zone=delta_melodica_api burst=15 nodelay;",
        "    limit_conn delta_melodica_conn 20;",
        "    limit_req_status 429;",
        "    limit_conn_status 429;",
    ],
    "location = /melodica/api/stats {": [
        "    # 精确匹配的统计入口也必须纳入限速。",
        "    limit_req zone=delta_melodica_api burst=15 nodelay;",
        "    limit_conn delta_melodica_conn 20;",
        "    limit_req_status 429;",
        "    limit_conn_status 429;",
    ],
}

patched = []
for signature, directives in patches.items():
    block = find_block_end(text, signature)
    if block is None:
        continue
    opening, closing = block
    body = text[opening + 1 : closing]
    if "limit_req zone=delta_melodica_" in body:
        patched.append(signature + "（已存在，跳过）")
        continue
    insertion = "\n" + "\n".join(directives) + "\n"
    text = text[:closing] + insertion + text[closing:]
    patched.append(signature)

if not patched:
    raise SystemExit("没有找到可加入限速的目标 location。")

route_file.write_text(text, encoding="utf-8")
print("已处理：" + "、".join(patched))
PY
}

write_fail2ban_jail() {
    mkdir -p "$(dirname "$fail2ban_jail_file")"
    cat > "$fail2ban_jail_file" <<'EOF'
# 三角洲口风琴 SSH 暴力尝试防护。
[sshd]
enabled = true
backend = systemd
port = 22
maxretry = 5
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ::1
EOF
    chmod 0644 "$fail2ban_jail_file"
}

write_sysctl_file() {
    mkdir -p "$(dirname "$sysctl_file")"
    cat > "$sysctl_file" <<'EOF'
# 基础 TCP 抗连接洪泛设置，不能替代运营商或云厂商的 DDoS 清洗。
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 4096
net.core.somaxconn = 4096
EOF
    chmod 0644 "$sysctl_file"
}

main() {
    require_root
    mkdir -p "$backup_dir"
    chmod 0700 "$backup_dir"

    if ! nginx -t >/dev/null 2>&1; then
        fail "当前 Nginx 配置测试已经失败，请先修复现有配置，未修改系统。"
    fi

    local route_file
    route_file="$(find_route_file)"
    backup_file "$nginx_zone_file"
    backup_file "$route_file"
    backup_file "$fail2ban_jail_file"
    backup_file "$sysctl_file"

    log "写入 Nginx 限速区：$nginx_zone_file"
    write_nginx_zone_file
    log "修改官网/API 路由：$route_file"
    patch_route_file "$route_file"

    if ! nginx -t >/dev/null 2>&1; then
        warn "Nginx 配置测试失败，正在自动恢复本次修改。"
        cp -a "$backup_dir/$(basename "$route_file").before" "$route_file"
        if [[ -f "$backup_dir/$(basename "$nginx_zone_file").before" ]]; then
            cp -a "$backup_dir/$(basename "$nginx_zone_file").before" "$nginx_zone_file"
        else
            rm -f "$nginx_zone_file"
        fi
        nginx -t || true
        fail "Nginx 防护配置未应用；原配置已恢复。"
    fi

    if ! nginx -T 2>/dev/null | grep -Fq "$nginx_zone_file"; then
        warn "Nginx 没有加载 $nginx_zone_file，请检查 nginx.conf 是否包含 conf.d/*.conf。"
    fi

    log "重新加载 Nginx"
    systemctl reload nginx

    log "写入 TCP 基础防护参数"
    write_sysctl_file
    if command -v sysctl >/dev/null 2>&1; then
        sysctl --system >/dev/null 2>&1 || warn "TCP 参数未全部生效，请检查 sysctl 日志。"
    fi

    if ! command -v fail2ban-client >/dev/null 2>&1; then
        if command -v dnf >/dev/null 2>&1; then
            log "尝试安装 Fail2ban"
            dnf install -y fail2ban >/dev/null 2>&1 || warn "Fail2ban 安装失败，可能需要先启用 EPEL 仓库。"
        else
            warn "未找到 dnf，无法自动安装 Fail2ban。"
        fi
    fi

    if command -v fail2ban-client >/dev/null 2>&1; then
        write_fail2ban_jail
        if systemctl enable --now fail2ban >/dev/null 2>&1; then
            fail2ban-client status sshd >/dev/null 2>&1 || warn "Fail2ban 已启动，但 sshd 监狱状态读取失败。"
        else
            warn "Fail2ban 启动失败，请检查 journalctl -u fail2ban。"
        fi
    else
        warn "未启用 Fail2ban；Nginx 限速仍已应用。"
    fi

    log "防护配置已应用。备份目录：$backup_dir"
    log "已启用：Nginx 官网/API 限速、连接数限制、基础 TCP 参数、SSH Fail2ban（若安装成功）。"
    warn "仍必须在云厂商控制台开启 DDoS 清洗/WAF，并限制源站只接受 CDN/WAF 回源。"
    warn "本脚本不会修改云安全组，也不会把 SSH 端口自动开放给所有来源。"
}

main "$@"
