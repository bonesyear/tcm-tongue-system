"""知识库 ZIP 导入的原库保护、安全与回滚测试；全部使用合成压缩包。"""
import io
import os
import stat
import zipfile

import pytest

import envfile
import kb_import
from app import create_app
from src.retrieval import retrieve


def _zip(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    output.seek(0)
    return output


def _with_manifest(upload, category):
    if category == 'composite':
        return upload
    output = io.BytesIO()
    with zipfile.ZipFile(upload) as source, \
            zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        if 'kb.yaml' not in source.namelist():
            target.writestr('kb.yaml', f'schema_version: 1\ncategory: {category}\n')
    output.seek(0)
    return output


def _valid_zip(category='composite'):
    return _with_manifest(_zip([
        ('a.md', '# 合成知识\n太阴虚寒与下利的测试文本\n'),
        ('synonym_map.yaml', '便软:\n  - 下利\n'),
    ]), category)


def _replacement_zip(category='composite'):
    return _with_manifest(_zip([
        ('new.md', '# 新合成知识\n新别名与新内容\n'),
        ('synonym_map.yaml', '新查询:\n  - 新别名\n'),
    ]), category)


def _snapshot(root):
    if not root.exists():
        return {}
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def _original_kb(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'original.md').write_text('# 原库占位\n原库内容不得改变\n', encoding='utf-8')
    (root / 'synonym_map.yaml').write_text('原查询:\n  - 原库内容\n', encoding='utf-8')
    return root


def _import(tmp_path, upload, locked=False, writer=None, category='composite'):
    calls = {}

    def write_env(path, updates):
        if writer:
            writer(path, updates)
        else:
            envfile.write_env(path, updates)
        calls.update(updates)

    result = kb_import.import_kb(_with_manifest(upload, category),
                                 str(tmp_path), str(tmp_path / '.env'),
                                 env_locked=locked, write_env=write_env,
                                 category=category)
    return result, calls


def _assert_no_transaction_dirs(root):
    assert not list(root.glob('.kb-staging/*'))
    assert not list(root.glob('.kb-backup-*'))
    assert not list(root.glob('.kb-preserve-*'))


def test_valid_zip_uses_managed_copy_and_preserves_original(tmp_path):
    original = _original_kb(tmp_path)
    before = _snapshot(original)
    result, config = _import(tmp_path, _valid_zip())
    assert result['ok'] is True and result['configured'] is True
    assert result['count'] == 2
    assert result['root'] == str(tmp_path / 'private_kb') == config['TCM_KB_ROOT']
    assert envfile.read_env(str(tmp_path / '.env'))['TCM_KB_ROOT'] == result['root']
    assert _snapshot(original) == before
    retrieved = retrieve('便软', kb_root=result['root'])
    assert retrieved['grep_hits'] == 1
    assert retrieved['synonyms_used'] == ['下利']


def test_composite_import_clears_only_composite_disabled(tmp_path):
    envfile.write_env(str(tmp_path / '.env'), {
        'TCM_KB_COMPOSITE_DISABLED': '1',
        'TCM_KB_CATEGORIES_DISABLED': '1',
        'TCM_KB_DIET_DISABLED': '1',
    })

    result, _ = _import(tmp_path, _valid_zip(), category='composite')

    assert result['ok'] is True and result['configured'] is True
    config = envfile.read_env(str(tmp_path / '.env'))
    assert config['TCM_KB_COMPOSITE_DISABLED'] == ''
    assert config['TCM_KB_CATEGORIES_DISABLED'] == '1'
    assert config['TCM_KB_DIET_DISABLED'] == '1'


def test_sub_library_import_preserves_group_and_other_switches(tmp_path):
    envfile.write_env(str(tmp_path / '.env'), {
        'TCM_KB_CATEGORIES_DISABLED': '1',
        'TCM_KB_DIET_DISABLED': '1',
        'TCM_KB_FORMULA_DISABLED': '1',
    })

    result, _ = _import(tmp_path, _valid_zip('diet'), category='diet')

    assert result['ok'] is True and result['configured'] is True
    config = envfile.read_env(str(tmp_path / '.env'))
    assert config['TCM_KB_DIET_DISABLED'] == ''
    assert config['TCM_KB_CATEGORIES_DISABLED'] == '1'
    assert config['TCM_KB_FORMULA_DISABLED'] == '1'


def test_public_template_can_be_packaged_imported_and_retrieved(tmp_path):
    template = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'templates', 'kb'))
    entries = []
    for name in ('README.md', 'example.md', 'synonym_map.yaml', 'kb.yaml'):
        with open(os.path.join(template, name), 'rb') as source:
            entries.append((name, source.read()))
    result, _ = _import(tmp_path, _zip(entries), category='constitution')
    assert result['ok'] is True and result['count'] == 4
    retrieved = retrieve('示例口语', kb_root=result['root'])
    assert retrieved['grep_hits'] == 1
    assert retrieved['synonyms_used'] == ['示例规范词']
    assert retrieved['results'][0]['file'] == 'example.md'


