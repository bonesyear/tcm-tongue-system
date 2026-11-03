#!/usr/bin/env python3
"""Scan new git commits without printing secrets or skipping text variants."""
import argparse
import json
import os
import re
import subprocess
import sys

CREDENTIAL_RE = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}"
    r"|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|LTAI[A-Za-z0-9]{12,}|AKLT[A-Za-z0-9]{10,}"
    r"|AIza[A-Za-z0-9_-]{30,}|xoxb-|BEGIN [A-Z ]*PRIVATE KEY",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"}


def git_bytes(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True).stdout


def git_text(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def load_words(path):
    with open(path, encoding="utf-8-sig") as handle:
        return [line.strip() for line in handle
                if line.strip() and not line.lstrip().startswith("#")]


def variants(word):
    return {word.casefold(), json.dumps(word, ensure_ascii=True)[1:-1].casefold()}


def decode_blob(data, path):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if b"\0" in data:
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            printable = sum(char.isprintable() or char.isspace() for char in text)
            if printable / max(1, len(text)) > 0.85:
                return text
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
            return data.decode("latin-1")
        raise ValueError("无法确认文本编码，需人工复核")


def iter_blobs(repo, commit):
    tree = git_bytes(repo, "ls-tree", "-r", "-z", commit)
    for item in tree.split(b"\0"):
        if not item:
            continue
        meta, path_bytes = item.split(b"\t", 1)
        fields = meta.split()
        if len(fields) < 3 or fields[1] != b"blob":
            continue
        path = os.fsdecode(path_bytes)
        data = git_bytes(repo, "cat-file", "blob", fields[2].decode("ascii"))
        yield path, data


def safe_path(path, words):
    folded = path.casefold()
    if any(word and word.casefold() in folded for word in words):
        return "<sensitive-path>"
    return path


def scan_text(text, words, fingerprints, path, commit, findings):
    folded = text.casefold()
    for index, word in enumerate(words, 1):
        for variant in variants(word):
            position = folded.find(variant)
            if position >= 0:
                findings.append(("word", index, commit, path,
                                 text[:position].count("\n") + 1))
                break
    if CREDENTIAL_RE.search(text):
        findings.append(("pattern", None, commit, path, None))
    for variable, fragment in fingerprints:
        if fragment.casefold() in folded:
            findings.append(("fingerprint", variable, commit, path, None))


def env_paths(repo):
    configured = os.environ.get("_PRIVACY_ENV_FILES", "")
    if configured.startswith("["):
        return json.loads(configured)
    if configured:
        return configured.split(os.pathsep) if os.pathsep in configured \
            else configured.split()
    return [os.path.join(repo, ".env"),
            os.path.expanduser("~/.config/tcm-tongue/.env"),
            os.path.expanduser("~/.hermes/profiles/tcm-tongue/.env"),
            os.path.expanduser("~/.hermes/.env")]


def load_fingerprints(repo):
    fingerprints = []
    for path in env_paths(repo):
        try:
            with open(path, encoding="utf-8-sig") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            variable, value = line.split("=", 1)
            if not re.search(r"KEY|TOKEN|SECRET|PASS|PWD|CREDENTIAL|_ID|ID_",
                             variable, re.IGNORECASE):
                continue
            value = value.strip().strip('"').strip("'")
            if len(value) >= 20:
                fingerprints.append((variable.strip(), value[:14]))
    return fingerprints


def scan_commit(repo, commit, words, fingerprints):
    findings = []
    for path, data in iter_blobs(repo, commit):
        folded_path = path.casefold()
        for index, word in enumerate(words, 1):
            if any(variant in folded_path for variant in variants(word)):
                findings.append(("path", index, commit, path, None))
        try:
            text = decode_blob(data, path)
        except ValueError as error:
            findings.append(("binary", str(error), commit, path, None))
            continue
        if path == "scripts/hooks/privacy_scan.py":
            text = re.sub(r"CREDENTIAL_RE = re\.compile\([\s\S]*?\n\)\n",
                          "", text, count=1)
        scan_text(text, words, fingerprints, path, commit, findings)
    message = git_text(repo, "log", "-1", "--format=%B", commit)
    scan_text(message, words, fingerprints, "<commit-message>", commit, findings)
    return findings


def scan_tag(repo, tag, words, fingerprints):
    findings = []
    text = git_text(repo, "cat-file", "tag", tag)
    scan_text(text, words, fingerprints, "<tag-message>", tag, findings)
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--words", required=True)
    parser.add_argument("--commits", default="")
    parser.add_argument("--tag")
    args = parser.parse_args()
    repo = os.path.abspath(args.repo)
    try:
        words = load_words(args.words)
    except (OSError, UnicodeError) as error:
        print(f"敏感词表不可用，拒绝放行: {error}", file=sys.stderr)
        return 2
    fingerprints = load_fingerprints(repo)
    findings = []
    for commit in args.commits.split():
        findings.extend(scan_commit(repo, commit, words, fingerprints))
    if args.tag:
        findings.extend(scan_tag(repo, args.tag, words, fingerprints))
    for kind, detail, commit, path, line in findings:
        location = safe_path(path, words)
        if line:
            location += f":{line}"
        if kind == "word":
            print(f"敏感词规则 #{detail} 命中（不输出词及行内容）: {commit[:10]} {location}",
                  file=sys.stderr)
        elif kind == "path":
            print(f"文件路径含敏感词（不输出路径）: {commit[:10]}", file=sys.stderr)
        elif kind == "pattern":
            print(f"疑似凭证模式命中: {commit[:10]} {location}", file=sys.stderr)
        elif kind == "fingerprint":
            print(f"真实凭证指纹命中（变量 {detail}）: {commit[:10]} {location}",
                  file=sys.stderr)
        else:
            print(f"{detail}: {commit[:10]} {location}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
