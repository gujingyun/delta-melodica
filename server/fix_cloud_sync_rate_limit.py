"""为私有曲库配置独立限流，避免批量同步被登录接口的限速拦截。"""

import argparse
from datetime import datetime
from pathlib import Path
import re
import subprocess


SIGNATURE = "location /melodica/account-api/ {"
SYNC_SIGNATURE = "location ^~ /melodica/account-api/library/ {"
ZONE = "limit_req_zone $binary_remote_addr zone=delta_sync_guard:16m rate=12r/s;"


def patch_config(text):
    if SYNC_SIGNATURE in text:
        return text
    start = text.find(SIGNATURE)
    if start < 0:
        raise ValueError("未找到账号接口配置，停止修改")
    opening = text.index("{", start)
    closing = text.index("}", opening)
    body = text[opening + 1:closing]
    if "{" in body or "proxy_pass http://127.0.0.1:3003/;" not in body:
        raise ValueError("账号接口配置与预期不同，停止修改")
    body = re.sub(r"^.*limit_req(?:_status)?\s+.*$", "", body, flags=re.M)
    # 新 location 多一层路径，转发时必须保留后端的 /library/ 前缀。
    body = body.replace("proxy_pass http://127.0.0.1:3003/;",
                        "proxy_pass http://127.0.0.1:3003/library/;")
    block = ("\n\n# 曲库连续同步独立排队，不消耗登录及验证码的限流额度。\n"
             + SYNC_SIGNATURE + body
             + "\n    limit_req zone=delta_sync_guard burst=30;\n"
             + "    limit_req_status 429;\n}\n")
    return text[:closing + 1] + block + text[closing + 1:]


def patch_zones(text):
    if "zone=delta_sync_guard:" in text:
        if ZONE not in text:
            raise ValueError("已有不同的曲库限流配置，停止修改")
        return text
    return text.rstrip() + "\n" + ZONE + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--zones", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    paths = [Path(args.config), Path(args.zones)]
    originals = [path.read_bytes() for path in paths]
    updated = [patch_config(originals[0].decode()), patch_zones(originals[1].decode())]
    if not args.apply:
        print("配置检查通过；使用 --apply 备份、校验并重载 Nginx")
        return
    subprocess.check_call(["nginx", "-t"])
    backup = Path("/var/backups/delta-cloud-sync-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(mode=0o700)
    for index, original in enumerate(originals):
        (backup / (str(index) + ".before")).write_bytes(original)
    try:
        for path, text in zip(paths, updated):
            path.write_text(text, encoding="utf-8")
        subprocess.check_call(["nginx", "-t"])
        subprocess.check_call(["nginx", "-s", "reload"])
    except Exception:
        for path, original in zip(paths, originals):
            path.write_bytes(original)
        subprocess.check_call(["nginx", "-t"])
        subprocess.check_call(["nginx", "-s", "reload"])
        raise
    print("已修复曲库同步限流；备份目录：" + str(backup))


if __name__ == "__main__":
    main()
