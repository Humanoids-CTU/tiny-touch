import json
import pandas as pd
import pytest
from adapters.export_writer import export_from_unified
from adapters.export_reader import read_export_df
from domain.model import empty_bundle
from domain.touch_stats import parse_export

def write(tmp_path, frames, fps=25, last=201):
    path = tmp_path / 'export.csv'
    export_from_unified(frames, str(path), 'test', 'video', 'Normal', fps, None, last)
    return path

def test_versioned_export_preserves_paired_points_and_millisecond_precision(tmp_path):
    bundle = empty_bundle()
    bundle['RH'].update(X=[120,9], Y=[130,0], Zones=[['A','B'],['OUTSIDE']], Onset='ON')
    path = write(tmp_path, {1: bundle})
    raw = pd.read_csv(path, keep_default_na=False, dtype=str)
    assert raw.loc[201, 'Time_ms'] == '8040.000'
    assert json.loads(raw.loc[1, 'Channel1_XY']) == [[120,130],[9,0]]
    assert json.loads(raw.loc[1, 'Channel1_Zones']) == [['A','B'],['OUTSIDE']]
    assert json.loads(raw.loc[0, 'Channel1_XY']) == []
    episode = parse_export(read_export_df(str(path))).episodes['RH'][0]
    assert [(p.x,p.y,p.zones) for p in episode.points] == [(120,130,('A','B')), (9,0,('OUTSIDE',))]

def test_fractional_and_unknown_time(tmp_path):
    path = write(tmp_path, {}, fps=30, last=1)
    assert pd.read_csv(path, dtype=str).loc[1,'Time_ms'] == '33.333'
    for fps in (None, 0, -1, float('nan'), float('inf')):
        path = write(tmp_path, {}, fps=fps, last=1)
        assert pd.read_csv(path, keep_default_na=False).loc[1,'Time_ms'] == ''

def test_export_rejects_misaligned_points(tmp_path):
    bundle = empty_bundle()
    bundle['RH'].update(X=[1,2], Y=[3], Zones=[['A']])
    with pytest.raises(ValueError, match='align'):
        write(tmp_path, {0:bundle}, last=0)

def test_reader_rejects_malformed_v2_alignment(tmp_path):
    path = write(tmp_path, {}, last=0)
    df = pd.read_csv(path, keep_default_na=False)
    df.loc[0, 'Channel1_XY'] = '[[1, 2], [3, 4]]'
    df.loc[0, 'Channel1_Zones'] = '[["A"]]'
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match='align'):
        read_export_df(str(path))

def test_legacy_reader_preserves_multizone_annotations():
    from pathlib import Path
    path = Path(__file__).parent / 'fixtures' / 'golden_export.csv'
    df = read_export_df(str(path))
    assert json.loads(df.loc[5, 'RL_Zones']) == [['L','I']]

def test_save_failure_keeps_existing_pair_and_success_archives_legacy(tmp_path):
    from pathlib import Path
    from domain.project import ProjectPaths
    from service_layer.save_service import MetadataInputs, run_export
    paths = ProjectPaths('vid', base_dir=str(tmp_path))
    Path(paths.export_dir).mkdir(parents=True)
    old_csv, old_meta = b'old research CSV', b'{"template":"default"}'
    Path(paths.export_csv).write_bytes(old_csv)
    Path(paths.export_metadata).write_bytes(old_meta)
    metadata = MetadataInputs('test', 'vid', 'Normal', None, None, None, None, 'default')
    bundle = empty_bundle()
    bundle['RH'].update(X=[1,2],Y=[3],Zones=[['A']])
    with pytest.raises(ValueError,match='align'):
        run_export({0:bundle}, paths, 25, metadata, 1)
    assert Path(paths.export_csv).read_bytes() == old_csv
    assert Path(paths.export_metadata).read_bytes() == old_meta
    assert not list(Path(paths.export_dir).glob('legacy-*'))
    run_export({}, paths, 25, metadata, 1)
    archive, = Path(paths.export_dir).glob('legacy-*')
    assert (archive / Path(paths.export_csv).name).read_bytes() == old_csv
    assert (archive / Path(paths.export_metadata).name).read_bytes() == old_meta
    assert json.loads(Path(paths.export_metadata).read_text())['Export Format Version'] == 2
    assert 'Channel1_XY' in pd.read_csv(paths.export_csv).columns

def test_closed_episode_roundtrip_keeps_every_point_zone_and_parameter(tmp_path):
    frames = {}
    for frame,onset in ((1,'ON'),(3,'ON'),(5,'OFF')):
        bundle = empty_bundle()
        bundle['RH'].update(X=[120+frame,9], Y=[130,0], Zones=[['A','B'],['OUTSIDE']], Onset=onset)
        bundle['RH']['LimbParams'] = {'Par1':'ON','Par2':'OFF'}
        bundle['Params'] = {'Par2':'ON'}
        bundle['Note'] = 'paired, point zones'
        frames[frame] = bundle
    path = write(tmp_path, frames, last=6)
    raw = pd.read_csv(path,keep_default_na=False)
    assert len(raw) == 7
    assert raw.loc[3,'Channel1_Parameter_1'] == 'ON'
    assert raw.loc[3,'Parameter_2'] == 'ON'
    assert raw.loc[3,'Note'] == 'paired, point zones'
    episode, = parse_export(read_export_df(str(path))).episodes['RH']
    assert episode.closed
    assert episode.end_frame - episode.start_frame == 4
    assert len(episode.points) == 6
    assert [(p.x,p.y,p.zones) for p in episode.points] == [
        (120+frame,130,('A','B')) if point == 0 else (9,0,('OUTSIDE',))
        for frame in (1,3,5) for point in (0,1)
    ]