def test_repeat_import_replaces_only_managed_copy_and_refreshes_retrieval(tmp_path):
    original = _original_kb(tmp_path)
    original_before = _snapshot(original)
    first, _ = _import(tmp_path, _valid_zip())
    assert retrieve('便软', kb_root=first['root'])['grep_hits'] == 1
    second, _ = _import(tmp_path, _replacement_zip())
    assert second['root'] == first['root']
    assert not (tmp_path / 'private_kb' / 'a.md').exists()
    assert (tmp_path / 'private_kb' / 'new.md').is_file()
    assert retrieve('便软', kb_root=second['root'])['grep_hits'] == 0
    retrieved = retrieve('新查询', kb_root=second['root'])
    assert retrieved['grep_hits'] == 1
    assert retrieved['synonyms_used'] == ['新别名']
    assert _snapshot(original) == original_before
    _assert_no_transaction_dirs(tmp_path)


def test_invalid_zip_preserves_managed_copy_original_and_config(tmp_path):
    original = _original_kb(tmp_path)
    original_before = _snapshot(original)
    result, _ = _import(tmp_path, _valid_zip())
    managed_before = _snapshot(tmp_path / 'private_kb')
    config_before = (tmp_path / '.env').read_bytes()
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('../escape.md', 'bad')]))
    assert _snapshot(tmp_path / 'private_kb') == managed_before
    assert _snapshot(original) == original_before
    assert (tmp_path / '.env').read_bytes() == config_before
    assert result['root'] == str(tmp_path / 'private_kb')
    assert not (tmp_path / 'escape.md').exists()
    _assert_no_transaction_dirs(tmp_path)


def test_traversal_symlink_and_special_files_are_rejected(tmp_path):
    for entries in ([('../escape.md', 'bad')], [('nested/../../escape.md', 'bad')]):
        with pytest.raises(ValueError):
            _import(tmp_path, _zip(entries))
    for kind in (stat.S_IFLNK, stat.S_IFIFO):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            info = zipfile.ZipInfo('special.md')
            info.external_attr = (kind | 0o777) << 16
            archive.writestr(info, 'target')
        output.seek(0)
        with pytest.raises(ValueError):
            _import(tmp_path, output)
    assert not (tmp_path / 'private_kb').exists()
    _assert_no_transaction_dirs(tmp_path)


def test_bad_text_limits_and_invalid_synonyms_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('bad.md', b'\xff\xfe')]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('large.md', b'a' * (4 * 1024 * 1024 + 1))]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('bomb.md', b'a' * (1024 * 1024))]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('a.exe', b'not-kb')]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('a.md', 'ok'), ('synonym_map.yaml', '- invalid')]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([('a.md', 'ok'), ('synonym_map.yaml', ':\n[')]))
    with pytest.raises(ValueError):
        _import(tmp_path, _zip([(f'{index}.md', 'ok') for index in range(33)]))
    assert not (tmp_path / 'private_kb').exists()
    _assert_no_transaction_dirs(tmp_path)


