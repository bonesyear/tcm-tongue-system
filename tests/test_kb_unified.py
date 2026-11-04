import json
from pathlib import Path
import shutil

import pytest

from kb_evidence import _kb_references, _kb_references_unified
from report_store import build_report_input
from src.record import DailyRecord

_FIXTURE = Path(__file__).parent / 'fixtures' / 'knowledge_base'
_ANCHORS = {
    'constitution': [],
    'diet': ['忌口', '适宜', '食疗'],
    'formula': ['煎服', '温覆', '方证', '方剂'],
}
_ALL_ANCHORS = ['忌口', '适宜', '食疗', '煎服', '温覆', '方证', '方剂']
_DIRECTORIES = {'constitution': 'diagnostics', 'diet': 'diet-lifestyle',
                'formula': 'formulas'}


def _corpus(tmp_path):
    composite = tmp_path / 'composite'
    shutil.copytree(_FIXTURE, composite)
    roots = {}
    for category, directory in _DIRECTORIES.items():
        target = tmp_path / category
        target.mkdir()
        for path in (composite / directory).rglob('*.md'):
            relative = path.relative_to(composite)
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target / relative)
        shutil.copyfile(composite / 'synonym_map.yaml', target / 'synonym_map.yaml')
        roots[category] = str(target)
    return composite, roots


def _record():
    return DailyRecord(json.loads(
        (Path(__file__).parent / 'fixtures' / '2026-06-25_analysis.json').read_text(encoding='utf-8')))


def _signature(refs):
    return [(ref['file'], ref['line'], ref['excerpt'], ref['term']) for ref in refs]


def _without(root, directory):
    target = root.parent / f'{root.name}-without-{directory}'
    shutil.copytree(root, target)
    shutil.rmtree(target / directory)
    return str(target)


def test_unified_all_categories_matches_composite(tmp_path):
    composite, roots = _corpus(tmp_path)
    rec = _record()
    expected = _kb_references(rec, kb_root=str(composite), anchor_terms=_ALL_ANCHORS)
    actual = _kb_references_unified(rec, roots, _ALL_ANCHORS)
    assert _signature(actual) == _signature(expected)
    assert build_report_input(rec, actual) == build_report_input(rec, expected)
    assert all(ref['category'] in roots for ref in actual)


def test_unified_two_categories_matches_filtered_composite(tmp_path):
    composite, roots = _corpus(tmp_path)
    rec = _record()
    scoped = _without(composite, 'formulas')
    expected = _kb_references(rec, kb_root=scoped, anchor_terms=_ANCHORS['diet'])
    actual = _kb_references_unified(rec, {
        'constitution': roots['constitution'], 'diet': roots['diet']}, _ANCHORS['diet'])
    assert _signature(actual) == _signature(expected)
    assert build_report_input(rec, actual) == build_report_input(rec, expected)

    scoped = _without(composite, 'diet-lifestyle')
    expected = _kb_references(rec, kb_root=scoped, anchor_terms=_ANCHORS['formula'])
    actual = _kb_references_unified(rec, {
        'constitution': roots['constitution'], 'formula': roots['formula']},
        _ANCHORS['formula'])
    assert _signature(actual) == _signature(expected)
    assert build_report_input(rec, actual) == build_report_input(rec, expected)


def test_unified_rejects_conflicting_duplicate_files(tmp_path):
    _, roots = _corpus(tmp_path)
    (tmp_path / 'constitution' / 'diagnostics' / 'conflict.md').write_text('甲', encoding='utf-8')
    (tmp_path / 'diet' / 'diagnostics').mkdir()
    (tmp_path / 'diet' / 'diagnostics' / 'conflict.md').write_text('乙', encoding='utf-8')
    with pytest.raises(ValueError, match='重复且内容冲突'):
        _kb_references_unified(_record(), roots, _ALL_ANCHORS)


def test_default_report_flattens_unified_anchor_terms(tmp_path, monkeypatch):
    import kb_evidence
    import llm_client
    from report_store import generate_and_store_report

    _, roots = _corpus(tmp_path)
    seen = {}

    def capture(rec, kb_roots, anchor_terms):
        seen['roots'] = kb_roots
        seen['anchors'] = anchor_terms
        return []

    monkeypatch.setattr(kb_evidence, '_kb_references_unified', capture)
    monkeypatch.setattr(llm_client, 'chat', lambda *args, **kwargs: json.dumps({
        'structured': {'three_views': {}, 'four_patterns': {}, 'six_diseases': '',
                       'core_pathomechanism': '', 'diet_advice': {}, 'lifestyle': {}},
        'markdown': '# 合成报告\n仅用于统一锚词回归。',
    }, ensure_ascii=False))
    daily = tmp_path / 'records' / 'daily'
    backup = tmp_path / 'records' / '_backup'
    daily.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / 'fixtures' / '2026-06-25_analysis.json',
                    daily / '2026-06-25_analysis.json')
    result = generate_and_store_report(
        str(daily), str(backup), '2026-06-25',
        lambda: {'model': 'synthetic', 'base_url': 'http://127.0.0.1/unused',
                 'api_key': 'synthetic', 'kb_roots': roots})
    assert result['ok'], result
    assert seen['roots'] == roots
    assert seen['anchors'] == _ALL_ANCHORS


