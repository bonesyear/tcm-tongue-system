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