def test_category_manifest_is_required_and_must_match(tmp_path):
    for entries, message in (
            ([('a.md', 'ok')], '必须包含 kb.yaml'),
            ([('a.md', 'ok'), ('kb.yaml', 'schema_version: 1\ncategory: diet\n')],
             '类别必须为 constitution'),
            ([('a.md', 'ok'), ('kb.yaml', 'schema_version: 2\ncategory: constitution\n')],
             'schema_version')):
        with pytest.raises(ValueError, match=message):
            kb_import.import_kb(_zip(entries), str(tmp_path), str(tmp_path / '.env'),
                                write_env=envfile.write_env, category='constitution')
    assert not (tmp_path / 'private_kb').exists()
    assert not (tmp_path / '.env').exists()
    _assert_no_transaction_dirs(tmp_path)


def test_locked_environment_does_not_write_config_or_original(tmp_path):
    original = _original_kb(tmp_path)
    before = _snapshot(original)

    def forbidden(*args):
        raise AssertionError('环境锁定时不得写配置')

    result, _ = _import(tmp_path, _valid_zip(), locked=True, writer=forbidden)
    assert result['ok'] is True and result['configured'] is False
    assert result['root'] == str(tmp_path / 'private_kb')
    assert not (tmp_path / '.env').exists()
    assert _snapshot(original) == before


def test_first_config_failure_preserves_original_and_config(tmp_path):
    original = _original_kb(tmp_path)
    original_before = _snapshot(original)
    envfile.write_env(str(tmp_path / '.env'), {'TCM_KB_ROOT': str(original)})
    config_before = (tmp_path / '.env').read_bytes()

    def fail(*args):
        raise OSError('首次导入配置写回失败')

    result, _ = _import(tmp_path, _valid_zip(), writer=fail)
    assert result['ok'] is False
    assert not (tmp_path / 'private_kb').exists()
    assert _snapshot(original) == original_before
    assert (tmp_path / '.env').read_bytes() == config_before
    failed = list(tmp_path.glob('.kb-failed-*'))
    assert len(failed) == 1 and (failed[0] / 'a.md').is_file()
    _assert_no_transaction_dirs(tmp_path)


def test_config_write_failure_restores_previous_managed_copy(tmp_path):
    original = _original_kb(tmp_path)
    original_before = _snapshot(original)
    _import(tmp_path, _valid_zip())
    managed_before = _snapshot(tmp_path / 'private_kb')
    config_before = (tmp_path / '.env').read_bytes()

    def fail(*args):
        raise OSError('合成写配置失败')

    result, config = _import(tmp_path, _replacement_zip(), writer=fail)
    assert result['ok'] is False and config == {}
    assert 'TCM_KB_ROOT 写回失败' in result['error']
    assert _snapshot(tmp_path / 'private_kb') == managed_before
    assert _snapshot(original) == original_before
    assert (tmp_path / '.env').read_bytes() == config_before
    assert len(list(tmp_path.glob('.kb-failed-*'))) == 1
    _assert_no_transaction_dirs(tmp_path)


def test_composite_import_preserves_category_copies_and_configs(tmp_path):
    _import(tmp_path, _valid_zip(), category='constitution')
    _import(tmp_path, _replacement_zip(), category='diet')
    constitution_before = _snapshot(tmp_path / 'private_kb' / 'constitution')
    diet_before = _snapshot(tmp_path / 'private_kb' / 'diet')
    config_before = envfile.read_env(str(tmp_path / '.env'))
    result, _ = _import(tmp_path, _valid_zip(), category='composite')
    assert result['ok'] is True
    assert _snapshot(tmp_path / 'private_kb' / 'constitution') == constitution_before
    assert _snapshot(tmp_path / 'private_kb' / 'diet') == diet_before
    config = envfile.read_env(str(tmp_path / '.env'))
    assert config['TCM_KB_CONSTITUTION_ROOT'] == config_before['TCM_KB_CONSTITUTION_ROOT']
    assert config['TCM_KB_DIET_ROOT'] == config_before['TCM_KB_DIET_ROOT']
    _assert_no_transaction_dirs(tmp_path)


