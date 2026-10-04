"""Byte-bound schema qualification must preserve current validation semantics."""
import json
import os

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from scripts import validate_json as v


def save(path, identifier='urn:cache:stage', **fields):
    path.write_text(json.dumps({'$schema': v.DIALECT, '$id': identifier, **fields}))
    return path


def test_unchanged_bytes_reuse_qualification_but_not_mutable_validators(tmp_path, monkeypatch):
    path = save(tmp_path/'stage.schema.json', type='object', additionalProperties=False)
    calls = []
    original = Draft202012Validator.check_schema
    def check(schema):
        calls.append(schema['$id'])
        return original(schema)
    monkeypatch.setattr(Draft202012Validator, 'check_schema', check)
    first = v.build_validator(path, tmp_path)
    assert list(first.iter_errors({'unknown': True}))
    first.schema['additionalProperties'] = True
    first._registry.contents('urn:cache:stage')['additionalProperties'] = True
    second = v.build_validator(path, tmp_path)
    assert list(second.iter_errors({'unknown': True}))
    assert first is not second
    assert calls == ['urn:cache:stage']


def test_same_size_schema_edit_with_restored_mtime_invalidates(tmp_path):
    path = save(tmp_path/'stage.schema.json', type='string')
    assert v.build_validator(path, tmp_path).is_valid('text')
    stat = path.stat()
    before = path.read_bytes()
    path.write_bytes(before.replace(b'string', b'number'))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    changed = v.build_validator(path, tmp_path)
    assert changed.is_valid(1) and not changed.is_valid('text')


@pytest.mark.parametrize('fault', ['invalid-schema', 'duplicate-id', 'malformed-json', 'wrong-dialect'])
def test_added_bad_member_cannot_reuse_previous_qualification(tmp_path, fault):
    path = save(tmp_path/'stage.schema.json', type='string')
    v.build_validator(path, tmp_path)
    added = tmp_path/'new.schema.json'
    save(added, 'urn:cache:extra', type='string')
    if fault == 'invalid-schema': save(added, 'urn:cache:extra', type='bogus')
    if fault == 'duplicate-id': save(added, type='string')
    if fault == 'malformed-json': added.write_text('{')
    if fault == 'wrong-dialect': added.write_text('{"$schema":"wrong","$id":"urn:cache:extra"}')
    with pytest.raises((ValueError, SchemaError)):
        v.build_validator(path, tmp_path)
    added.unlink()
    assert v.build_validator(path, tmp_path).is_valid('text')


def test_reference_changes_and_removal_are_observed(tmp_path):
    stage = save(tmp_path/'stage.schema.json', **{'$ref': 'urn:cache:dependency'})
    dependency = save(tmp_path/'dependency.schema.json', 'urn:cache:dependency', type='string')
    assert v.build_validator(stage, tmp_path).is_valid('text')
    save(dependency, 'urn:cache:dependency', type='number')
    assert not v.build_validator(stage, tmp_path).is_valid('text')
    dependency.unlink()
    with pytest.raises(Unresolvable):
        v.build_validator(stage, tmp_path).validate('text')


def test_warm_and_cold_document_errors_are_equivalent():
    path = v.SCHEMA_DIR/'analysis.schema.json'
    instance = v.load_json(v.ROOT/'examples/contracts/analysis.json')
    instance['unknown'] = 'must reject'
    v._qualify_snapshot.cache_clear()
    def errors():
        return sorted((v.json_pointer(e.absolute_path), e.message)
                      for e in v.build_validator(path).iter_errors(instance))
    cold = errors()
    assert cold and errors() == cold
