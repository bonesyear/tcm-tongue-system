"""pre-push 的真实本地 git 行为；所有仓库、词表和凭证均为合成数据。"""
import json
import os
import shutil
import subprocess

import pytest

from test_oss_backup import BASH  # noqa: E402

SECRET = "隐私" + "哨兵"
ASCII_SECRET = "Example" + " Person"
FAKE_KEY = "sk-" + "x" * 24
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(tmp_path, extra=None):
    env = {key: os.environ[key] for key in
           ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")
           if key in os.environ}
    env.update({"HOME": str(tmp_path / "home"),
                "USERPROFILE": str(tmp_path / "home"),
                "PYTHONIOENCODING": "utf-8"})
    if extra:
        env.update(extra)
    return env


def _run(cwd, *args, env=None, check=True):
    env = _env(cwd) if env is None else env
    return subprocess.run(args, cwd=cwd, env=env, check=check,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)


def _git(cwd, *args, env=None):
    return _run(cwd, "git", *args, env=env)


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote), env=_env(tmp_path))
    _git(repo, "init", "-b", "main", env=_env(tmp_path))
    _git(repo, "config", "user.email", "test@example.invalid", env=_env(tmp_path))
    _git(repo, "config", "user.name", "Test", env=_env(tmp_path))
    hooks = repo / "scripts" / "hooks"
    hooks.mkdir(parents=True)
    for name in ("pre-push", "privacy_scan.py"):
        target = hooks / name
        shutil.copyfile(os.path.join(_ROOT, "scripts", "hooks", name), target)
        target.chmod(0o755)
    _git(repo, "config", "core.hooksPath", "scripts/hooks", env=_env(tmp_path))
    (repo / ".gitignore").write_text(".privacy-words\n", encoding="utf-8")
    (repo / ".privacy-words").write_text(
        f"{SECRET}\n{ASCII_SECRET}\n", encoding="utf-8")
    (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## v1.0.0\n", encoding="utf-8")
    _git(repo, "add", ".", env=_env(tmp_path))
    _git(repo, "commit", "-m", "initial", env=_env(tmp_path))
    _git(repo, "remote", "add", "origin", str(remote), env=_env(tmp_path))
    return repo


def _commit(repo, name, content, message="update"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", message)


def _push(repo, ref="main", force=False):
    args = ["git", "push", "origin", ref]
    if force:
        args.insert(2, "--force")
    return _run(repo, *args, check=False)


def test_clean_push_is_allowed(tmp_path):
    repo = _make_repo(tmp_path)
    result = _push(repo)
    assert result.returncode == 0, (result.stdout + result.stderr)


def test_root_commit_message_is_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "note.md", "clean", message=SECRET)
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_middle_commit_cannot_be_hidden_by_deletion(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "note.md", SECRET)
    assert _push(repo).returncode == 1
    _git(repo, "rm", "note.md")
    _git(repo, "commit", "-m", "remove")
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_utf16_content_is_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "utf16.md", SECRET.encode("utf-16"))
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_json_unicode_escape_is_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "record.json", json.dumps({"name": SECRET}, ensure_ascii=True))
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_ascii_case_and_filename_are_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "ascii.md", ASCII_SECRET.lower())
    assert _push(repo).returncode == 1
    _commit(repo, f"{SECRET}.md", "clean")
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_unknown_binary_fails_closed(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "payload.bin", b"\x80\x81\x82")
    result = _push(repo)
    assert result.returncode == 1
    assert "无法确认文本编码" in (result.stdout + result.stderr)


def test_hooks_directory_is_not_an_exemption(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "scripts/hooks/note.txt", SECRET)
    result = _push(repo)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_fingerprint_and_log_masking(tmp_path):
    repo = _make_repo(tmp_path)
    env_file = tmp_path / "fake.env"
    env_file.write_text(f"VISION_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    _commit(repo, "leaked.cfg", FAKE_KEY)
    result = _run(repo, "git", "push", "origin", "main", check=False,
                  env=_env(tmp_path, {"_PRIVACY_ENV_FILES": json.dumps([str(env_file)])}))
    assert result.returncode == 1
    assert FAKE_KEY not in (result.stdout + result.stderr)
    assert "VISION_API_KEY" in (result.stdout + result.stderr)


def test_missing_words_file_fails_closed(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / ".privacy-words").unlink()
    result = _push(repo)
    assert result.returncode == 1
    assert "未找到敏感词表" in (result.stdout + result.stderr)


def test_worktree_uses_main_words_file(tmp_path):
    repo = _make_repo(tmp_path)
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", str(worktree), "-b", "feature")
    _commit(worktree, "note.md", SECRET)
    result = _push(worktree, "feature")
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_annotated_tag_message_is_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    _git(repo, "tag", "-a", "v1.0.0", "-m", SECRET)
    result = _push(repo, "v1.0.0")
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_force_push_with_unknown_remote_sha_is_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    assert _push(repo).returncode == 0
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-b", "main", str(tmp_path / "remote.git"), str(other))
    _git(other, "config", "user.email", "test@example.invalid")
    _git(other, "config", "user.name", "Test")
    _commit(other, "other.md", "clean")
    _git(other, "push", "origin", "HEAD:main", "--no-verify")
    _commit(repo, "note.md", SECRET)
    result = _push(repo, force=True)
    assert result.returncode == 1
    assert SECRET not in (result.stdout + result.stderr)


def test_version_hint_does_not_add_extra_v(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "VERSION").write_text("0.9.9\n", encoding="utf-8")
    _git(repo, "add", "VERSION")
    _git(repo, "commit", "-m", "version")
    result = _push(repo)
    assert result.returncode == 1
    assert "不带 v" in (result.stdout + result.stderr)
    assert "改成 vv" not in (result.stdout + result.stderr)


def test_words_are_trimmed(tmp_path):
    repo = _make_repo(tmp_path)
    with (repo / ".privacy-words").open("a", encoding="utf-8") as handle:
        handle.write(f"  {SECRET}  \n")
    _commit(repo, "note.md", SECRET)
    assert _push(repo).returncode == 1


def test_unreleased_version_section_is_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    _commit(repo, "CHANGELOG.md", "## v1.0.0\n\n## Unreleased\n")
    result = _push(repo)
    assert result.returncode == 1
    assert "Unreleased" in (result.stdout + result.stderr)