def test_write_after_commit_restores_original_config_and_directory(tmp_path):
    original = _original_kb(tmp_path)
    envfile.write_env(str(tmp_path / '.env'), {'TCM_KB_DIET_ROOT': str(original)})
    config_before = (tmp_path / '.env').read_bytes()

    def write_then_fail(path, updates):
        envfile.write_env(path, updates)
        if updates.get('TCM_KB_DIET_ROOT') != str(original):
            raise RuntimeError('合成：写入后的回读失败')

    result, _ = _import(tmp_path, _valid_zip(), writer=write_then_fail, category='diet')
    assert result['ok'] is False
    assert not (tmp_path / 'private_kb' / 'diet').exists()
    assert (tmp_path / '.env').read_bytes() == config_before
    assert len(list(tmp_path.glob('.kb-failed-*'))) == 1
    _assert_no_transaction_dirs(tmp_path)


def test_composite_config_failure_restores_composite_and_categories(tmp_path):
    _import(tmp_path, _valid_zip(), category='constitution')
    _import(tmp_path, _replacement_zip(), category='diet')
    _import(tmp_path, _valid_zip(), category='composite')
    original = _original_kb(tmp_path)
    envfile.write_env(str(tmp_path / '.env'), {'TCM_KB_ROOT': str(original)})
    files_before = _snapshot(tmp_path / 'private_kb')
    config_before = (tmp_path / '.env').read_bytes()
    calls = {'count': 0}

    def fail_once_after_write(path, updates):
        envfile.write_env(path, updates)
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('综合导入写后失败')

    result, _ = _import(tmp_path, _replacement_zip(), writer=fail_once_after_write)
    assert result['ok'] is False and calls['count'] == 1
    assert _snapshot(tmp_path / 'private_kb') == files_before
    assert (tmp_path / '.env').read_bytes() == config_before
    assert len(list(tmp_path.glob('.kb-failed-*'))) == 1
    _assert_no_transaction_dirs(tmp_path)


def test_composite_rejects_reserved_category_directories(tmp_path):
    _import(tmp_path, _valid_zip(), category='constitution')
    before = _snapshot(tmp_path / 'private_kb')
    with pytest.raises(ValueError, match='系统分类目录'):
        _import(tmp_path, _zip([('constitution/new.md', 'new')]))
    assert _snapshot(tmp_path / 'private_kb') == before
    _assert_no_transaction_dirs(tmp_path)


