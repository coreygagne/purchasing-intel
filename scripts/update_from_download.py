"""Update this copy of Purchasing Research from a newer download in the Downloads folder.

    python -I scripts/update_from_download.py APP_DIR [--downloads DIR] [--yes]

The starters run this before starting the app. It looks for the GitHub "Download ZIP" file
(purchasing-intel-main.zip, or "purchasing-intel-main (1).zip", or the folder Safari unzips it to) that is newer
than this copy's last install, asks once, and copies the new version over this folder. Your keys (.env), saved
research (data) and the app's Python environment (.venv) are never touched.

Exit codes: 0 nothing to do (or you said no), 3 updated (the starter then restarts itself), 1 the download
couldn't be used (the app still starts as it was).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

MARKER = ".installed-at"
# never overwritten or removed: your settings, saved research, Python environment and this marker
KEEP = {".env", "data", ".venv", MARKER, ".DS_Store"}
# folders that belong to the app: mirrored exactly, so files removed from the app are removed here too
MIRRORED = ("app", "scripts", "tests")
REQUIRED = ("app/main.py", "requirements.txt", "Start Purchasing Research.command")
EXECUTABLE = ("Start Purchasing Research.command", "run.sh")
UPDATED = 3


def _kept(rel: Path) -> bool:
    top = rel.parts[0]
    return top in KEEP or top.startswith("data-replaced-") or top.startswith(".env")


def candidates(downloads: Path, app: Path) -> list[Path]:
    out = []
    for p in downloads.glob("purchasing-intel-main*"):
        if p.suffix == ".zip" or (p.is_dir() and (p / "app" / "main.py").exists()):
            try:
                if p.is_dir() and p.resolve() == app.resolve():
                    continue  # this copy itself
            except OSError:
                continue
            out.append(p)
    return out


def _safe_extract(zip_path: Path, dest: Path) -> Path:
    """Extract the GitHub ZIP (one top folder) and return that folder. Refuses paths outside dest."""
    with zipfile.ZipFile(zip_path) as z:
        tops = {n.split("/", 1)[0] for n in z.namelist() if n.strip("/")}
        if len(tops) != 1:
            raise ValueError("it isn't a single-folder app download")
        root = dest.resolve()
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(root) + os.sep) and target != root:
                raise ValueError("it contains paths outside its folder")
            z.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                os.chmod(target, mode)
        return dest / tops.pop()


def _check(src: Path) -> None:
    missing = [r for r in REQUIRED if not (src / r).exists()]
    if missing:
        raise ValueError(f"it doesn't look like Purchasing Research (missing {', '.join(missing)})")


def apply(src: Path, app: Path) -> int:
    """Copy src over app, keeping KEEP; mirror the app's own folders. Returns the number of files written."""
    written = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if _kept(rel) or "__pycache__" in rel.parts:
            continue
        target = app / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".updating")
        shutil.copy2(path, tmp)
        os.replace(tmp, target)  # a running starter keeps reading its old copy until it restarts
        written += 1
    for folder in MIRRORED:
        root = app / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            rel = path.relative_to(app)
            if "__pycache__" in rel.parts or (src / rel).exists():
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    for name in EXECUTABLE:
        p = app / name
        if p.exists():
            p.chmod(p.stat().st_mode | 0o111)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("app", type=Path)
    ap.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    ap.add_argument("--yes", action="store_true", help="don't ask")
    args = ap.parse_args(argv)
    app = args.app.resolve()
    marker = app / MARKER
    if not marker.exists():
        marker.touch()  # first run with this updater: downloads before now are the version already here
        return 0
    if not args.downloads.is_dir():
        return 0
    since = marker.stat().st_mtime
    newer = [p for p in candidates(args.downloads, app) if p.stat().st_mtime > since]
    if not newer:
        return 0
    newest = max(newer, key=lambda p: p.stat().st_mtime)
    when = time.strftime("%b %d at %H:%M", time.localtime(newest.stat().st_mtime))
    print(f"A newer version was downloaded ({newest.name}, {when}).")
    if not args.yes:
        try:
            answer = input("Update this copy now? Your keys and saved research are kept. [Y/n] ").strip().lower()
        except EOFError:
            answer = ""
        if answer.startswith("n"):
            marker.touch()  # don't ask again for this download
            print("Not updated. Starting the version you have.")
            return 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = newest if newest.is_dir() else _safe_extract(newest, Path(tmp))
            _check(src)
            n = apply(src, app)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Couldn't update from {newest.name}: {exc}. Starting the version you have.")
        return 1
    marker.touch()
    print(f"Updated ({n} files). Your keys and saved research were kept. You can delete {newest.name} from "
          "Downloads.")
    return UPDATED


if __name__ == "__main__":
    sys.exit(main())
