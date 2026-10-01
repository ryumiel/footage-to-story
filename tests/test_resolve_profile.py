"""Synthetic profile inheritance and binding regressions."""
from copy import deepcopy
import shutil

import pytest

from scripts.resolve_profile import ProfileError, ROOT, check_selects_binding, main, resolve_profile


@pytest.fixture
def profiles(tmp_path):
    target = tmp_path / 'profiles'
    shutil.copytree(ROOT / 'profiles', target)
    return target


def test_existing_profiles_keep_meaning():
    winery = resolve_profile('winery', 'synthetic')
    assert [x['profile'] for x in winery['chain']] == ['base', 'travel_documentary', 'winery']
    assert winery['settings']['priorities']['dialogue'] == .9
    assert winery['settings']['priorities']['source_integrity'] == 1
    assert winery['settings']['preferred_topics'][0] == 'vineyard'
    assert winery['settings']['rules']['preserve_complete_thoughts'] is True
    assert resolve_profile('winery', 'synthetic') == winery
    cycling = resolve_profile('cycling', 'synthetic')
    assert [x['profile'] for x in cycling['chain']] == ['base', 'cycling']
    assert cycling['settings']['priorities']['dialogue'] == .25
    assert cycling['settings']['rules']['default_broll_seconds'] == [2, 6]


def selects(snapshot):
    return {'schema_version': '2.0.0', 'job_id': snapshot['job_id'],
            'profile': snapshot['profile'], 'profile_version': snapshot['profile_version'], 'items': []}


def test_parent_byte_change_invalidates_binding(profiles):
    snapshot = resolve_profile('winery', 'synthetic', profiles)
    check_selects_binding(selects(snapshot), snapshot, profiles)
    path = profiles / 'base.yaml'
    path.write_text(path.read_text() + '# Changed parent bytes\n')
    with pytest.raises(ProfileError, match='stale'):
        check_selects_binding(selects(snapshot), snapshot, profiles)
    changed = resolve_profile('winery', 'synthetic', profiles)
    assert changed['settings'] == snapshot['settings']
    assert changed['chain'] != snapshot['chain']


@pytest.mark.parametrize('field,value', [('job_id','other'), ('profile','cycling'), ('profile_version',2)])
def test_selects_identity_mismatch(field, value):
    snapshot = resolve_profile('winery', 'synthetic')
    data = selects(snapshot)
    data[field] = value
    with pytest.raises(ProfileError, match='does not match'):
        check_selects_binding(data, snapshot)


@pytest.mark.parametrize('body', [
    'profile: base\nversion: 1\nparent: base\n',
    'profile: base\nversion: 1\nparent: missing\n',
    'profile: base\nversion: 1\nversion: 2\nparent: null\n',
    'profile: base\nversion: 1\nparent: null\nunknown: true\n',
    'profile: base\nversion: 1\nparent: null\nrules: {unknown: true}\n',
    'profile: base\nversion: 1\nparent: null\npriorities: {dialogue: 2}\n',
    'profile: base\nversion: true\nparent: null\n',
    'profile: base\nversion: 1\nparent: null\npacing: {broll_seconds: [6, 2]}\n',
    'profile: base\nversion: 1\nparent: null\npriorities: {dialogue: .nan}\n',
    'profile: base\nversion: 1\nparent: null\nrules: &x {preserve_complete_thoughts: *x}\n',
    'profile: other\nversion: 1\nparent: null\n',
    'profile: base\nversion: 1\nparent: ../external\n',
    'profile: base\nversion: 1\nparent: null\nrules: {preserve_complete_thoughts: true, preserve_complete_thoughts: false}\n',
])
def test_reject_invalid_yaml(profiles, body):
    (profiles / 'base.yaml').write_text(body)
    with pytest.raises((ProfileError, ValueError)):
        resolve_profile('base', 'synthetic', profiles)


def test_lists_replace_and_mapping_merge(profiles):
    (profiles / 'cycling.yaml').write_text('profile: cycling\nversion: 7\nparent: base\nrules:\n  default_broll_seconds: [1, 3]\npreferred_topics: []\n')
    result = resolve_profile('cycling', 'synthetic', profiles)
    assert result['profile_version'] == 7
    assert result['settings']['rules']['default_broll_seconds'] == [1, 3]
    assert result['settings']['rules']['preserve_event_context'] is True
    assert result['settings']['preferred_topics'] == []


def test_altered_settings_rejected():
    snapshot = deepcopy(resolve_profile('winery', 'synthetic'))
    snapshot['settings']['priorities']['dialogue'] = .1
    with pytest.raises(ProfileError, match='altered'):
        check_selects_binding(selects(snapshot), snapshot)


def test_cli_writes_external_snapshot_without_overwrite(tmp_path):
    output = tmp_path / 'resolved.json'
    argv = ['winery', '--job-id', 'synthetic', '--output', str(output)]
    assert main(argv) == 0
    original = output.read_bytes()
    assert main(argv) == 1
    assert output.read_bytes() == original


def test_cli_rejects_committed_source_output():
    assert main(['winery', '--job-id', 'synthetic', '--output', str(ROOT / 'profiles' / 'bad.json')]) == 1


@pytest.mark.parametrize('native_value', ['2026-10-01', '2026-10-01T10:00:00Z', '!!binary dGVzdA=='])
def test_yaml_native_types_are_controlled_errors(profiles, native_value, tmp_path, capsys):
    (profiles / 'base.yaml').write_text(f'profile: base\nversion: 1\nparent: null\npreferred_topics: [{native_value}]\n')
    with pytest.raises(ProfileError, match='Cannot read profile'):
        resolve_profile('base', 'synthetic', profiles)
    assert main(['base', '--job-id', 'synthetic', '--profiles-dir', str(profiles),
                 '--output', str(tmp_path / 'out.json')]) == 1
    assert 'PROFILE_ERROR:' in capsys.readouterr().err
    assert not (tmp_path / 'out.json').exists()


def test_fifo_read_is_rejected_without_waiting_for_writer(tmp_path):
    import os
    import subprocess
    import sys
    fifo = tmp_path / 'base.yaml'
    os.mkfifo(fifo)
    result = subprocess.run([sys.executable, 'scripts/resolve_profile.py', 'base',
                             '--job-id', 'synthetic', '--profiles-dir', str(tmp_path),
                             '--output', str(tmp_path / 'out.json')],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'regular file' in result.stderr
    assert not (tmp_path / 'out.json').exists()


def test_profile_file_size_is_bounded(tmp_path):
    path = tmp_path / 'base.yaml'
    with path.open('wb') as stream:
        stream.truncate(1024 * 1024 + 1)
    with pytest.raises(ProfileError, match='exceeds 1 MiB'):
        resolve_profile('base', 'synthetic', tmp_path)


def test_growth_after_stat_is_bounded(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    from scripts.resolve_profile import _read_profile
    path = tmp_path / 'base.yaml'
    path.write_bytes(b'x' * (1024 * 1024 + 2))
    original = os.fstat
    def small_stat(fd):
        result = original(fd)
        return SimpleNamespace(st_mode=result.st_mode, st_size=1)
    monkeypatch.setattr(os, 'fstat', small_stat)
    with pytest.raises(ProfileError, match='exceeds 1 MiB'):
        _read_profile(path)


def test_device_file_is_rejected_before_read():
    from pathlib import Path
    from scripts.resolve_profile import _read_profile
    with pytest.raises(ProfileError, match='regular file'):
        _read_profile(Path('/dev/null'))