def _generate_report(tmp_path, monkeypatch, roots, injection=None):
    import llm_client
    from report_store import generate_and_store_report

    monkeypatch.setattr(llm_client, 'chat', lambda *args, **kwargs: json.dumps({
        'structured': {'three_views': {}, 'four_patterns': {}, 'six_diseases': '',
                       'core_pathomechanism': '', 'diet_advice': {}, 'lifestyle': {}},
        'markdown': '# 合成报告\n仅用于统一检索回归。',
    }, ensure_ascii=False))
    daily = tmp_path / 'records' / 'daily'
    backup = tmp_path / 'records' / '_backup'
    daily.mkdir(parents=True)
    shutil.copyfile(_FIXTURE.parent / '2026-06-25_analysis.json',
                    daily / '2026-06-25_analysis.json')
    kwargs = {'kb_references': injection} if injection is not None else {}
    result = generate_and_store_report(
        str(daily), str(backup), '2026-06-25',
        lambda: {'model': 'synthetic', 'base_url': 'http://127.0.0.1/unused',
                 'api_key': 'synthetic', 'kb_roots': roots}, **kwargs)
    assert result['ok'], result
    return json.loads((daily / '2026-06-25_analysis.json').read_text(
        encoding='utf-8'))['diagnosis']['report']


def test_unified_shared_root_excludes_unavailable_category(tmp_path, monkeypatch):
    composite, _ = _corpus(tmp_path)
    formula = composite / 'formulas' / 'formula-system.md'
    formula.write_text(formula.read_text(encoding='utf-8') +
                       '\n食疗也可能出现在综合库的其他分类文件中。\n', encoding='utf-8')
    roots = {'constitution': str(composite), 'diet': str(composite), 'formula': None}
    expected = _kb_references(_record(), kb_root=_without(composite, 'formulas'),
                              anchor_terms=_ANCHORS['diet'])
    actual = _kb_references_unified(_record(), roots, _ANCHORS['diet'])
    assert _signature(actual) == _signature(expected)
    assert {ref['category'] for ref in actual} <= {'constitution', 'diet'}

    report = _generate_report(tmp_path, monkeypatch, roots)
    assert not [ref for ref in report['kb_refs'] if ref['category'] == 'formula']
    assert report['kb_categories']['formula']['status'] == 'unconfigured'


def test_unified_partial_shared_root_rejects_unknown_layout(tmp_path):
    composite, _ = _corpus(tmp_path)
    (composite / 'notes').mkdir()
    (composite / 'notes' / 'custom.md').write_text('自定义主题', encoding='utf-8')
    roots = {'constitution': str(composite), 'diet': str(composite)}
    with pytest.raises(ValueError, match='无法确定类别'):
        _kb_references_unified(_record(), roots, ['自定义主题'])


def test_unified_full_shared_root_keeps_generic_candidates(tmp_path):
    composite, _ = _corpus(tmp_path)
    (composite / 'notes').mkdir()
    (composite / 'notes' / 'custom.md').write_text('自定义主题', encoding='utf-8')
    refs = _kb_references_unified(
        _record(), {category: str(composite) for category in _DIRECTORIES}, ['自定义主题'])
    generic = [ref for ref in refs if ref['file'] == 'notes/custom.md']
    assert [ref['category'] for ref in generic] == ['composite']
    text = build_report_input(_record(), refs, kb_status={
        category: 'retrieved' for category in _DIRECTORIES})
    assert '综合知识库通用候选参考' in text
    assert '自定义主题' in text


def test_unified_dedicated_root_keeps_custom_layout(tmp_path):
    root = tmp_path / 'custom-diet'
    (root / 'notes').mkdir(parents=True)
    (root / 'notes' / 'custom.md').write_text('专用食疗主题', encoding='utf-8')
    refs = _kb_references_unified(_record(), {'diet': str(root)}, ['专用食疗主题'])
    assert [ref['category'] for ref in refs] == ['diet']


def test_report_preserves_custom_kb_references(tmp_path, monkeypatch):
    _, roots = _corpus(tmp_path)
    called = []

    def injection(rec, kb_root=None, anchor_terms=None, category=None):
        called.append(category)
        return [{'file': f'{category}.md', 'line': 1, 'excerpt': '合成自定义参考',
                 'term': 'custom', 'category': category}]

    report = _generate_report(tmp_path, monkeypatch, roots, injection)
    assert called == list(_DIRECTORIES)
    assert [(ref['file'], ref['category']) for ref in report['kb_refs']] == [
        (f'{category}.md', category) for category in _DIRECTORIES]


