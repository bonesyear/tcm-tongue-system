from collections import Counter
from fractions import Fraction

import pytest

from src.constitution_assessment import RULE_ENTRIES, evaluate_constitution


def test_registry_covers_30_unique_entries_with_source_and_scoring_metadata():
    expected = {
        '平和质': 4, '气虚质': 3, '阳虚质': 3, '阴虚质': 3, '痰湿质': 3,
        '湿热质': 4, '血瘀质': 3, '气郁质': 3, '特禀质': 4,
    }
    assert len(RULE_ENTRIES) == 30
    assert len({entry.entry_id for entry in RULE_ENTRIES}) == 30
    assert Counter(entry.constitution for entry in RULE_ENTRIES) == expected
    for entry in RULE_ENTRIES:
        assert entry.question
        assert entry.source_clause.startswith('附录A 表A.')
        assert entry.source_pdf_page in {13, 14, 15}
        assert entry.gender_condition in {'all', 'female_only', 'male_only'}
        assert entry.score_direction in {'forward', 'reverse'}
    reverse = {entry.entry_id for entry in RULE_ENTRIES
               if entry.score_direction == 'reverse'}
    assert reverse == {'GB46939-A1-02', 'GB46939-A1-03', 'GB46939-A1-04'}
    gendered = {entry.entry_id: entry.gender_condition for entry in RULE_ENTRIES
                if entry.gender_condition != 'all'}
    assert gendered == {
        'GB46939-A6-03': 'female_only', 'GB46939-A6-04': 'male_only',
    }


def test_uniform_three_answers_compute_each_category_and_preserve_exact_scores():
    answers = {entry.entry_id: '3' for entry in RULE_ENTRIES}
    result = evaluate_constitution(answers, 'female')
    assert result['status'] == 'completed'
    assert result['standard_id'] == 'GB/T 46939—2025'
    assert result['questionnaire_version'] == 'appendixA-2025'
    assert result['gender'] == 'female'
    assert result['answers'] == answers
    for entry in RULE_ENTRIES:
        category = result['results'][entry.constitution]
        expected_count = 3 if entry.constitution == '湿热质' else \
            Counter(e.constitution for e in RULE_ENTRIES)[entry.constitution]
        assert category['item_count'] == expected_count
        assert category['raw_score'] == 3 * expected_count
        assert category['converted_score'] == Fraction(50)
        assert category['display_score'] == '50.00'
        assert category['result'] == ('否' if entry.constitution == '平和质' else '是')
        assert result['entry_sources'][entry.entry_id] == {
            'clause': entry.source_clause, 'pdf_page': entry.source_pdf_page,
        }
    assert result['results']['湿热质']['excluded_items'] == ['GB46939-A6-04']
    assert 'GB46939-A6-04' not in result['item_scores']
    assert [item['constitution'] for item in result['combined_results']] == [
        '气虚质', '阳虚质', '阴虚质', '痰湿质', '湿热质', '血瘀质', '气郁质', '特禀质',
    ]
    assert result['unknown'] == {'categories': [], 'items': {}}


def test_reverse_items_are_converted_before_raw_score_and_keep_original_answers():
    for value, expected in {'1': 5, '2': 4, '3': 3, '4': 2, '5': 1}.items():
        answers = {entry.entry_id: '3' for entry in RULE_ENTRIES}
        answers['GB46939-A1-02'] = value
        result = evaluate_constitution(answers, 'female')
        assert result['item_scores']['GB46939-A1-02'] == expected
        assert result['answers']['GB46939-A1-02'] == value
        assert result['results']['平和质']['raw_score'] == 9 + expected
        assert result['results']['平和质']['converted_score'] == \
            Fraction(9 + expected - 4, 16) * 100


