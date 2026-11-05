"""知识库状态、无库降级与可选词典行为；只使用合成资料。"""
from app import create_app
from src.retrieval import inspect_kb, invalidate_kb_caches, retrieve


def test_inspect_kb_states_revision_and_uppercase_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    public = inspect_kb()
    assert public['status'] == 'unconfigured' and public['file_count'] == 0

    empty = tmp_path / 'empty'
    empty.mkdir()
    assert inspect_kb(str(empty))['status'] == 'empty'
    missing = inspect_kb(str(tmp_path / 'missing'))
    assert missing['status'] == 'error' and missing['error']

    (empty / 'note.MD').write_text('# 合成\n大写扩展名可检索\n', encoding='utf-8')
    ready = inspect_kb(str(empty))
    assert ready['status'] == 'ready' and ready['file_count'] == 1
    assert ready['revision']
    assert retrieve('大写扩展名', kb_root=str(empty))['grep_hits'] == 1
    (empty / 'note.MD').write_text('# 合成\n版本已经改变\n', encoding='utf-8')
    changed = inspect_kb(str(empty))
    assert changed['revision'] != ready['revision']


def test_missing_optional_synonym_map_is_quiet_and_not_stale(tmp_path, capsys):
    root = tmp_path / 'kb'
    root.mkdir()
    (root / 'a.md').write_text('下利 合成内容\n', encoding='utf-8')
    for _ in range(3):
        assert retrieve('便软', kb_root=str(root))['synonyms_used'] == []
    assert capsys.readouterr().err == ''

    (root / 'synonym_map.yaml').write_text('便软:\n  - 下利\n', encoding='utf-8')
    assert retrieve('便软', kb_root=str(root))['synonyms_used'] == ['下利']
    (root / 'synonym_map.yaml').unlink()
    assert retrieve('便软', kb_root=str(root))['synonyms_used'] == []
    assert capsys.readouterr().err == ''
    invalidate_kb_caches(str(root))


def test_settings_and_local_report_explicitly_handle_no_kb(tmp_path, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    env.write_text('VISION_DISABLED=1\nLLM_DISABLED=1\n', encoding='utf-8')
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    settings = client.get('/settings').get_data(as_text=True)
    assert settings.count('未配置知识库') == 4
    for category in ('constitution', 'diet', 'formula'):
        assert f'id="kb-count-{category}">0</span>' in settings
    assert '其他本地功能仍可使用' in settings

    client.post('/demo')
    detail = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '缺少中医体质辨证知识库' in detail
    assert '缺少食疗知识库' in detail
    assert '水证 · 宜' not in detail
    assert '<h3 class="sect-h">四证聚类</h3>' not in detail
    assert 'diet-therapy.md' not in detail and 'KB L' not in detail


def test_category_specific_root_overrides_legacy_without_fallback(tmp_path):
    from src.retrieval import inspect_kb_categories
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'legacy.md').write_text('综合库合成内容', encoding='utf-8')
    missing = tmp_path / 'missing-diet'
    categories = inspect_kb_categories({
        'TCM_KB_ROOT': str(legacy), 'TCM_KB_DIET_ROOT': str(missing),
        'TCM_KB_ALLOW_EXTERNAL_KB': '1'})
    assert categories['constitution']['status'] == 'ready'
    assert categories['constitution']['legacy'] is True
    assert categories['formula']['root'] == str(legacy)
    assert categories['diet']['status'] == 'error'
    assert categories['diet']['root'] == str(missing)
    assert categories['diet']['legacy'] is False