def test_unified_mixed_roots_prefer_dedicated_category(tmp_path):
    composite, roots = _corpus(tmp_path)
    shared_formula = composite / 'formulas' / 'formula-system.md'
    shared_formula.write_text('共享综合根中的方剂文件不应进入。\n食疗交叉主题。',
                              encoding='utf-8')
    (composite / 'notes').mkdir()
    (composite / 'notes' / 'custom.md').write_text('通用综合主题', encoding='utf-8')
    expected_root = tmp_path / 'expected'
    shutil.copytree(composite, expected_root)
    shutil.rmtree(expected_root / 'formulas')
    shutil.copytree(tmp_path / 'formula' / 'formulas', expected_root / 'formulas')
    active = {'constitution': str(composite), 'diet': str(composite),
              'formula': roots['formula']}
    anchors = _ALL_ANCHORS + ['通用综合主题']
    expected = _kb_references(_record(), kb_root=str(expected_root), anchor_terms=anchors)
    actual = _kb_references_unified(_record(), active, anchors)
    assert _signature(actual) == _signature(expected)
    generic = [ref for ref in actual if ref['file'] == 'notes/custom.md']
    assert [ref['category'] for ref in generic] == ['composite']


def test_unified_lowercase_readme_matches_original(tmp_path):
    composite, roots = _corpus(tmp_path)
    (composite / 'readme.md').write_text('小写说明文件标记', encoding='utf-8')
    (tmp_path / 'diet' / 'readme.md').write_text('小写说明文件标记', encoding='utf-8')
    expected = _kb_references(_record(), kb_root=str(composite),
                              anchor_terms=['小写说明文件标记'])
    actual = _kb_references_unified(_record(), roots, ['小写说明文件标记'])
    assert _signature(actual) == _signature(expected)
    assert [ref['category'] for ref in actual if ref['file'] == 'readme.md'] == ['diet']


def test_unified_aliases_preserve_loader_values(tmp_path, monkeypatch):
    from src.retrieval import synonym_loader
    _, roots = _corpus(tmp_path)
    (tmp_path / 'diet' / 'diet-lifestyle' / 'hash.md').write_text(
        '#特殊词', encoding='utf-8')
    original_load_map = synonym_loader.load_map

    def source_mapping_only(path):
        if 'kb-unified-' in str(path):
            return original_load_map(path)
        return {'口语': ['#特殊词']}

    monkeypatch.setattr(synonym_loader, 'load_map', source_mapping_only)
    refs = _kb_references_unified(_record(), roots, ['口语'])
    hits = [ref for ref in refs if ref['term'] == '口语' and ref['excerpt'] == '#特殊词']
    assert len(hits) == 1
    assert hits[0]['category'] == 'diet'


@pytest.mark.parametrize('directory_first', [True, False])
def test_unified_rejects_file_directory_conflicts(tmp_path, directory_first):
    _, roots = _corpus(tmp_path)
    first = tmp_path / 'constitution' / 'diagnostics' / 'conflict.md'
    second = tmp_path / 'diet' / 'diagnostics' / 'conflict.md'
    directory, file = (first, second) if directory_first else (second, first)
    directory.mkdir(parents=True)
    (directory / 'nested.md').write_text('目录内容', encoding='utf-8')
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('文件内容', encoding='utf-8')
    with pytest.raises(ValueError, match='路径类型冲突'):
        _kb_references_unified(_record(), roots, _ALL_ANCHORS)


def test_unified_temporary_view_invalidates_caches(tmp_path, monkeypatch):
    import kb_evidence
    from src.retrieval import dispatcher, grep_search, synonym_loader
    _, roots = _corpus(tmp_path)

    def counts():
        return (len(dispatcher._RAG_CACHE), len(grep_search._FILE_CACHE),
                len(synonym_loader._CACHE))

    before = counts()
    for _ in range(2):
        assert _kb_references_unified(_record(), roots, _ALL_ANCHORS)
    assert counts() == before

    original = kb_evidence._kb_references

    def fail_after_retrieval(rec, kb_root=None, anchor_terms=None, syn_map=None):
        original(rec, kb_root=kb_root, anchor_terms=anchor_terms, syn_map=syn_map)
        raise RuntimeError('合成检索后故障')

    monkeypatch.setattr(kb_evidence, '_kb_references', fail_after_retrieval)
    with pytest.raises(RuntimeError, match='合成检索后故障'):
        _kb_references_unified(_record(), roots, _ALL_ANCHORS)
    assert counts() == before
