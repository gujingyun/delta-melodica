"""准备可离线分发的人声模型及引擎依赖许可证，仅由构建脚本调用。"""
import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import urllib.request


MODEL_NAME = "955717e8-8726e21a.th"
MODEL_SHA256 = "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
MODEL_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/" + MODEL_NAME


def prepare_models(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / MODEL_NAME
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != MODEL_SHA256:
        temporary = target.with_suffix(".download")
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=30) as response, temporary.open("wb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise ValueError("人声模型大小超出预期")
                    output.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_SHA256:
                raise ValueError("人声模型 SHA-256 校验失败")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    (folder / "htdemucs.yaml").write_text("models: ['955717e8']\n", encoding="utf-8")


def copy_licenses(folder):
    for distribution in importlib.metadata.distributions():
        for relative in distribution.files or []:
            if relative.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    destination = Path(folder) / distribution.metadata["Name"] / relative.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models")
    parser.add_argument("--licenses")
    args = parser.parse_args()
    if args.models:
        prepare_models(args.models)
    if args.licenses:
        copy_licenses(args.licenses)
