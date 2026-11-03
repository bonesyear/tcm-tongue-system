"""公私知识库分离的回归测试；只使用合成资料与临时目录。"""
from pathlib import Path
import shutil

from src.retrieval import retrieve
from src.retrieval.kb_paths import resolve_kb_root


def test_public_kb_contains_only_configuration(monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    root = Path(resolve_kb_root())
    assert [path.relative_to(root).as_posix() for path in root.rglob('*')
            if path.is_file()] == ['README.md']
    result = retrieve('便软', kb_root=str(root), syn_map={})
    assert result['results'] == []


def test_external_private_kb_root_works(tmp_path, monkeypatch):
    private = tmp_path / 'private-kb'
    source = Path(__file__).parent / 'fixtures' / 'knowledge_base'
    shutil.copytree(source, private)
    monkeypatch.setenv('TCM_KB_ROOT', str(private))
    result = retrieve('便软')
    assert result['grep_hits'] > 0
    assert '下利' in result['synonyms_used']
    assert resolve_kb_root() == str(private)