def test_group_and_composite_switches_preserve_independent_preferences(tmp_path):
    from src.retrieval import (
        KB_CATEGORY_DEFS, kb_category_root, kb_disabled_key, kb_legacy_root)

    roots = {}
    config = {'TCM_KB_ALLOW_EXTERNAL_KB': '1'}
    for category in KB_CATEGORY_DEFS:
        root = tmp_path / category
        root.mkdir()
        (root / 'synthetic.md').write_text(f'{category} 专用资料', encoding='utf-8')
        roots[category] = str(root)
        config[f'TCM_KB_{category.upper()}_ROOT'] = str(root)
    composite = tmp_path / 'composite'
    composite.mkdir()
    (composite / 'synthetic.md').write_text('综合资料', encoding='utf-8')
    config['TCM_KB_ROOT'] = str(composite)
    config['TCM_KB_DIET_DISABLED'] = '1'

    config['TCM_KB_CATEGORIES_DISABLED'] = '1'
    assert all(kb_category_root(category, config) is None for category in roots)
    assert kb_legacy_root(config) == str(composite)

    config['TCM_KB_CATEGORIES_DISABLED'] = ''
    assert kb_category_root('constitution', config) == roots['constitution']
    assert kb_category_root('diet', config) is None
    assert kb_category_root('formula', config) == roots['formula']

    config['TCM_KB_COMPOSITE_DISABLED'] = '1'
    assert kb_legacy_root(config) is None
    assert kb_category_root('constitution', config) == roots['constitution']
    config['TCM_KB_CONSTITUTION_ROOT'] = ''
    assert kb_category_root('constitution', config) is None
    assert kb_disabled_key('composite') == 'TCM_KB_COMPOSITE_DISABLED'


def test_group_status_distinguishes_override_from_each_sub_library(tmp_path):
    from src.retrieval import inspect_kb_categories

    states = inspect_kb_categories({
        'TCM_KB_CATEGORIES_DISABLED': '1',
        'TCM_KB_DIET_DISABLED': '1',
        'TCM_DATA_ROOT': str(tmp_path / 'data'),
    })
    for category, info in states.items():
        assert info['group_disabled'] is True, category
        assert info['disabled'] is True, category
        assert info['root'] == '', category
    assert states['constitution']['self_disabled'] is False
    assert states['diet']['self_disabled'] is True
    assert states['formula']['self_disabled'] is False


def test_local_sections_follow_each_category_availability(tmp_path, monkeypatch):
    import envfile
    constitution = tmp_path / 'constitution'
    diet = tmp_path / 'diet'
    for root in (constitution, diet):
        root.mkdir()
        (root / 'content.md').write_text('合成内容', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    envfile.write_env(str(env), {
        'VISION_DISABLED': '1', 'LLM_DISABLED': '1',
        'TCM_KB_CONSTITUTION_ROOT': str(constitution)})
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    client.post('/demo')
    detail = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '体质格局倾向' in detail and '四证聚类' in detail
    assert '缺少食疗知识库' in detail and '水证 · 宜' not in detail

    envfile.write_env(str(env), {
        'TCM_KB_CONSTITUTION_ROOT': '', 'TCM_KB_DIET_ROOT': str(diet)})
    detail = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '缺少中医体质辨证知识库' in detail
    assert '体质格局倾向' not in detail
    assert '饮食宜忌方向（内置规则，非当前知识库引用）' in detail
    assert '水证 · 宜' in detail


def test_strict_mode_toggle_disables_and_restores_legacy_fallback(tmp_path, monkeypatch):
    import envfile
    from src.retrieval import inspect_kb_categories
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'legacy.md').write_text('综合库合成内容', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    envfile.write_env(str(env), {
        'VISION_DISABLED': '1', 'LLM_DISABLED': '1', 'TCM_KB_ROOT': str(legacy),
        'TCM_KB_ALLOW_EXTERNAL_KB': '1'})
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    config = envfile.read_env(str(env))
    assert inspect_kb_categories(config)['diet']['status'] == 'ready'

    response = client.post('/settings/kb/mode', data={'enabled': '1'})
    assert response.status_code == 302
    config = envfile.read_env(str(env))
    assert config['TCM_KB_STRICT_CATEGORIES'] == '1'
    assert config['TCM_KB_ROOT'] == str(legacy)
    assert inspect_kb_categories(config)['diet']['status'] == 'unconfigured'
    assert (legacy / 'legacy.md').is_file()

    response = client.post('/settings/kb/mode', data={})
    assert response.status_code == 302
    assert inspect_kb_categories(envfile.read_env(str(env)))['diet']['status'] == 'ready'


def test_external_roots_ignored_by_default_and_managed_copies_auto_enable(tmp_path, monkeypatch):
    from src.retrieval import inspect_kb_categories
    import io
    import zipfile
    import envfile
    import kb_import
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'old.md').write_text('旧库合成内容', encoding='utf-8')
    original_bytes = (external / 'old.md').read_bytes()
    data_root = tmp_path / 'data'
    env = tmp_path / '.env'
    envfile.write_env(str(env), {
        'TCM_DATA_ROOT': str(data_root), 'TCM_KB_ROOT': str(external)})
    monkeypatch.setenv('TCM_KB_ROOT', str(external))
    config = envfile.read_env(str(env))
    states = inspect_kb_categories(config)
    assert all(info['status'] == 'unconfigured' for info in states.values())
    assert all(info['root'] == '' for info in states.values())

    for category in ('constitution', 'diet', 'formula'):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('a.md', '# 新合成内容\n')
            archive.writestr('kb.yaml', f'schema_version: 1\ncategory: {category}\n')
        output.seek(0)
        result = kb_import.import_kb(output, str(data_root), str(env),
                                     write_env=envfile.write_env, category=category)
        assert result['ok'] and result['configured']
    states = inspect_kb_categories(envfile.read_env(str(env)))
    assert all(info['status'] == 'ready' for info in states.values())
    assert all(not info['legacy'] for info in states.values())
    assert (external / 'old.md').read_bytes() == original_bytes

    config['TCM_KB_ALLOW_EXTERNAL_KB'] = '1'
    states = inspect_kb_categories(config)
    assert states['constitution']['status'] == 'ready'


