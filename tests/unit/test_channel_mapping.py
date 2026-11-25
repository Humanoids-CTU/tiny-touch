from dataclasses import replace
import json

import pytest

from adapters.coding_configs import CodingConfigStore, validate_coding_setup
from domain.coding_setup import CodingSetup, default_coding_setup


def test_mapping_is_immutable_and_portable(tmp_path):
    setup = replace(default_coding_setup('general'), channel_zones={
        'RH': ['1', '9'], 'LH': [], 'RF': ['11'], 'LF': ['12']})
    assert setup.channel_zones['RH'] == ('1', '9')
    with pytest.raises(TypeError):
        setup.channel_zones['RH'] = ('2',)
    raw = setup.to_dict()
    assert raw['schema_version'] == 2
    assert raw['channel_zones']['Channel1'] == ['1', '9']
    assert CodingSetup.from_dict(json.loads(json.dumps(raw))) == setup
    store = CodingConfigStore(tmp_path)
    assert store.load(store.save(setup, 'study')) == setup


@pytest.mark.parametrize('change', [
    {'schema_version': 1},
    {'zone_layout': 'legacy'},
])
def test_configuration_from_an_older_version_must_be_recreated(tmp_path, change):
    raw = {**default_coding_setup('general').to_dict(), **change}
    with pytest.raises(ValueError, match='older version of TinyTouch'):
        CodingSetup.from_dict(raw)
    path = tmp_path / 'old.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    store = CodingConfigStore(tmp_path)
    assert store.list_configs() == []
    with pytest.raises(ValueError, match='Recreate it'):
        store.import_config(path, 'copy.json')
    assert not (tmp_path / 'copy.json').exists()


@pytest.mark.parametrize('template,expected', [
    ('default', ('N', 'M', 'B', 'A')),
    ('alternate', ('L', 'K', 'B', 'A')),
    ('general', ('9', '10', '11', '12')),
])
def test_template_channel_mapping(template, expected):
    assert tuple(default_coding_setup(template).channel_zones.values()) == tuple((zone,) for zone in expected)


@pytest.mark.parametrize('zones', [
    {'RH': ['1'], 'LH': ['1'], 'RF': [], 'LF': []},
    {'RH': ['1', '1'], 'LH': [], 'RF': [], 'LF': []},
    {'RH': '1', 'LH': [], 'RF': [], 'LF': []},
    {'RH': [], 'LH': [], 'RF': []},
])
def test_invalid_mapping_is_rejected(zones):
    with pytest.raises(ValueError):
        replace(default_coding_setup('general'), channel_zones=zones)


@pytest.mark.parametrize('zone', ['unknown', 'NN', 'LINE', 'Channel1'])
def test_adapter_rejects_non_target_mapping(zone):
    setup = replace(default_coding_setup('general'), channel_zones={
        'RH': [zone], 'LH': [], 'RF': [], 'LF': []})
    with pytest.raises(ValueError):
        validate_coding_setup(setup)


def test_schema_two_requires_explicit_mapping():
    raw = default_coding_setup().to_dict()
    raw.pop('channel_zones', None)
    with pytest.raises(ValueError):
        CodingSetup.from_dict(raw)
