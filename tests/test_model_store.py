import json

import pytest

from model_store import ModelStore, ModelConfigError, sampling_params, PARAMETERS


@pytest.fixture
def store(tmp_path):
    result = ModelStore(str(tmp_path / 'profiles.json'), str(tmp_path / 'users.json'), 'dual')
    result.merge_discovered([{'id': 'dual', 'type': 'both'}, {'id': 'plain', 'type': 'non_thinking'},
                             {'id': 'reasoner', 'type': 'thinking'}])
    return result


def test_selection_defaults_isolation_restart_and_mode_restrictions(store):
    assert store.current(1)['mode'] == 'thinking'
    store.set_mode(1, 'non_thinking')
    assert store.current(2)['mode'] == 'thinking'
    reopened = ModelStore(str(store.path), str(store.selections_path), 'dual')
    assert reopened.current(1)['mode'] == 'non_thinking'
    store.select(1, 'reasoner')
    assert store.current(1)['mode'] == 'thinking'
    with pytest.raises(ModelConfigError):
        store.set_mode(1, 'non_thinking')
    store.select(1, 'plain')
    assert store.current(1)['mode'] == 'non_thinking'
    assert store.current(1)['reasoning_effort'] is None
    with pytest.raises(ModelConfigError):
        store.set_mode(1, 'thinking')
    store.select(1, 'dual')
    assert store.current(1)['mode'] == 'thinking'


def test_parameters_isolated_by_model_and_mode(store):
    store.update_params(1, {'temperature': '0.6', 'max_tokens': '4096'})
    store.update_params(1, {'temperature': '0.2'}, 'non_thinking')
    assert store.current(1)['parameters'] == {'temperature': 0.6, 'max_tokens': 4096}
    store.set_mode(1, 'non_thinking')
    assert store.current(1)['parameters'] == {'temperature': 0.2}
    store.select(1, 'plain')
    assert store.current(1)['parameters'] == {}
    assert store.current(2)['parameters']['temperature'] == 0.6


def test_blank_defaults_hot_reload_and_discovery_preserves_edits(store):
    store.update_params(1, dict.fromkeys(PARAMETERS, 'default'))
    assert store.current(1)['parameters'] == {}
    data = store.profiles()
    data['models']['dual']['thinking'] = {'temperature': '', 'max_tokens': None, 'top_p': 0.8}
    data['models']['dual']['thinking_effort'] = 'high'
    store.path.write_text(json.dumps(data))
    store.merge_discovered([{'id': 'dual', 'type': 'non_thinking'}])
    assert store.current(1)['type'] == 'both'
    assert store.current(1)['reasoning_effort'] == 'high'
    assert store.current(1)['parameters'] == {'top_p': 0.8}


@pytest.mark.parametrize('name,value', [('top_k', 1.5), ('max_tokens', 0), ('top_p', 1.1),
    ('min_p', -1), ('temperature', 'nan'), ('temperature', True), ('presence_penalty', 3), ('oops', 1)])
def test_invalid_update_does_not_write(store, name, value):
    before = store.path.read_bytes()
    with pytest.raises(ModelConfigError):
        store.update_params(1, {'temperature': 0.4, name: value})
    assert store.path.read_bytes() == before


def test_corrupt_file_is_not_overwritten(store):
    store.path.write_text('{broken')
    with pytest.raises(ModelConfigError):
        store.merge_discovered([])
    assert store.path.read_text() == '{broken'


def test_unknown_model_requires_manual_capability(store):
    store.merge_discovered([{'id': 'unknown', 'type': 'unknown'}])
    with pytest.raises(ModelConfigError):
        store.select(1, 'unknown')


def test_unlimited_tokens_and_zero_values():
    assert sampling_params({'max_tokens': -1, 'top_k': 0, 'temperature': 0}) == {
        'max_tokens': -1, 'top_k': 0, 'temperature': 0}


def test_extended_profiles_preserve_metadata_and_reasoning_precedence(store):
    data = store.profiles()
    data['official_recommendations_metadata'] = {'note': 'reference only'}
    profile = data['models']['dual']
    profile['official_recommendations'] = {'task_presets': {'precise': {'temperature': 0.1}}}
    profile['thinking_effort'] = 'medium'
    profile['thinking'] = {'repetition_penalty': 1.05, 'reasoning_effort': 'xhigh',
                           'chat_template_kwargs': {'enable_thinking': True, 'preserve_thinking': True}}
    profile['non_thinking'] = {'chat_template_kwargs': {'enable_thinking': False}}
    store.path.write_text(json.dumps(data), encoding='utf-8')
    current = store.current(1)
    assert current['reasoning_effort'] == 'xhigh'
    assert current['parameters']['repetition_penalty'] == 1.05
    assert 'reasoning_effort' not in current['parameters']
    assert 'official_recommendations' not in current['parameters']
    store.update_params(1, {'chat_template_kwargs.preserve_thinking': 'false'})
    assert store.current(1)['parameters']['chat_template_kwargs'] == {'enable_thinking': True, 'preserve_thinking': False}
    store.update_params(1, {'chat_template_kwargs.preserve_thinking': ''})
    assert store.current(1)['parameters']['chat_template_kwargs'] == {'enable_thinking': True}
    store.update_params(1, {'reasoning_effort': ''})
    assert store.current(1)['reasoning_effort'] is None
    store.set_mode(1, 'non_thinking')
    assert store.current(1)['reasoning_effort'] == 'none'
    assert store.current(1)['parameters'] == {'chat_template_kwargs': {'enable_thinking': False}}
    reloaded = store.profiles()
    assert reloaded['official_recommendations_metadata'] == data['official_recommendations_metadata']
    assert reloaded['models']['dual']['official_recommendations'] == profile['official_recommendations']


@pytest.mark.parametrize('changes', [
    {'repetition_penalty': 0}, {'repetition_penalty': -1}, {'repeat_penalty': True},
    {'repetition_penalty': 'inf'}, {'repetition_penalty': 1, 'repeat_penalty': 1.1},
    {'reasoning_effort': 'wrong'}, {'reasoning_effort': 'none'},
    {'chat_template_kwargs': []}, {'chat_template_kwargs': {'enable_thinking': 'false'}},
    {'chat_template_kwargs': {'enable_thinking': False}},
    {'chat_template_kwargs.preserve_thinking': '1'}, {'chat_template_kwargs.unknown': True},
    {'chat_template_kwargs': {}, 'chat_template_kwargs.enable_thinking': True},
    {'messages': []}, {'stream': False},
])
def test_invalid_extended_updates_are_atomic(store, changes):
    before = store.path.read_bytes()
    with pytest.raises(ModelConfigError):
        store.update_params(1, changes)
    assert store.path.read_bytes() == before


def test_alias_updates_and_blank_template_defaults(store):
    store.update_params(1, {'repetition_penalty': 1.05})
    store.update_params(1, {'repeat_penalty': 1.2})
    assert store.current(1)['parameters'] == {'repeat_penalty': 1.2}
    store.update_params(1, {'repetition_penalty': ''})
    assert store.current(1)['parameters'] == {}
    assert sampling_params({'chat_template_kwargs': {'enable_thinking': '', 'preserve_thinking': None}}) == {}
    assert sampling_params({'chat_template_kwargs': {}}) == {}
    assert sampling_params({'chat_template_kwargs': {'enable_thinking': False}}) == {
        'chat_template_kwargs': {'enable_thinking': False}}