def test_explicit_none_inspect_does_not_fallback_to_environment(tmp_path, monkeypatch):
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'old.md').write_text('不应读取的合成旧库\n', encoding='utf-8')
    monkeypatch.setenv('TCM_KB_ROOT', str(external))
    monkeypatch.delenv('TCM_KB_ALLOW_EXTERNAL_KB', raising=False)

    # 无参数调用保留旧的默认检索行为；显式空值表示上游已判定未配置。
    assert inspect_kb()['status'] == 'ready'
    for empty in (None, ''):
        assert inspect_kb(empty) == {
            'root': '', 'status': 'unconfigured', 'file_count': 0,
            'revision': '', 'error': ''}


def test_settings_does_not_inspect_ignored_external_composite(tmp_path, monkeypatch):
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'old.md').write_text('不应读取的合成旧库\n', encoding='utf-8')
    monkeypatch.setenv('TCM_KB_ROOT', str(external))
    monkeypatch.delenv('TCM_KB_ALLOW_EXTERNAL_KB', raising=False)
    app = create_app(env_file=str(tmp_path / '.env'),
                     data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})

    settings = client.get('/settings').get_data(as_text=True)

    assert 'id="kb-status-label-composite">未配置知识库<' in settings
    assert 'id="kb-count-composite">0</span>' in settings
    assert 'id="kb-current-root-composite"></code>' in settings


