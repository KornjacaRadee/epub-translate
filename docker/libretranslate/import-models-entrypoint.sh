#!/bin/sh
set -eu

MODELS_DIR="${MODELS_DIR:-/models}"
PACKAGES_DIR="${PACKAGES_DIR:-/home/libretranslate/.local/share/argos-translate/packages}"

mkdir -p "$PACKAGES_DIR"

python3 - <<'PY'
from __future__ import annotations

import glob
import os
import zipfile
from pathlib import Path

models_dir = Path(os.environ.get("MODELS_DIR", "/models"))
packages_dir = Path(os.environ.get("PACKAGES_DIR", "/home/libretranslate/.local/share/argos-translate/packages"))
packages_dir.mkdir(parents=True, exist_ok=True)

for model_path_str in sorted(glob.glob(str(models_dir / "*.argosmodel"))):
    model_path = Path(model_path_str)
    if not zipfile.is_zipfile(model_path):
        print(f"Skipping non-zip Argos model: {model_path}")
        continue

    with zipfile.ZipFile(model_path) as archive:
        roots = sorted({name.split("/")[0] for name in archive.namelist() if name.strip("/")})
        if not roots:
            print(f"Skipping empty Argos model: {model_path}")
            continue
        root = roots[0]
        target_dir = packages_dir / root
        if target_dir.exists():
            print(f"Argos model already installed: {root}")
            continue
        print(f"Installing Argos model: {model_path.name} -> {target_dir}")
        archive.extractall(packages_dir)

try:
    import pwd
    import grp

    uid = pwd.getpwnam("libretranslate").pw_uid
    gid = grp.getgrnam("nogroup").gr_gid
    for current_root, dirnames, filenames in os.walk(packages_dir):
        os.chown(current_root, uid, gid)
        for name in dirnames:
            os.chown(os.path.join(current_root, name), uid, gid)
        for name in filenames:
            os.chown(os.path.join(current_root, name), uid, gid)
except Exception as exc:
    print(f"Skipping ownership adjustment: {exc}")
PY

exec ./scripts/entrypoint.sh "$@"
