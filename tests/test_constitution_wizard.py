import json
import os

import pytest

import wizard_store
from constitution_store import assessment_view, validate_draft_assessment
from src.constitution_assessment import RULE_ENTRIES

pytest.importorskip('flask')
from app import create_app


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / 'data'
    (root / 'records' / 'daily').mkdir(parents=True)
    return str(root)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    app = create_app(env_file=str(tmp_path / '.env',), data_root=data_root)
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    return client


def _today():
    return wizard_store.datetime.date.today().isoformat()


def _read_record(data_root, date_str):
    path = os.path.join(data_root, 'records', 'daily', f'{date_str}_analysis.json')
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _answer_all(client, value='3'):
    for entry in RULE_ENTRIES:
        response = client.post('/wizard/constitution', json={
            'action': 'answer', 'entry_id': entry.entry_id, 'value': value,
        })
        assert response.status_code == 200, response.get_json()


def _finish_parts(client):
    for part in wizard_store.PARTS:
        response = client.post('/wizard/skip', json={'part': part['part'], 'mode': 'normal'})
        assert response.status_code == 200, response.get_json()


def test_gender_answers_and_unknown_are_saved_independently(client, data_root):
    response = client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    assert response.status_code == 200
    response = client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '3',
    })
    assert response.status_code == 200
    response = client.post('/wizard/constitution', json={
        'action': 'unanswered', 'entry_id': 'GB46939-A2-02',
    })
    assert response.status_code == 200
    assessment = response.get_json()['assessment']
    assert assessment['status'] == 'draft'
    assert assessment['answers']['GB46939-A2-01'] == '3'
    assert assessment['unanswered'] == ['GB46939-A2-02']
    assert assessment['evaluation']['results']['气虚质']['result'] == 'unknown'
    assert assessment['evaluation']['results']['湿热质']['item_count'] == 3
    assert assessment['evaluation']['results']['湿热质']['excluded_items'] == ['GB46939-A6-04']

    response = client.post('/wizard/constitution', json={
        'action': 'clear_answer', 'entry_id': 'GB46939-A2-02',
    })
    assert response.get_json()['assessment']['unanswered'] == []
    response = client.post('/wizard/inquiry', json={'answer': '温'})
    assert response.status_code == 200
    response = client.post('/wizard/constitution', json={'action': 'clear'})
    assert response.status_code == 200
    draft = wizard_store.load_draft(os.path.join(data_root, 'records', 'daily'), _today())
    assert 'constitution_assessment' not in draft
    assert draft['inquiry']['手足温凉'] == '温'


def test_invalid_answer_does_not_overwrite_existing_draft(client, data_root):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '3',
    })
    response = client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '6',
    })
    assert response.status_code == 400
    assert '非法分值' in response.get_json()['error']
    draft = wizard_store.load_draft(
        os.path.join(data_root, 'records', 'daily'), _today())
    assert draft['constitution_assessment']['answers']['GB46939-A2-01'] == '3'


def test_draft_conflict_returns_409_without_overwriting(client, data_root, monkeypatch):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    original = wizard_store.load_draft_with_version

    def stale_load(daily_dir, date_str):
        draft, version = original(daily_dir, date_str)
        draft['__conflict_marker'] = 'changed-by-another-writer'
        wizard_store.save_draft(daily_dir, draft)
        return draft, version

    monkeypatch.setattr(wizard_store, 'load_draft_with_version', stale_load)
    response = client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '4',
    })
    assert response.status_code == 409
    assert response.get_json()['conflict'] is True
    draft = wizard_store.load_draft(os.path.join(data_root, 'records', 'daily'), _today())
    assert 'GB46939-A2-01' not in draft['constitution_assessment']['answers']


def test_incomplete_assessment_cannot_submit_and_draft_is_retained(client, data_root):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '3',
    })
    _finish_parts(client)
    response = client.post('/wizard/submit', json={'mode': 'new'})
    assert response.status_code == 400
    assert '未完成体质评估' in response.get_json()['error']
    draft = wizard_store.load_draft(os.path.join(data_root, 'records', 'daily'), _today())
    assert draft['constitution_assessment']['answers']['GB46939-A2-01'] == '3'
    assert not os.path.exists(os.path.join(
        data_root, 'records', 'daily', f'{_today()}_analysis.json'))


