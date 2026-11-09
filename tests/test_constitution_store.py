import json

import pytest

from constitution_store import (
    assessment_view, build_assessment, finalize_assessment, validate_assessment,
)
from src.constitution_assessment import RULE_ENTRIES


def _answers(value='3'):
    return {entry.entry_id: value for entry in RULE_ENTRIES}


def test_completed_assessment_is_json_safe_versioned_and_restorable():
    first = build_assessment(_answers(), 'female', final=True, timezone_name='UTC')
    assert first['schema_version'] == 1
    assert first['standard_id'] == 'GB/T 46939—2025'
    assert first['questionnaire_version'] == 'appendixA-2025'
    assert first['status'] == 'completed'
    assert first['gender'] == 'female'
    assert first['answers'] == _answers()
    assert first['evaluation']['results']['湿热质']['item_count'] == 3
    assert first['evaluation']['results']['湿热质']['converted_score'] == '50'
    json.dumps(first, ensure_ascii=False)

    view = assessment_view({'constitution_assessment': first})
    assert view['status'] == 'completed'
    assert view['stale'] is False
    assert view['assessment'] == first
    assert validate_assessment({'constitution_assessment': first}) == []


def test_old_record_without_assessment_is_unassessed_not_computed():
    view = assessment_view({'inquiry': {'手足温凉': {'answer': '厥冷'}}})
    assert view['status'] == 'unassessed'
    assert view['stale'] is False
    assert validate_assessment({}) == []


def test_changed_answer_or_gender_makes_old_evaluation_stale_and_restore_works():
    old = build_assessment(_answers(), 'female', final=True)
    changed = dict(old, answers=dict(old['answers'], **{'GB46939-A2-01': '4'}))
    view = assessment_view({'constitution_assessment': changed})
    assert view['stale'] is True
    assert view['status'] == 'error'
    assert validate_assessment({'constitution_assessment': changed})

    restored = build_assessment(old['answers'], 'male', final=True)
    restored_view = assessment_view({'constitution_assessment': restored})
    assert restored_view['stale'] is False
    assert restored_view['assessment']['evaluation']['results']['湿热质']['excluded_items'] == [
        'GB46939-A6-03']


def test_incomplete_answers_cannot_finalize_but_explicit_unknown_is_allowed():
    with pytest.raises(ValueError, match='未完成'):
        build_assessment({'GB46939-A2-01': '3'}, 'female', final=True)
    answers = _answers()
    del answers['GB46939-A2-02']
    result = build_assessment(answers, 'female', unanswered=['GB46939-A2-02'], final=True)
    assert result['status'] == 'completed'
    assert result['evaluation']['results']['气虚质']['result'] == 'unknown'
    assert result['evaluation']['results']['气虚质']['unknown_items'] == ['GB46939-A2-02']
    assert result['evaluation']['results']['气虚质']['raw_score'] is None


def test_finalize_draft_requires_complete_input_and_skipping_needs_no_gender():
    with pytest.raises(ValueError, match='未完成'):
        finalize_assessment({'constitution_assessment': {
            'status': 'draft', 'gender': 'female', 'answers': {}, 'unanswered': [],
        }})
    skipped = finalize_assessment({'constitution_assessment': {
        'status': 'skipped', 'gender': None, 'answers': {}, 'unanswered': [],
    }})
    assert skipped['status'] == 'skipped'
    assert skipped['evaluation']['results'] == {}


def test_tampered_evaluation_or_unanswered_list_is_rejected():
    valid = build_assessment(_answers(), 'female', final=True)
    tampered = json.loads(json.dumps(valid, ensure_ascii=False))
    tampered['evaluation']['results']['湿热质']['converted_score'] = '0'
    assert assessment_view({'constitution_assessment': tampered})['stale'] is True
    with pytest.raises(ValueError, match='无法回答'):
        build_assessment(_answers(), 'female', unanswered=['GB46939-A2-01'], final=True)
