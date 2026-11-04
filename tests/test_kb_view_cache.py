import concurrent.futures
from pathlib import Path

import pytest

from kb_evidence import _kb_references_unified
from test_kb_unified import _ALL_ANCHORS, _corpus, _record, _signature


def _capture_views(monkeypatch):
    import kb_evidence
    seen = []
    original = kb_evidence._kb_references

    def capture(rec, kb_root=None, anchor_terms=None, syn_map=None):
        seen.append(kb_root)
        return original(rec, kb_root=kb_root, anchor_terms=anchor_terms, syn_map=syn_map)

    monkeypatch.setattr(kb_evidence, '_kb_references', capture)
    return seen


def test_unified_reuses_view_for_same_version(tmp_path, monkeypatch):
    from src.retrieval import dispatcher, grep_search, synonym_loader
    _, roots = _corpus(tmp_path)
    seen = _capture_views(monkeypatch)
    first = _kb_references_unified(_record(), roots, _ALL_ANCHORS)
    caches = (len(dispatcher._RAG_CACHE), len(grep_search._FILE_CACHE),
              len(synonym_loader._CACHE))
    second = _kb_references_unified(_record(), roots, _ALL_ANCHORS)
    assert _signature(second) == _signature(first)
    assert seen[0] == seen[1]
    assert (len(dispatcher._RAG_CACHE), len(grep_search._FILE_CACHE),
            len(synonym_loader._CACHE)) == caches


def test_unified_concurrent_readers_build_only_once(tmp_path, monkeypatch):
    import shutil
    _, roots = _corpus(tmp_path)
    seen = _capture_views(monkeypatch)
    copies = []
    original_copy = shutil.copyfile

    def counted_copy(source, target):
        copies.append(source)
        return original_copy(source, target)

    monkeypatch.setattr(shutil, 'copyfile', counted_copy)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: _kb_references_unified(_record(), roots, _ALL_ANCHORS), range(4)))
    assert all(_signature(result) == _signature(results[0]) for result in results)
    assert len(set(seen)) == 1
    assert len(copies) == 4


def test_unified_cache_detects_same_stat_content_change(tmp_path, monkeypatch):
    import os
    _, roots = _corpus(tmp_path)
    source = tmp_path / 'diet' / 'diet-lifestyle' / 'version.md'
    source.write_text('版本标记甲', encoding='utf-8')
    seen = _capture_views(monkeypatch)
    cache = tmp_path / 'cache'
    first = _kb_references_unified(_record(), roots, ['版本标记'], cache_root=cache)
    stat = source.stat()
    source.write_text('版本标记乙', encoding='utf-8')
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = _kb_references_unified(_record(), roots, ['版本标记'], cache_root=cache)
    assert seen[0] != seen[1]
    assert first[0]['excerpt'].endswith('甲')
    assert second[0]['excerpt'].endswith('乙')


def test_unified_cleans_recognized_staging(tmp_path):
    import kb_view
    _, roots = _corpus(tmp_path)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / kb_view._CACHE_MARKER).write_text('1\n', encoding='utf-8')
    staging = cache / f".{'a' * 64}.staging-dead"
    staging.mkdir()
    (staging / 'partial.md').write_text('崩溃暂存', encoding='utf-8')
    unrelated = cache / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'keep.txt').write_text('保留', encoding='utf-8')
    assert _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    assert not staging.exists()
    assert (unrelated / 'keep.txt').read_text(encoding='utf-8') == '保留'


def test_app_startup_cleans_recognized_staging(tmp_path):
    import kb_view
    from app import create_app
    cache = tmp_path / 'data' / 'cache' / 'kb-unified'
    cache.mkdir(parents=True)
    (cache / kb_view._CACHE_MARKER).write_text('1\n', encoding='utf-8')
    staging = cache / f".{'b' * 64}.staging-dead"
    staging.mkdir()
    (staging / 'partial.md').write_text('崩溃暂存', encoding='utf-8')
    create_app(env_file=str(tmp_path / '.env'), data_root=str(tmp_path / 'data'))
    assert not staging.exists()


