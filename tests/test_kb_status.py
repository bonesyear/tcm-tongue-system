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
    assert settings.count('未配置知识库') == 3
    for category in ('constitution', 'diet', 'formula'):
        assert f'可检索 Markdown <span id="kb-count-{category}">0</span>' in settings
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


def test_external_roots_ignored_by_default_and_managed_copies_auto_enable(tmp_path):
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
    config = envfile.read_env(str(env))
    states = inspect_kb_categories(config)
    assert all(info['status'] == 'unconfigured' for info in states.values())

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