def _legacy_report_client(tmp_path, monkeypatch):
    """带三类标记的历史报告：没有新版类别指纹，不能靠整份过期隐藏。"""
    import json
    import envfile

    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    roots = {}
    for category in ('constitution', 'diet', 'formula'):
        root = tmp_path / category
        root.mkdir()
        (root / 'synthetic.md').write_text(f'{category} 合成资料\n', encoding='utf-8')
        roots[f'TCM_KB_{category.upper()}_ROOT'] = str(root)
    envfile.write_env(str(env), {
        **roots, 'TCM_KB_ALLOW_EXTERNAL_KB': '1',
        'LLM_API_KEY': 'sk-synthetic', 'LLM_MODEL': 'synthetic',
        'LLM_BASE_URL': 'https://example.invalid/v1/chat/completions',
    })
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    client.post('/demo')
    path = tmp_path / 'data' / 'records' / 'daily' / '2026-06-25_analysis.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    for key in ('corrected_at', 'manually_corrected', 'derived_meta'):
        raw.pop(key, None)
    raw['pattern_differentiation'] = {
        'three_views': {'表里观': '里'}, 'four_patterns': {},
        'six_diseases': 'CONSTITUTION_SUMMARY',
        'core_pathomechanism': '合成历史病机',
    }
    raw['diagnosis'] = {'report': {
        'generated_at': '2026-01-01T00:00:00+00:00',
        'markdown': '# 合成历史报告\n\nFORMULA_MARKDOWN',
        'diet_advice': {'daily_foods': [{
            'name': 'DIET_STRUCTURED', 'nature': '平', 'purpose': '合成',
            'amount': '适量', 'note': '仅供界面测试',
        }]},
        'kb_status': 'retrieved',
        'kb_refs': [
            {'file': f'{category}.md', 'line': 1, 'term': '合成',
             'excerpt': f'{category.upper()}_REF', 'category': category}
            for category in ('constitution', 'diet', 'formula')
        ] + [{'file': 'legacy.md', 'line': 1, 'term': '合成',
              'excerpt': 'UNCATEGORIZED_REF'}],
    }}
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    return client, env


def _assert_legacy_baseline(html):
    assert 'CONSTITUTION_SUMMARY' in html
    assert '辨证报告·全案' in html and 'FORMULA_MARKDOWN' in html
    assert 'DIET_STRUCTURED' in html
    for marker in ('CONSTITUTION_REF', 'DIET_REF', 'FORMULA_REF', 'UNCATEGORIZED_REF'):
        assert marker in html


def test_legacy_report_hides_full_report_and_refs_without_constitution(tmp_path, monkeypatch):
    import envfile
    client, env = _legacy_report_client(tmp_path, monkeypatch)
    _assert_legacy_baseline(client.get('/record/2026-06-25').get_data(as_text=True))

    envfile.write_env(str(env), {'TCM_KB_CONSTITUTION_DISABLED': '1'})
    html = client.get('/record/2026-06-25').get_data(as_text=True)

    assert '缺少中医体质辨证知识库' in html
    assert 'CONSTITUTION_SUMMARY' not in html
    assert '辨证报告·全案' not in html and 'FORMULA_MARKDOWN' not in html
    assert 'CONSTITUTION_REF' not in html


def test_diet_summary_does_not_depend_on_constitution(tmp_path, monkeypatch):
    import envfile
    client, env = _legacy_report_client(tmp_path, monkeypatch)
    envfile.write_env(str(env), {'TCM_KB_CONSTITUTION_DISABLED': '1'})

    html = client.get('/record/2026-06-25').get_data(as_text=True)

    assert '<h3 class="sect-h">饮食建议</h3>' in html
    assert 'DIET_STRUCTURED' in html


def test_legacy_report_filters_disabled_diet_refs(tmp_path, monkeypatch):
    import envfile
    client, env = _legacy_report_client(tmp_path, monkeypatch)
    _assert_legacy_baseline(client.get('/record/2026-06-25').get_data(as_text=True))
    envfile.write_env(str(env), {'TCM_KB_DIET_DISABLED': '1'})

    html = client.get('/record/2026-06-25').get_data(as_text=True)

    assert '缺少食疗知识库' in html
    assert 'DIET_STRUCTURED' not in html and 'DIET_REF' not in html
    assert 'UNCATEGORIZED_REF' not in html
    assert 'CONSTITUTION_SUMMARY' in html and 'FORMULA_MARKDOWN' in html
    assert 'CONSTITUTION_REF' in html and 'FORMULA_REF' in html


def test_missing_formula_hides_full_report_but_keeps_other_summaries(tmp_path, monkeypatch):
    import envfile
    client, env = _legacy_report_client(tmp_path, monkeypatch)
    envfile.write_env(str(env), {'TCM_KB_FORMULA_DISABLED': '1'})

    html = client.get('/record/2026-06-25').get_data(as_text=True)

    assert '缺少方剂知识库' in html
    assert '辨证报告·全案' not in html and 'FORMULA_MARKDOWN' not in html
    assert 'FORMULA_REF' not in html
    assert 'CONSTITUTION_SUMMARY' in html and 'DIET_STRUCTURED' in html

    envfile.write_env(str(env), {'TCM_KB_FORMULA_DISABLED': ''})
    _assert_legacy_baseline(client.get('/record/2026-06-25').get_data(as_text=True))