def test_activation_failure_restores_previous_managed_copy(tmp_path, monkeypatch):
    original = _original_kb(tmp_path)
    original_before = _snapshot(original)
    _import(tmp_path, _valid_zip())
    managed_before = _snapshot(tmp_path / 'private_kb')
    config_before = (tmp_path / '.env').read_bytes()
    real_replace = os.replace

    def fail_activation(source, target):
        if '.kb-staging' in source and target == str(tmp_path / 'private_kb'):
            raise OSError('合成目录激活失败')
        return real_replace(source, target)

    monkeypatch.setattr(kb_import.os, 'replace', fail_activation)
    with pytest.raises(OSError, match='合成目录激活失败'):
        _import(tmp_path, _replacement_zip())
    assert _snapshot(tmp_path / 'private_kb') == managed_before
    assert _snapshot(original) == original_before
    assert (tmp_path / '.env').read_bytes() == config_before
    _assert_no_transaction_dirs(tmp_path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    app = create_app(env_file=str(tmp_path / '.env'), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    return client


def test_settings_import_route_and_retrieval(client, tmp_path):
    response = client.post('/settings/kb/import', data={
        'category': 'constitution',
        'kb_file': (_valid_zip('constitution'), 'knowledge.zip'),
    }, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['ok'] is True and payload['configured'] is True
    config = envfile.read_env(str(tmp_path / '.env'))
    root = config['TCM_KB_CONSTITUTION_ROOT']
    assert root == payload['root'] == str(tmp_path / 'data' / 'private_kb' / 'constitution')
    assert retrieve('便软', kb_root=root)['grep_hits'] == 1
    html = client.get('/settings').get_data(as_text=True)
    assert '中医体质辨证知识库' in html and root in html

    response = client.post('/settings/kb/import', data={
        'category': 'diet', 'kb_file': (_replacement_zip('diet'), 'diet.zip'),
    }, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_json()
    diet_root = response.get_json()['root']
    assert diet_root == str(tmp_path / 'data' / 'private_kb' / 'diet')
    assert envfile.read_env(str(tmp_path / '.env'))['TCM_KB_CONSTITUTION_ROOT'] == root
    assert (tmp_path / 'data' / 'private_kb' / 'constitution' / 'a.md').is_file()
    assert (tmp_path / 'data' / 'private_kb' / 'diet' / 'new.md').is_file()


def test_settings_composite_import_card_and_route(client, tmp_path):
    html = client.get('/settings').get_data(as_text=True)
    assert '默认 · 推荐' not in html
    assert '分类知识库（进阶）' not in html
    assert '默认关闭，普通自建直接使用综合包即可' not in html
    assert '此功能用于调试及保证兼容性。' not in html
    assert '旧综合库' not in html
    assert 'id="kb-card-categories"' not in html
    for category in ('constitution', 'diet', 'formula', 'composite'):
        assert f'<section id="kb-card-{category}"' in html
        assert f'data-category="{category}"' in html
    card_order = ('kb-card-constitution', 'kb-card-diet', 'kb-card-formula',
                  'kb-category-mode', 'kb-card-composite')
    assert [html.index(f'id="{card_id}"') for card_id in card_order] == sorted(
        html.index(f'id="{card_id}"') for card_id in card_order)
    assert '目录结构与建库步骤见右上角指南' in html
    assert 'if (data.configured) {\n        location.reload();' in html
    assert 'statusLabel.textContent = "知识库可用"' not in html

    response = client.post('/settings/kb/import', data={
        'category': 'composite', 'kb_file': (_valid_zip(), 'composite.zip'),
    }, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['ok'] is True and payload['configured'] is True
    root = payload['root']
    assert root == str(tmp_path / 'data' / 'private_kb')
    assert retrieve('便软', kb_root=root)['grep_hits'] == 1
    html = client.get('/settings').get_data(as_text=True)
    assert 'id="kb-current-root-composite"' in html and root in html
    assert 'id="kb-import-status-composite"' in html

    envfile.write_env(str(tmp_path / '.env'), {'TCM_KB_STRICT_CATEGORIES': '1'})
    html = client.get('/settings').get_data(as_text=True)
    assert '综合库未参与检索' in html
    assert '当前只使用分类专用根' in html


def test_kb_group_is_collapsed_and_has_five_independent_switches(client):
    html = client.get('/settings').get_data(as_text=True)
    opening = '<details class="kb-group" id="kb-categories-card"'
    assert opening in html
    assert ' open' not in html.split(opening, 1)[1].split('>', 1)[0]
    labels = {
        'kb_categories': '启用子知识库整组',
        'kb_constitution': '启用中医体质辨证知识库',
        'kb_diet': '启用食疗知识库',
        'kb_formula': '启用方剂知识库',
        'kb_composite': '启用综合知识库',
    }
    for target, label in labels.items():
        assert html.count(f'data-kb-toggle="{target}"') == 1
        assert f'aria-label="{label}"' in html
    markup = html.split('<div class="card" id="kb-import-card">', 1)[1].split('<script>', 1)[0]
    group_start = markup.index(opening)
    group_label = markup.index('<label class="switch kb-group-toggle"')
    group = markup[group_start:group_label]
    # 整组开关紧跟在最外层 details 后，不能混入内部技术详情的折叠区。
    assert group.rstrip().endswith('</details>')
    for item in ('kb-card-constitution', 'kb-card-diet',
                 'kb-card-formula', 'kb-category-mode'):
        assert group_start < markup.index(item) < group_label
    group_toggle = markup.index('data-kb-toggle="kb_categories"', group_label)
    assert group_label < group_toggle < markup.index('kb-card-composite')


def test_kb_group_override_is_visible_without_losing_sub_preferences(client, tmp_path):
    envfile.write_env(str(tmp_path / '.env'), {
        'TCM_KB_CATEGORIES_DISABLED': '1',
        'TCM_KB_DIET_DISABLED': '1',
    })
    html = client.get('/settings').get_data(as_text=True)
    assert '整组已停用' in html
    expected = {
        'kb_categories': False, 'kb_composite': True,
        'kb_constitution': True, 'kb_diet': False, 'kb_formula': True,
    }
    for target, checked in expected.items():
        marker = html.index(f'data-kb-toggle="{target}"')
        tag = html[html.rfind('<input', 0, marker):html.index('>', marker) + 1]
        assert ('checked' in tag) is checked, (target, tag)


def test_settings_kb_modules_use_responsive_split_layout(client):
    html = client.get('/settings').get_data(as_text=True)
    for category in ('constitution', 'diet', 'formula', 'composite'):
        start = html.index(f'<section id="kb-card-{category}"')
        section = html[start:html.index('</section>', start)]
        assert 'class="kb-module"' in section
        summary_index = section.index('class="kb-module-summary"')
        import_index = section.index('class="kb-import-form kb-module-import"')
        tools_index = section.index('class="kb-module-tools"')
        assert summary_index < import_index < tools_index
    assert '.kb-module {' in html
    assert '.kb-upload-controls {' in html
    assert '@media (max-width: 760px)' in html


def test_kb_paths_are_collapsed_technical_details(client):
    html = client.get('/settings').get_data(as_text=True)
    assert html.count('<summary>技术详情</summary>') == 4
    for category in ('constitution', 'diet', 'formula', 'composite'):
        count_index = html.index(f'id="kb-count-{category}"')
        path_index = html.index(f'id="kb-current-root-{category}"')
        details_index = html.rfind('<summary>技术详情</summary>', 0, path_index)
        assert details_index > count_index


def test_settings_import_rejects_bad_zip_without_config_change(client, tmp_path):
    response = client.post('/settings/kb/import', data={
        'kb_file': (io.BytesIO(b'bad'), 'bad.zip'),
    }, content_type='multipart/form-data')
    assert response.status_code == 400
    assert not (tmp_path / '.env').exists()
    assert not list((tmp_path / 'data').glob('.kb-staging/*'))


def test_settings_locked_root_is_never_replaced(tmp_path, monkeypatch):
    original = _original_kb(tmp_path)
    before = _snapshot(original)
    monkeypatch.setenv('TCM_KB_ROOT', str(original))
    app = create_app(env_file=str(tmp_path / '.env'), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/settings/kb/import', data={
        'kb_file': (_valid_zip(), 'knowledge.zip'),
    }, content_type='multipart/form-data', headers={'Origin': 'http://localhost'})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['configured'] is False
    assert _snapshot(original) == before
    assert not (tmp_path / '.env').exists()
    assert (tmp_path / 'data' / 'private_kb' / 'a.md').is_file()


def test_settings_import_requires_admin(client):
    response = client.post('/settings/kb/import', data={
        'kb_file': (_valid_zip(), 'knowledge.zip'),
    }, content_type='multipart/form-data', headers={'Origin': 'http://localhost'},
        environ_overrides={'REMOTE_ADDR': '192.0.2.10'})
    assert response.status_code == 403


def test_settings_import_rejects_unknown_category(client, tmp_path):
    response = client.post('/settings/kb/import', data={
        'category': 'unknown', 'kb_file': (_valid_zip(), 'knowledge.zip'),
    }, content_type='multipart/form-data')
    assert response.status_code == 400
    assert not (tmp_path / '.env').exists()
    assert not (tmp_path / 'data' / 'private_kb').exists()
