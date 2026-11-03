"""push.sh 的目的地、配置保留和远端验证；git 网络命令全部 stub。"""
import os
import shutil
import subprocess

from test_oss_backup import BASH  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(_ROOT, "scripts", "push.sh")
REAL_GIT = shutil.which("git")


def _git(cwd, *args, env=None):
    return subprocess.run([REAL_GIT, *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "src.txt").write_text("v1", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "remote", "add", "origin", "https://github.com/example/repo.git")
    return repo


def _stub_env(tmp_path, repo):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "git"
    stub.write_text("""#!/bin/bash
if [ "$1" = "-c" ] && [ "$3" = "push" ]; then
  printf 'push %s\\n' "$*" >> "$STUB_LOG"
  printf 'raw-config:\\n' >> "$STUB_LOG"
  cat "$GIT_CONFIG_GLOBAL" >> "$STUB_LOG"
  printf 'include-config:\\n' >> "$STUB_LOG"
  include_path=$("$REAL_GIT" config --file "$GIT_CONFIG_GLOBAL" --get include.path)
  if [ -n "$include_path" ]; then cat "$include_path" >> "$STUB_LOG"; fi
  "$REAL_GIT" config --show-origin --get-all credential.helper >> "$STUB_LOG" || true
  exit 0
fi
if [ "$1" = "-c" ]; then
  printf 'unexpected-global-option %s\\n' "$*" >> "$STUB_LOG"
  exit 99
fi
if [ "$1" = "push" ]; then
  printf 'push %s\\n' "$*" >> "$STUB_LOG"
  "$REAL_GIT" config --get-regexp credential >> "$STUB_LOG" || true
  exit 0
fi
if [ "$1" = "ls-remote" ]; then
  if [ -n "${STUB_REMOTE_FAIL:-}" ]; then exit 1; fi
  printf 'ls-remote %s\\n' "$*" >> "$STUB_LOG"
  printf '%s refs/heads/%s\\n' "$STUB_SHA" "$3"
  exit 0
fi
printf 'git %s\\n' "$*" >> "$STUB_LOG"
exec "$REAL_GIT" "$@"
""", encoding="utf-8")
    stub.chmod(0o755)
    env = {key: os.environ[key] for key in
           ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")
           if key in os.environ}
    env.update({
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "REAL_GIT": REAL_GIT,
        "GIT_BIN": str(stub),
        "STUB_LOG": str(tmp_path / "commands.log"),
        "STUB_SHA": _git(repo, "rev-parse", "refs/heads/main").stdout.strip(),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "global.gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "system.gitconfig"),
    })
    (tmp_path / "system.gitconfig").write_text("", encoding="utf-8")
    (tmp_path / "global.gitconfig").write_text(
        '[credential]\n\thelper = custom-helper\n'
        '[url "file:///mirror.git/"]\n\tinsteadOf = https://github.com/\n',
        encoding="utf-8")
    return env


def _run(repo, env, branch="main"):
    return subprocess.run([BASH, SCRIPT, "origin", branch], cwd=repo, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)


def _log(env):
    if not os.path.exists(env["STUB_LOG"]):
        return ""
    with open(env["STUB_LOG"], encoding="utf-8") as handle:
        return handle.read()


def test_push_preserves_credentials_and_verifies_remote(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    result = _run(repo, env)
    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(env)
    assert "push origin refs/heads/main:refs/heads/main" in log
    assert "ls-remote origin refs/heads/main" in log
    assert "custom-helper" in log
    assert "mirror.git" not in log


def test_included_credential_helper_is_preserved(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    include = tmp_path / "credentials.inc"
    include.write_text("[credential]\n\thelper = custom-include\n", encoding="utf-8")
    with open(env["GIT_CONFIG_GLOBAL"], "a", encoding="utf-8") as handle:
        handle.write(f"[include]\n\tpath = {include.as_posix()}\n")
    result = _run(repo, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "custom-include" in _log(env)
    assert include.read_text(encoding="utf-8") == "[credential]\n\thelper = custom-include\n"
    assert "mirror.git" not in _log(env)


def test_branch_sha_is_used_instead_of_head(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    _git(repo, "checkout", "-b", "feature")
    (repo / "src.txt").write_text("v2", encoding="utf-8")
    _git(repo, "add", "src.txt")
    _git(repo, "commit", "-m", "feature")
    env["STUB_SHA"] = _git(repo, "rev-parse", "refs/heads/main").stdout.strip()
    result = _run(repo, env, "main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ls-remote origin refs/heads/main" in _log(env)


def test_remote_verification_failure_is_not_success(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    env["STUB_REMOTE_FAIL"] = "1"
    result = _run(repo, env)
    assert result.returncode != 0
    assert "远端验证失败" in result.stdout + result.stderr
    assert "验证通过" not in result.stdout + result.stderr


def test_non_github_destination_is_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    _git(repo, "remote", "set-url", "origin", "file:///mirror.git")
    result = _run(repo, env)
    assert result.returncode != 0
    assert "目的地" in result.stdout + result.stderr
    assert "push origin refs" not in _log(env)


def test_repository_url_rewrite_is_rejected(tmp_path):
    repo = _make_repo(tmp_path)
    env = _stub_env(tmp_path, repo)
    _git(repo, "config", "--local", "url.file:///mirror.git/.insteadOf",
         "https://github.com/")
    result = _run(repo, env)
    assert result.returncode != 0
    assert "仓库级" in result.stdout + result.stderr
    assert "push origin refs" not in _log(env)