def _assert_strict_report_cycle(tmp_path, monkeypatch, *, modern):
    """实际切换设置路由，验证两个方向的过期、恢复和重新生成入口。"""
    import json
    import envfile
    from src.retrieval import inspect_kb, inspect_kb_categories

    client, env = _legacy_report_client(tmp_path, monkeypatch)
    composite = tmp_path / 'composite'
    composite.mkdir()
    (composite / 'synthetic.md').write_text('综合库合成资料\n', encoding='utf-8')
    envfile.write_env(str(env), {
        **{f'TCM_KB_{category.upper()}_ROOT': ''
           for category in ('constitution', 'diet', 'formula')},
        'TCM_KB_ROOT': str(composite),
    })
    path = tmp_path / 'data' / 'records' / 'daily' / '2026-06-25_analysis.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    report = raw['diagnosis']['report']

    for initial_strict in (False, True):
        envfile.write_env(str(env), {
            'TCM_KB_STRICT_CATEGORIES': '1' if initial_strict else ''})
        config = envfile.read_env(str(env))
        stored_legacy = inspect_kb(None if initial_strict else str(composite))
        report.update(kb_root=stored_legacy['root'],
                      kb_revision=stored_legacy['revision'])
        if modern:
            report['kb_categories'] = {
                category: {'root': info['root'], 'revision': info['revision']}
                for category, info in inspect_kb_categories(config).items()}
        else:
            report.pop('kb_categories', None)
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')

        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert '报告已过期' not in html, initial_strict
        assert ('FORMULA_MARKDOWN' in html) is not initial_strict, initial_strict

        response = client.post('/settings/kb/mode',
                               data={} if initial_strict else {'enabled': '1'})
        assert response.status_code == 302
        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert '报告已过期' in html, initial_strict
        assert '知识库目录或内容已变化' in html, initial_strict
        assert 'FORMULA_MARKDOWN' not in html, initial_strict
        assert 'id="btn-report"' in html and '重新生成' in html

        response = client.post('/settings/kb/mode',
                               data={'enabled': '1'} if initial_strict else {})
        assert response.status_code == 302
        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert '报告已过期' not in html, initial_strict
        assert ('FORMULA_MARKDOWN' in html) is not initial_strict, initial_strict


def test_strict_mode_modern_report_staleness_cycle(tmp_path, monkeypatch):
    _assert_strict_report_cycle(tmp_path, monkeypatch, modern=True)


def test_strict_mode_legacy_report_staleness_cycle(tmp_path, monkeypatch):
    _assert_strict_report_cycle(tmp_path, monkeypatch, modern=False)