def test_unified_prunes_stale_views_and_invalidates(tmp_path, monkeypatch):
    import os
    import time
    import kb_view
    from src.retrieval import dispatcher
    monkeypatch.setattr(kb_view, '_MAX_CACHED_VIEWS', 2)
    _, roots = _corpus(tmp_path)
    source = tmp_path / 'diet' / 'diet-lifestyle' / 'version.md'
    seen = _capture_views(monkeypatch)
    cache = tmp_path / 'cache'
    previous = None
    for value in '甲乙丙':
        if previous is not None:
            old = time.time() - kb_view._RETIRE_SECONDS - 10
            os.utime(previous, (old, old))
        source.write_text(f'版本标记{value}', encoding='utf-8')
        assert _kb_references_unified(
            _record(), roots, ['版本标记'], cache_root=cache)
        previous = seen[-1]
    assert len(list(cache.glob('*/view.json'))) == 2
    assert not Path(seen[0]).exists()
    assert Path(seen[1]).is_dir() and Path(seen[2]).is_dir()
    assert seen[0] not in dispatcher._RAG_CACHE


def test_unified_pruning_preserves_recent_views(tmp_path, monkeypatch):
    import os
    import time
    import kb_view
    from src.retrieval import dispatcher
    monkeypatch.setattr(kb_view, '_MAX_CACHED_VIEWS', 1)
    _, roots = _corpus(tmp_path)
    source = tmp_path / 'diet' / 'diet-lifestyle' / 'version.md'
    seen = _capture_views(monkeypatch)
    cache = tmp_path / 'cache'
    source.write_text('版本标记甲', encoding='utf-8')
    _kb_references_unified(_record(), roots, ['版本标记'], cache_root=cache)
    source.write_text('版本标记乙', encoding='utf-8')
    _kb_references_unified(_record(), roots, ['版本标记'], cache_root=cache)
    assert Path(seen[0]).is_dir() and Path(seen[1]).is_dir()
    assert seen[0] not in dispatcher._RAG_CACHE
    old = time.time() - kb_view._RETIRE_SECONDS - 10
    os.utime(seen[0], (old, old))
    _kb_references_unified(_record(), roots, ['版本标记'], cache_root=cache)
    assert not Path(seen[0]).exists()
    assert Path(seen[1]).is_dir()


def test_unified_failed_build_has_no_partial_view(tmp_path, monkeypatch):
    import kb_view
    _, roots = _corpus(tmp_path)
    cache = tmp_path / 'cache'
    original = kb_view.shutil.copyfile

    def fail_copy(source, target):
        raise OSError('合成发布前复制故障')

    monkeypatch.setattr(kb_view.shutil, 'copyfile', fail_copy)
    with pytest.raises(OSError, match='合成发布前复制故障'):
        _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    assert not list(cache.glob('*/view.json'))
    assert not list(cache.glob('.*.staging-*'))
    monkeypatch.setattr(kb_view.shutil, 'copyfile', original)
    assert _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    assert len(list(cache.glob('*/view.json'))) == 1


def test_unified_source_change_during_build_not_published(tmp_path, monkeypatch):
    import kb_view
    _, roots = _corpus(tmp_path)
    cache = tmp_path / 'cache'
    original = kb_view.shutil.copyfile
    changed = []

    def change_source(source, target):
        copied = original(source, target)
        if not changed:
            Path(source).write_text('构建期间发生内容变化', encoding='utf-8')
            changed.append(source)
        return copied

    monkeypatch.setattr(kb_view.shutil, 'copyfile', change_source)
    with pytest.raises(ValueError, match='构建期间已变化'):
        _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    assert not list(cache.glob('*/view.json'))
    assert not list(cache.glob('.*.staging-*'))


def test_unified_corrupt_manifest_is_rebuilt(tmp_path, monkeypatch):
    import json
    _, roots = _corpus(tmp_path)
    seen = _capture_views(monkeypatch)
    cache = tmp_path / 'cache'
    first = _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    manifest = Path(seen[0]) / 'view.json'
    manifest.write_text('{', encoding='utf-8')
    second = _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=cache)
    assert _signature(second) == _signature(first)
    assert seen[0] == seen[1]
    assert json.loads(manifest.read_text(encoding='utf-8'))['schema'] == 1


def test_unified_overlapping_cache_uses_ephemeral_view(tmp_path, monkeypatch):
    from src.retrieval import dispatcher, grep_search, synonym_loader
    _, roots = _corpus(tmp_path)
    seen = _capture_views(monkeypatch)

    def counts():
        return (len(dispatcher._RAG_CACHE), len(grep_search._FILE_CACHE),
                len(synonym_loader._CACHE))

    before = counts()
    first = _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=tmp_path)
    assert counts() == before
    second = _kb_references_unified(_record(), roots, _ALL_ANCHORS, cache_root=tmp_path)
    assert _signature(second) == _signature(first)
    assert counts() == before
    assert seen[0] != seen[1]
    assert not Path(seen[0]).exists() and not Path(seen[1]).exists()
    assert not (tmp_path / '.write.lock').exists()