def test_full_option_labels_are_accepted_without_rewriting_the_answer():
    result = evaluate_constitution({'GB46939-A2-01': '有时（有些）'}, '女性')
    assert result['gender'] == 'female'
    assert result['answers']['GB46939-A2-01'] == '有时（有些）'
    assert result['item_scores']['GB46939-A2-01'] == 3
    assert result['results']['气虚质']['result'] == 'unknown'
    assert result['results']['气虚质']['unknown_items'] == [
        'GB46939-A2-02', 'GB46939-A2-03',
    ]


def test_male_and_female_use_exactly_one_gender_specific_item():
    answers = {entry.entry_id: '3' for entry in RULE_ENTRIES}
    male = evaluate_constitution(answers, 'male')
    female = evaluate_constitution(answers, 'female')
    assert male['results']['湿热质']['item_count'] == 3
    assert male['results']['湿热质']['excluded_items'] == ['GB46939-A6-03']
    assert female['results']['湿热质']['item_count'] == 3
    assert female['results']['湿热质']['excluded_items'] == ['GB46939-A6-04']
    assert 'GB46939-A6-03' not in male['item_scores']
    assert 'GB46939-A6-04' not in female['item_scores']
    assert male['results']['湿热质']['raw_score'] == 9
    assert female['results']['湿热质']['raw_score'] == 9


def test_invalid_gender_is_rejected_even_with_complete_answers():
    answers = {entry.entry_id: '3' for entry in RULE_ENTRIES}
    for gender in (None, '', 'other', '未知'):
        with pytest.raises(ValueError, match='必须选择男性或女性'):
            evaluate_constitution(answers, gender)


def test_user_can_skip_the_whole_assessment_without_gender_or_results():
    result = evaluate_constitution({}, None, skipped=True)
    assert result['status'] == 'skipped'
    assert result['results'] == {}
    assert result['combined_results'] == []
    assert result['unknown'] == {'categories': [], 'items': {}}


def test_missing_applicable_answer_is_unknown_not_zero_or_normal():
    answers = {entry.entry_id: '3' for entry in RULE_ENTRIES}
    del answers['GB46939-A6-03']
    result = evaluate_constitution(answers, 'female')
    assert result['results']['湿热质']['result'] == 'unknown'
    assert result['results']['湿热质']['unknown_items'] == ['GB46939-A6-03']
    assert result['results']['湿热质']['excluded_items'] == ['GB46939-A6-04']
    assert result['results']['气虚质']['result'] == '是'
    assert '湿热质' not in [item['constitution'] for item in result['combined_results']]
    assert result['results']['平和质']['result'] == 'unknown'
    assert result['unknown']['categories'] == ['平和质', '湿热质']


def test_duplicate_and_unknown_entry_ids_fail_loud():
    with pytest.raises(ValueError, match='重复题号'):
        evaluate_constitution([('GB46939-A2-01', '1'), ('GB46939-A2-01', '2')], 'female')
    with pytest.raises(ValueError, match='未知题号'):
        evaluate_constitution({'UNKNOWN-01': '3'}, 'female')


@pytest.mark.parametrize('value', [3, None, True, 3.0])
def test_non_string_answer_fails_loud(value):
    with pytest.raises(TypeError, match='必须是字符串'):
        evaluate_constitution({'GB46939-A2-01': value}, 'female')


@pytest.mark.parametrize('value', ['', '   ', '0', '6', '-1', '1.5', 'abc'])
def test_empty_or_invalid_score_fails_loud(value):
    with pytest.raises(ValueError):
        evaluate_constitution({'GB46939-A2-01': value}, 'female')


def test_malformed_answer_containers_fail_loud():
    with pytest.raises(TypeError):
        evaluate_constitution('3', 'female')
    with pytest.raises(TypeError):
        evaluate_constitution(['GB46939-A2-01'], 'female')


def _complete_answers():
    return {entry.entry_id: '5' if entry.score_direction == 'reverse' else '1'
            for entry in RULE_ENTRIES}


