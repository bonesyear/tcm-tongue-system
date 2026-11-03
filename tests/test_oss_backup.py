"""OSS 备份白名单与清单可靠性；本地 stub，不访问真实 OSS。"""
import os
import shutil
import subprocess
import tarfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(_ROOT, "scripts", "backup_to_oss.sh")


def _find_bash():
    candidates = [os.environ.get("BASH"),
                  "C:/Users/sming/AppData/Local/hermes/git/bin/bash.exe",
                  "C:/Program Files/Git/bin/bash.exe",
                  "C:/Program Files/Git/usr/bin/bash.exe",
                  shutil.which("bash")]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError("未找到可用 Bash")


BASH = _find_bash()


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


def _make_repo(tmp_path):
    repo = tmp_path / "charts" / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text(
        "records/\ncharts/\n.env\n.privacy-words\n.claude/\ndocs/*_TASK_*.md\n",
        encoding="utf-8")
    (repo / "src.txt").write_text("v1", encoding="utf-8")
    (repo / ".env.example").write_text("VISION_MODEL=example\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "public.md").write_text("public", encoding="utf-8")
    _git(repo, "add", ".")
    sensitive = {
        ".env": "FAKE_KEY=not-a-real-key",
        ".privacy-words": "测试姓名",
        "_books/book.epub": "fake book",
        "docs/private.pdf": "fake pdf",
        "docs/x_TASK_private.md": "private task",
        ".claude/private.txt": "private",
    }
    for name, content in sensitive.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (repo / "records" / "photos").mkdir(parents=True)
    (repo / "records" / "photos" / "photo.jpg").write_bytes(b"fake")
    (repo / "charts").mkdir()
    (repo / "charts" / "chart.png").write_bytes(b"fake")
    _git(repo, "add", "-f", *sensitive)
    _git(repo, "commit", "-m", "initial")
    return repo


def _stub_env(tmp_path, repo):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "ossutil"
    stub.write_text('#!/bin/bash\ncp "$3" "$STUB_COPY"\n', encoding="utf-8")
    stub.chmod(0o755)
    env = {key: os.environ[key] for key in
           ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")
           if key in os.environ}
    env.update({
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
        "TCM_SYSTEM_DIR": str(repo),
        "TCM_OSS_BUCKET": "test-bucket",
        "STUB_COPY": str(tmp_path / "upload.tar.gz"),
    })
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return env


def _run(repo, env):
    return subprocess.run([BASH, SCRIPT], cwd=repo, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=30)


def test_backup_excludes_sensitive_files_even_when_tracked(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    result = _run(repo, env)
    assert result.returncode == 0, result.stderr
    with tarfile.open(env["STUB_COPY"], "r:gz") as archive:
        names = archive.getnames()
    assert "src.txt" in names and "docs/public.md" in names
    assert ".env.example" in names
    assert not [name for name in names if (
        (name.startswith(".env") and name != ".env.example")
        or name.startswith((".privacy-words", "_books/", "records/", "charts/", ".claude/"))
        or name.endswith((".pdf", ".epub")) or "_TASK_" in name)]


def test_missing_bucket_is_rejected_before_backup(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    env.pop("TCM_OSS_BUCKET")
    result = _run(repo, env)
    assert result.returncode == 2
    assert not os.path.exists(env["STUB_COPY"])


def test_corrupt_manifest_warns_and_recovers(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    assert _run(repo, env).returncode == 0
    (repo / ".backup_manifest").write_text("", encoding="utf-8")
    result = _run(repo, env)
    assert result.returncode == 0, result.stderr
    assert "备份清单缺少 hash" in result.stderr
    assert os.path.exists(env["STUB_COPY"])


def test_tracked_change_detected_under_charts_parent(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    assert _run(repo, env).returncode == 0
    (repo / "src.txt").write_text("v2", encoding="utf-8")
    result = _run(repo, env)
    assert result.returncode == 0, result.stderr
    assert "内容无变化" not in result.stdout
    assert os.path.exists(env["STUB_COPY"])
