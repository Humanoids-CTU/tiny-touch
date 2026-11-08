from dataclasses import replace
import json

import pytest

from adapters.coding_configs import CodingConfigStore, validate_coding_setup
from domain.coding_setup import CodingSetup, default_coding_setup


def test_mapping_is_immutable_and_portable(tmp_path):
    setup = replace(default_coding_setup('general'), channel_zones={
        'RH': ['1', '9'], 'LH': [], 'RL': ['11'], 'LL': ['12']})
    assert setup.channel_zones['RH'] == ('1', '9')
    with pytest.raises(TypeError):
        setup.channel_zones['RH'] = ('2',)
    raw = setup.to_dict()
    assert raw['schema_version'] == 2
    assert raw['channel_zones']['Channel1'] == ['1', '9']
    assert CodingSetup.from_dict(json.loads(json.dumps(raw))) == setup
    store = CodingConfigStore(tmp_path)
    assert store.load(store.save(setup, 'study')) == setup


def test_schema_one_general_preserves_historical_footer_ids():
    raw = default_coding_setup('general').to_dict()
    raw['schema_version'] = 1
    raw.pop('channel_zones', None)
    raw.pop('zone_layout', None)
    raw['zone_labels'] = {'Channel1': 'Parent'}
    setup = CodingSetup.from_dict(raw)
    assert setup.zone_layout == 'legacy'
    assert setup.channel_zones['RH'] == ('Channel1',)
    assert validate_coding_setup(setup) is setup
    assert CodingSetup.from_dict(setup.to_dict()) == setup


@pytest.mark.parametrize('template,expected', [
    ('default', ('N', 'M', 'B', 'A')),
    ('alternate', ('L', 'K', 'B', 'A')),
    ('general', ('9', '10', '11', '12')),
])
def test_template_channel_mapping(template, expected):
    assert tuple(default_coding_setup(template).channel_zones.values()) == tuple((zone,) for zone in expected)


@pytest.mark.parametrize('zones', [
    {'RH': ['1'], 'LH': ['1'], 'RL': [], 'LL': []},
    {'RH': ['1', '1'], 'LH': [], 'RL': [], 'LL': []},
    {'RH': '1', 'LH': [], 'RL': [], 'LL': []},
    {'RH': [], 'LH': [], 'RL': []},
])
def test_invalid_mapping_is_rejected(zones):
    with pytest.raises(ValueError):
        replace(default_coding_setup('general'), channel_zones=zones)


@pytest.mark.parametrize('zone', ['unknown', 'NN', 'LINE', 'Channel1'])
def test_adapter_rejects_non_target_mapping(zone):
    setup = replace(default_coding_setup('general'), channel_zones={
        'RH': [zone], 'LH': [], 'RL': [], 'LL': []})
    with pytest.raises(ValueError):
        validate_coding_setup(setup)


def test_schema_two_requires_explicit_mapping():
    raw = default_coding_setup().to_dict()
    raw.pop('channel_zones', None)
    with pytest.raises(ValueError):
        CodingSetup.from_dict(raw)