def _assert_strict_report_regeneration(tmp_path, monkeypatch, *, modern):
    """过期后用模拟模型重生成，指纹、输入披露和页面均对应当前模式。"""
    import json
    import envfile
    import llm_client
    from src.retrieval import inspect_kb, inspect_kb_categories

    client, env = _legacy_report_client(tmp_path, monkeypatch)
    composite = tmp_path / 'composite'
    composite.mkdir()
    (composite / 'synthetic.md').write_text('综合库合成资料\n', encoding='utf-8')
    envfile.write_env(str(env), {
        **{f'TCM_KB_{category.upper()}_ROOT': ''
           for category in ('constitution', 'diet', 'formula')},
        'TCM_KB_ROOT': str(composite),
    })
    path = tmp_path / 'data' / 'records' / 'daily' / '2026-06-25_analysis.json'
    baseline = path.read_text(encoding='utf-8')
    prompt_modes = []

    def fake_chat(user_input, *args, **kwargs):
        strict = user_input.count('状态：未配置') == 3
        prompt_modes.append('strict' if strict else 'composite')
        structured = {} if strict else {
            'three_views': {}, 'four_patterns': {},
            'six_diseases': '太阴病',
            'core_pathomechanism': '太阴虚寒，水饮内停',
            'diet_advice': {}, 'lifestyle': {},
        }
        marker = 'REGENERATED_STRICT' if strict else 'REGENERATED_COMPOSITE'
        return json.dumps({'structured': structured,
                           'markdown': f'# 当前报告\n\n{marker}'},
                          ensure_ascii=False)

    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    for initial_strict in (False, True):
        target_strict = not initial_strict
        envfile.write_env(str(env), {
            'TCM_KB_STRICT_CATEGORIES': '1' if initial_strict else ''})
        raw = json.loads(baseline)
        report = raw['diagnosis']['report']
        stored_legacy = inspect_kb(None if initial_strict else str(composite))
        report.update(kb_root=stored_legacy['root'],
                      kb_revision=stored_legacy['revision'])
        if modern:
            report['kb_categories'] = {
                category: {'root': info['root'], 'revision': info['revision']}
                for category, info in inspect_kb_categories(
                    envfile.read_env(str(env))).items()}
        else:
            report.pop('kb_categories', None)
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')

        response = client.post('/settings/kb/mode',
                               data={'enabled': '1'} if target_strict else {})
        assert response.status_code == 302
        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert '报告已过期' in html and '重新生成' in html

        response = client.post('/record/2026-06-25/report')
        assert response.status_code == 200, response.get_json()
        assert prompt_modes[-1] == ('strict' if target_strict else 'composite')
        saved = json.loads(path.read_text(encoding='utf-8'))
        regenerated = saved['diagnosis']['report']
        current = inspect_kb_categories(envfile.read_env(str(env)))
        for category, info in current.items():
            stored = regenerated['kb_categories'][category]
            assert (stored['root'], stored['revision']) == \
                (info['root'], info['revision']), category
            if target_strict:
                assert stored['status'] == 'unconfigured', category
            else:
                assert stored['status'] in ('retrieved', 'no_hits'), category
        roots = {info['root'] for info in current.values()}
        revisions = {info['revision'] for info in current.values()}
        assert regenerated['kb_root'] == (roots.pop() if len(roots) == 1 else '')
        assert regenerated['kb_revision'] == (
            revisions.pop() if len(revisions) == 1 else '')
        assert regenerated['input_hash'] and regenerated['ruleset_version']
        assert regenerated['generator_version']
        assert regenerated['generated_at'] != '2026-01-01T00:00:00+00:00'
        assert 'FORMULA_MARKDOWN' not in regenerated['markdown']

        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert '报告已过期' not in html, target_strict
        assert 'FORMULA_MARKDOWN' not in html and 'CONSTITUTION_SUMMARY' not in html
        if target_strict:
            assert regenerated['kb_status'] == 'unconfigured'
            assert regenerated['kb_root'] == '' and regenerated['kb_revision'] == ''
            assert 'REGENERATED_STRICT' in regenerated['markdown']
            assert '缺少中医体质辨证知识库' in html and '缺少方剂知识库' in html
        else:
            assert regenerated['kb_status'] in ('retrieved', 'no_hits')
            assert regenerated['kb_root'] == str(composite)
            assert regenerated['kb_revision']
            assert 'REGENERATED_COMPOSITE' in html and '太阴病' in html


def test_strict_mode_modern_report_regenerates_current_fingerprints(
        tmp_path, monkeypatch):
    _assert_strict_report_regeneration(tmp_path, monkeypatch, modern=True)


def test_strict_mode_legacy_report_regenerates_current_fingerprints(
        tmp_path, monkeypatch):
    _assert_strict_report_regeneration(tmp_path, monkeypatch, modern=False)


