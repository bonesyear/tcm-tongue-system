"""分类知识库重置的原库保护、回滚与重新启用测试。"""
import io
import os
import zipfile

import pytest

import envfile
import kb_import
import kb_reset
from app import create_app
from src.retrieval import inspect_kb_categories


def _zip(category):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('a.md', '# 合成知识\n太阴虚寒与下利的测试文本\n')
        archive.writestr('synonym_map.yaml', '便软:\n  - 下利\n')
        archive.writestr('kb.yaml', f'schema_version: 1\ncategory: {category}\n')
    output.seek(0)
    return output


def _snapshot(root):
    if not root.exists():
        return {}
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def _original(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'original.md').write_text('原库内容不得改变', encoding='utf-8')
    return root


def _client(tmp_path, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    env = tmp_path / '.env'
    env.write_text('VISION_DISABLED=1\nLLM_DISABLED=1\n', encoding='utf-8')
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    client.post('/demo')
    return client


def _import(client, category):
    return client.post('/settings/kb/import', data={
        'category': category, 'kb_file': (_zip(category), 'kb.zip'),
    }, content_type='multipart/form-data')


def test_composite_reset_is_not_supported(tmp_path):
    with pytest.raises(ValueError, match='未知知识库类别'):
        kb_reset.reset_kb(str(tmp_path), str(tmp_path / '.env'), 'composite',
                          write_env=envfile.write_env)
    assert not (tmp_path / '.env').exists()
    assert not (tmp_path / 'private_kb').exists()


def test_reset_disables_category_and_reupload_reactivates(tmp_path, monkeypatch):
    original = _original(tmp_path)
    original_before = _snapshot(original)
    client = _client(tmp_path, monkeypatch)
    assert _import(client, 'constitution').status_code == 200
    managed = tmp_path / 'data' / 'private_kb' / 'constitution'
    assert (managed / 'a.md').is_file()

    response = client.post('/settings/kb/reset', data={'category': 'constitution'})
    assert response.status_code == 302
    config = envfile.read_env(str(tmp_path / '.env'))
    assert config['TCM_KB_CONSTITUTION_DISABLED'] == '1'
    assert config['TCM_KB_CONSTITUTION_ROOT'] == str(managed)
    assert not managed.exists()
    assert _snapshot(original) == original_before
    states = inspect_kb_categories(config)
    assert states['constitution']['disabled'] is True
    assert states['constitution']['status'] == 'unconfigured'
    detail = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '体质格局倾向' not in detail

    assert _import(client, 'constitution').status_code == 200
    config = envfile.read_env(str(tmp_path / '.env'))
    assert config['TCM_KB_CONSTITUTION_DISABLED'] == ''
    assert inspect_kb_categories(config)['constitution']['status'] == 'ready'
    assert (managed / 'a.md').is_file()
    assert _snapshot(original) == original_before


def test_reset_wins_over_legacy_without_touching_other_categories(tmp_path, monkeypatch):
    legacy = _original(tmp_path)
    legacy_before = _snapshot(legacy)
    env = tmp_path / '.env'
    env.write_text(f'TCM_KB_ROOT={legacy}\nTCM_KB_ALLOW_EXTERNAL_KB=1\nVISION_DISABLED=1\nLLM_DISABLED=1\n', encoding='utf-8')
    app = create_app(env_file=str(env), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    client.post('/demo')
    assert inspect_kb_categories(envfile.read_env(str(env)))['diet']['status'] == 'ready'

    response = client.post('/settings/kb/reset', data={'category': 'diet'})
    assert response.status_code == 302
    config = envfile.read_env(str(env))
    states = inspect_kb_categories(config)
    assert states['diet']['status'] == 'unconfigured'
    assert states['diet']['disabled'] is True
    assert states['constitution']['status'] == 'ready'
    assert states['formula']['status'] == 'ready'
    assert _snapshot(legacy) == legacy_before
    detail = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '体质格局倾向' in detail and '水证 · 宜' not in detail


def test_reset_write_failure_restores_copy_and_both_config_values(tmp_path):
    kb_import.import_kb(_zip('diet'), str(tmp_path), str(tmp_path / '.env'),
                        write_env=envfile.write_env, category='diet')
    files_before = _snapshot(tmp_path / 'private_kb')
    config_before = (tmp_path / '.env').read_bytes()
    calls = {'count': 0}

    def fail_once(path, updates):
        envfile.write_env(path, updates)
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('重置写后失败')

    result = kb_reset.reset_kb(str(tmp_path), str(tmp_path / '.env'), 'diet',
                               write_env=fail_once)
    assert result['ok'] is False and calls['count'] == 1
    assert _snapshot(tmp_path / 'private_kb') == files_before
    assert (tmp_path / '.env').read_bytes() == config_before
    assert not list(tmp_path.glob('.kb-reset-backup-*'))


def test_locked_reset_is_refused_without_deleting_copy(tmp_path, monkeypatch):
    original = _original(tmp_path)
    original_before = _snapshot(original)
    monkeypatch.setenv('TCM_KB_DIET_ROOT', str(original))
    app = create_app(env_file=str(tmp_path / '.env'), data_root=str(tmp_path / 'data'))
    app.config['TESTING'] = True
    managed = tmp_path / 'data' / 'private_kb' / 'diet'
    managed.mkdir(parents=True)
    (managed / 'a.md').write_text('导入副本', encoding='utf-8')
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/settings/kb/reset', data={'category': 'diet'},
                                      headers={'Origin': 'http://localhost'})
    assert response.status_code == 409
    assert (managed / 'a.md').is_file()
    assert _snapshot(original) == original_before


def test_reset_rejects_symlink_instead_of_deleting_target(tmp_path):
    original = _original(tmp_path)
    managed = tmp_path / 'private_kb'
    managed.mkdir()
    try:
        os.symlink(original, managed / 'diet', target_is_directory=True)
    except OSError as error:
        pytest.skip(f'当前平台不允许创建目录符号链接: {error}')
    with pytest.raises(ValueError, match='普通的导入副本目录'):
        kb_reset.reset_kb(str(tmp_path), str(tmp_path / '.env'), 'diet',
                          write_env=envfile.write_env)
    assert (original / 'original.md').is_file()
    assert (managed / 'diet').is_symlink()