def _set_raw_score(answers, constitution, raw_score):
    entries = [entry for entry in RULE_ENTRIES
               if entry.constitution == constitution and entry.entry_id != 'GB46939-A6-04']
    base, remainder = divmod(raw_score, len(entries))
    for index, entry in enumerate(entries):
        value = base + int(index < remainder)
        assert 1 <= value <= 5
        answers[entry.entry_id] = str(6 - value if entry.score_direction == 'reverse' else value)


def test_biased_boundaries_and_repeating_fraction_remain_exact():
    for raw_score, expected_result, expected_score in (
            (6, '否', Fraction(25)),
            (7, '倾向是', Fraction(100, 3)),
            (8, '是', Fraction(125, 3))):
        answers = _complete_answers()
        _set_raw_score(answers, '气虚质', raw_score)
        category = evaluate_constitution(answers, 'female')['results']['气虚质']
        assert category['result'] == expected_result
        assert category['converted_score'] == expected_score
    answers = _complete_answers()
    _set_raw_score(answers, '气虚质', 7)
    category = evaluate_constitution(answers, 'female')['results']['气虚质']
    assert category['display_score'] == '33.33'
    assert category['converted_score'] == Fraction(100, 3)


def test_peaceful_result_requires_own_score_and_all_other_scores():
    for other_raw, expected in ((25, '是'), (31.25, '基本是'), (37.5, '基本是'),
                                (43.75, '否')):
        answers = _complete_answers()
        for constitution in ('气虚质', '阳虚质', '阴虚质', '痰湿质', '湿热质',
                             '血瘀质', '气郁质', '特禀质'):
            raw = {25: 6, 31.25: 7, 37.5: 7, 43.75: 9}[other_raw]
            if constitution == '特禀质':
                raw = {25: 8, 31.25: 9, 37.5: 9, 43.75: 11}[other_raw]
            _set_raw_score(answers, constitution, raw)
        _set_raw_score(answers, '平和质', 14)
        result = evaluate_constitution(answers, 'female')['results']['平和质']
        assert result['result'] == expected
        assert result['converted_score'] == Fraction(125, 2)
    answers = _complete_answers()
    _set_raw_score(answers, '平和质', 13)
    assert evaluate_constitution(answers, 'female')['results']['平和质']['result'] == '否'


def test_multiple_biased_results_are_preserved_in_standard_order_not_by_score():
    answers = _complete_answers()
    _set_raw_score(answers, '气虚质', 11)
    _set_raw_score(answers, '阳虚质', 7)
    _set_raw_score(answers, '痰湿质', 7)
    _set_raw_score(answers, '湿热质', 9)
    result = evaluate_constitution(answers, 'female')
    assert [(item['constitution'], item['result']) for item in result['combined_results']] == [
        ('气虚质', '是'), ('阳虚质', '倾向是'), ('痰湿质', '倾向是'), ('湿热质', '是'),
    ]
    assert result['combined_results'][0]['converted_score'] == Fraction(200, 3)
    assert result['combined_results'][1]['converted_score'] == Fraction(100, 3)
    assert result['combined_results'][2]['converted_score'] == Fraction(100, 3)


def test_unknown_categories_are_separate_from_combined_results():
    answers = _complete_answers()
    _set_raw_score(answers, '气虚质', 11)
    del answers['GB46939-A8-02']
    result = evaluate_constitution(answers, 'female')
    assert [item['constitution'] for item in result['combined_results']] == ['气虚质']
    assert result['unknown']['categories'] == ['平和质', '气郁质']
    assert result['unknown']['items'] == {'气郁质': ['GB46939-A8-02']}
    assert result['results']['平和质']['result'] == 'unknown'


def test_all_minimum_answers_produce_zero_without_fabricating_positive_results():
    result = evaluate_constitution(_complete_answers(), 'female')
    for constitution, category in result['results'].items():
        assert category['raw_score'] == category['item_count']
        assert category['converted_score'] == 0
        assert category['result'] == '否'
    assert result['combined_results'] == []
    assert result['unknown'] == {'categories': [], 'items': {}}
