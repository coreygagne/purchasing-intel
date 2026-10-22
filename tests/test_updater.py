"""The in-place updater: a newer 'Download ZIP' replaces the app's files and keeps keys and saved research."""

import io
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from scripts import update_from_download as up

ROOT = Path(__file__).resolve().parents[1]


def make_app(tmp: Path) -> Path:
    app = tmp / "Documents" / "purchasing-intel-main"
    (app / "app").mkdir(parents=True)
    (app / "data").mkdir()
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / "app" / "main.py").write_text("OLD")
    (app / "app" / "removed_later.py").write_text("stale")
    (app / "requirements.txt").write_text("old")
    (app / "Start Purchasing Research.command").write_text("old")
    (app / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-keep-me\n")
    (app / "data" / "purchasing.db").write_text("saved research")
    (app / ".venv" / "bin" / "python").write_text("venv")
    return app


def make_zip(path: Path, files: dict[str, str], top: str = "purchasing-intel-main", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            info = zipfile.ZipInfo(f"{top}/{name}")
            info.external_attr = (0o755 if name.endswith((".command", ".sh")) else 0o644) << 16
            z.writestr(info, text)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


NEW = {"app/main.py": "NEW", "app/added.py": "added", "requirements.txt": "new",
       "Start Purchasing Research.command": "#!/bin/bash\necho new", "run.sh": "#!/bin/bash"}


def test_first_run_only_records_the_install(tmp_path):
    app = make_app(tmp_path)
    make_zip(tmp_path / "Downloads" / "purchasing-intel-main.zip", NEW)
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads"), "--yes"]) == 0
    assert (app / up.MARKER).exists() and (app / "app" / "main.py").read_text() == "OLD"


def test_newer_download_updates_and_keeps_keys_research_and_venv(tmp_path):
    app = make_app(tmp_path)
    (app / up.MARKER).touch()
    os.utime(app / up.MARKER, (time.time() - 60, time.time() - 60))
    make_zip(tmp_path / "Downloads" / "purchasing-intel-main (1).zip", NEW)
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads"), "--yes"]) == up.UPDATED
    assert (app / "app" / "main.py").read_text() == "NEW" and (app / "app" / "added.py").exists()
    assert not (app / "app" / "removed_later.py").exists()  # the app's folders mirror the new version
    assert (app / ".env").read_text() == "ANTHROPIC_API_KEY=sk-ant-keep-me\n"
    assert (app / "data" / "purchasing.db").read_text() == "saved research"
    assert (app / ".venv" / "bin" / "python").read_text() == "venv"
    assert os.access(app / "Start Purchasing Research.command", os.X_OK)
    # the same download isn't applied twice
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads"), "--yes"]) == 0


def test_older_download_is_ignored_and_no_means_no(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    (app / up.MARKER).touch()
    make_zip(tmp_path / "Downloads" / "purchasing-intel-main.zip", NEW, mtime=time.time() - 3600)
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads")]) == 0
    os.utime(app / up.MARKER, (time.time() - 7200, time.time() - 7200))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads")]) == 0
    assert (app / "app" / "main.py").read_text() == "OLD"
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads")]) == 0  # not asked again


@pytest.mark.parametrize("files,top", [({"app/main.py": "x"}, "purchasing-intel-main"),  # not the app
                                       ({**NEW, "../../evil.txt": "x"}, "purchasing-intel-main")])  # zip slip
def test_bad_downloads_change_nothing(tmp_path, files, top):
    app = make_app(tmp_path)
    (app / up.MARKER).touch()
    os.utime(app / up.MARKER, (time.time() - 60, time.time() - 60))
    make_zip(tmp_path / "Downloads" / "purchasing-intel-main.zip", files, top)
    assert up.main([str(app), "--downloads", str(tmp_path / "Downloads"), "--yes"]) == 1
    assert (app / "app" / "main.py").read_text() == "OLD" and not (tmp_path / "evil.txt").exists()


def test_safari_unzipped_folder_and_the_real_github_zip_layout(tmp_path):
    """GitHub's Download ZIP is `git archive` with a <repo>-<branch>/ prefix: apply this repo's own archive."""
    app = make_app(tmp_path)
    (app / up.MARKER).touch()
    os.utime(app / up.MARKER, (time.time() - 60, time.time() - 60))
    dl = tmp_path / "Downloads"
    dl.mkdir()
    archive = subprocess.run(["git", "archive", "--format=zip", "--prefix=purchasing-intel-main/", "HEAD"],
                             cwd=ROOT, capture_output=True, check=True).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        z.extractall(dl)  # what Safari does with the download
    assert up.main([str(app), "--downloads", str(dl), "--yes"]) == up.UPDATED
    assert (app / "app" / "research.py").exists() and (app / "scripts" / "smoke_test.py").exists()
    assert (app / ".env").read_text() == "ANTHROPIC_API_KEY=sk-ant-keep-me\n"
    assert not (app / "app" / "removed_later.py").exists()