def test_completed_assessment_writes_record_and_independent_view(client, data_root):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    _answer_all(client)
    client.post('/wizard/inquiry', json={'answer': '温'})
    _finish_parts(client)
    response = client.post('/wizard/submit', json={'mode': 'new'})
    assert response.status_code == 200, response.get_json()
    raw = _read_record(data_root, response.get_json()['date'])
    assessment = raw['constitution_assessment']
    assert assessment['status'] == 'completed'
    assert assessment['evaluation']['results']['湿热质']['item_count'] == 3
    assert raw['inquiry']['手足温凉'] == {'asked': True, 'answer': '温'}
    assert assessment_view(raw)['stale'] is False
    html = client.get(f"/record/{response.get_json()['date']}").get_data(as_text=True)
    assert '国标体质评估' in html
    assert '50.00' in html
    assert 'six_diseases' not in assessment['evaluation']


def test_explicit_unknown_can_complete_but_is_not_selected_as_positive(client, data_root):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    for entry in RULE_ENTRIES:
        if entry.entry_id == 'GB46939-A2-02':
            continue
        client.post('/wizard/constitution', json={
            'action': 'answer', 'entry_id': entry.entry_id, 'value': '3',
        })
    client.post('/wizard/constitution', json={
        'action': 'unanswered', 'entry_id': 'GB46939-A2-02',
    })
    _finish_parts(client)
    response = client.post('/wizard/submit', json={'mode': 'new'})
    assert response.status_code == 200, response.get_json()
    raw = _read_record(data_root, response.get_json()['date'])
    assert raw['constitution_assessment']['unanswered'] == ['GB46939-A2-02']
    assert raw['constitution_assessment']['evaluation']['results']['气虚质']['result'] == 'unknown'
    assert raw['constitution_assessment']['evaluation']['results']['气虚质']['raw_score'] is None
    assert '气虚质' not in [item['constitution']
                          for item in raw['constitution_assessment']['evaluation']['combined_results']]


def test_skipped_assessment_has_no_result(client, data_root):
    client.post('/wizard/constitution', json={'action': 'skip'})
    _finish_parts(client)
    response = client.post('/wizard/submit', json={'mode': 'new'})
    assert response.status_code == 200, response.get_json()
    raw = _read_record(data_root, response.get_json()['date'])
    assert raw['constitution_assessment']['status'] == 'skipped'
    assert raw['constitution_assessment']['evaluation']['results'] == {}
    assert raw['constitution_assessment']['evaluation']['combined_results'] == []


def test_old_record_has_no_assessment_result(client, data_root):
    today = _today()
    path = os.path.join(data_root, 'records', 'daily', f'{today}_analysis.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'date': today, 'observations': {'tongue': {'body': {'color': '淡红'}}}},
                  handle, ensure_ascii=False)
    html = client.get(f'/record/{today}').get_data(as_text=True)
    assert '未评估' in html
    assert '50.00' not in html


def test_answer_change_recomputes_hash_and_restoring_keeps_view_valid(client, data_root):
    client.post('/wizard/constitution', json={'action': 'gender', 'gender': 'female'})
    client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '3',
    })
    first = wizard_store.load_draft(
        os.path.join(data_root, 'records', 'daily'), _today())['constitution_assessment']
    client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '4',
    })
    changed = wizard_store.load_draft(
        os.path.join(data_root, 'records', 'daily'), _today())['constitution_assessment']
    assert changed['input_hash'] != first['input_hash']
    assert changed['evaluation']['item_scores']['GB46939-A2-01'] == 4
    client.post('/wizard/constitution', json={
        'action': 'answer', 'entry_id': 'GB46939-A2-01', 'value': '3',
    })
    restored = wizard_store.load_draft(
        os.path.join(data_root, 'records', 'daily'), _today())['constitution_assessment']
    assert restored['input_hash'] == first['input_hash']
    validate_draft_assessment(restored)