def test_switch_modern_report_staleness_and_restore(tmp_path, monkeypatch):
    import json
    import envfile
    from src.retrieval import inspect_kb_categories

    client, env = _legacy_report_client(tmp_path, monkeypatch)
    path = tmp_path / 'data' / 'records' / 'daily' / '2026-06-25_analysis.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['diagnosis']['report']['kb_categories'] = {
        category: {'root': info['root'], 'revision': info['revision']}
        for category, info in inspect_kb_categories(envfile.read_env(str(env))).items()}
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    assert '报告已过期' not in client.get('/record/2026-06-25').get_data(as_text=True)

    for enabled in (False, True):
        response = client.post('/settings/toggle',
                               json={'target': 'kb_categories', 'enabled': enabled})
        assert response.status_code == 200, response.get_json()
        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert ('报告已过期' in html) is not enabled
        assert ('知识库目录或内容已变化' in html) is not enabled

    response = client.post('/settings/toggle',
                           json={'target': 'kb_composite', 'enabled': False})
    assert response.status_code == 200
    assert '报告已过期' not in client.get('/record/2026-06-25').get_data(as_text=True)

    composite = tmp_path / 'composite'
    composite.mkdir()
    (composite / 'synthetic.md').write_text('综合库合成资料\n', encoding='utf-8')
    envfile.write_env(str(env), {
        **{f'TCM_KB_{category.upper()}_ROOT': ''
           for category in ('constitution', 'diet', 'formula')},
        'TCM_KB_ROOT': str(composite)})
    response = client.post('/settings/toggle',
                           json={'target': 'kb_composite', 'enabled': True})
    assert response.status_code == 200
    raw['diagnosis']['report']['kb_categories'] = {
        category: {'root': info['root'], 'revision': info['revision']}
        for category, info in inspect_kb_categories(envfile.read_env(str(env))).items()}
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    assert '报告已过期' not in client.get('/record/2026-06-25').get_data(as_text=True)
    for enabled in (False, True):
        response = client.post('/settings/toggle',
                               json={'target': 'kb_composite', 'enabled': enabled})
        assert response.status_code == 200
        html = client.get('/record/2026-06-25').get_data(as_text=True)
        assert ('报告已过期' in html) is not enabled


def test_switches_control_local_sections_without_changing_dedicated_roots(tmp_path, monkeypatch):
    import envfile

    constitution = tmp_path / 'constitution'
    diet = tmp_path / 'diet'
    composite = tmp_path / 'composite'
    for root in (constitution, diet, composite):
        root.mkdir()
        (root / 'content.md').write_text('合成内容', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    envfile.write_env(str(env), {
        'VISION_DISABLED': '1', 'LLM_DISABLED': '1',
        'TCM_KB_ALLOW_EXTERNAL_KB': '1', 'TCM_KB_ROOT': str(composite),
        'TCM_KB_CONSTITUTION_ROOT': str(constitution), 'TCM_KB_DIET_ROOT': str(diet)})
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    client.post('/demo')

    def detail():
        return client.get('/record/2026-06-25').get_data(as_text=True)

    assert '体质格局倾向' in detail() and '水证 · 宜' in detail()
    client.post('/settings/toggle', json={'target': 'kb_composite', 'enabled': False})
    assert '体质格局倾向' in detail() and '水证 · 宜' in detail()

    client.post('/settings/toggle', json={'target': 'kb_categories', 'enabled': False})
    html = detail()
    assert '体质格局倾向' not in html and '<h3 class="sect-h">四证聚类</h3>' not in html
    assert '缺少中医体质辨证知识库' in html and '缺少食疗知识库' in html
    assert '水证 · 宜' not in html

    client.post('/settings/toggle', json={'target': 'kb_categories', 'enabled': True})
    assert '体质格局倾向' in detail() and '水证 · 宜' in detail()
    envfile.write_env(str(env), {
        'TCM_KB_CONSTITUTION_ROOT': '', 'TCM_KB_DIET_ROOT': ''})
    assert '体质格局倾向' not in detail() and '水证 · 宜' not in detail()
    client.post('/settings/toggle', json={'target': 'kb_composite', 'enabled': True})
    assert '体质格局倾向' in detail() and '水证 · 宜' in detail()
