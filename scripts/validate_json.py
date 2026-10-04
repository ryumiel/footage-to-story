"""Offline JSON Schema validation using existing libraries, not a custom engine.

Usage: python scripts/validate_json.py SCHEMA DATA [--schema-dir DIRECTORY]
Exit codes: 0 = schema-valid; 1 = contract violation; 2 = input/configuration error.
This command does NOT check cross-document/media integrity or authorize export.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "2.0.0"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    """Use the standard JSON parser; reject ambiguous keys and NaN/Infinity."""
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _schema_contents(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


@lru_cache(maxsize=8)
def _qualify_snapshot(snapshot: tuple[tuple[str, bytes], ...]) -> None:
    """Cache only successful schema self-validation, keyed by exact local bytes.

    Membership/path changes and edits, including same-size edits with restored
    mtimes, create a new key. No mutable schema or validator is shared with callers.
    Invalid snapshots raise and are not cached.
    """
    identifiers: set[str] = set()
    for path, raw in snapshot:
        schema = _schema_contents(raw)
        if not isinstance(schema, dict) or schema.get("$schema") != DIALECT:
            raise ValueError(f"Expected an explicit Draft 2020-12 schema: {path}")
        identifier = schema.get("$id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"Missing schema $id: {path}")
        if identifier in identifiers:
            raise ValueError(f"Duplicate schema $id: {identifier}")
        Draft202012Validator.check_schema(schema)
        identifiers.add(identifier)


def load_registry(schema_dir: Path = SCHEMA_DIR) -> Registry:
    """Read current schemas; reuse byte-bound qualification, never fetch remotely."""
    paths = sorted(schema_dir.resolve().rglob("*.schema.json"))
    if not paths:
        raise ValueError(f"No schema files found under {schema_dir}")
    snapshot = tuple((str(path), path.read_bytes()) for path in paths)
    _qualify_snapshot(snapshot)
    # Fresh parsed objects prevent a caller mutating a validator/registry from
    # poisoning subsequent validation. Document validation always runs normally.
    resources = []
    for _, raw in snapshot:
        schema = _schema_contents(raw)
        identifier = schema["$id"]
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def build_validator(schema_path: Path, schema_dir: Path = SCHEMA_DIR) -> Draft202012Validator:
    schema = load_json(schema_path)
    registry = load_registry(schema_dir)
    if not isinstance(schema, dict) or schema.get("$schema") != DIALECT:
        raise ValueError("The selected schema must explicitly use Draft 2020-12.")
    identifier = schema.get("$id")
    if not isinstance(identifier, str):
        raise ValueError("The selected schema must have an explicit $id.")
    try:
        registered = registry.contents(identifier)
    except NoSuchResource as exc:
        raise ValueError("The selected schema is not in the local registry.") from exc
    if registered != schema:
        raise ValueError("The selected schema must match a registered local schema.")
    if identifier.endswith("/common.schema.json"):
        raise ValueError("common.schema.json is a reference library, not a stage schema.")
    # Fail explicitly if the installed library cannot enforce the format we use.
    checker = FormatChecker()
    if "date-time" not in checker.checkers:
        raise ValueError("Install jsonschema[format-nongpl] to enable date-time validation.")
    return Draft202012Validator(schema, registry=registry, format_checker=checker)


def json_pointer(parts: Iterable[Any]) -> str:
    """Render a library-provided instance path without mixed-type sorting errors."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR)
    args = parser.parse_args(argv)
    try:
        validator = build_validator(args.schema, args.schema_dir)
        instance = load_json(args.data)
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda error: (json_pointer(error.absolute_path), str(error.validator), error.message),
        )
    except (OSError, ValueError, SchemaError, Unresolvable) as exc:
        print(f"INPUT_OR_SCHEMA_ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(
                f"SCHEMA_INVALID {json_pointer(error.absolute_path) or '<root>'}: {error.message}",
                file=sys.stderr,
            )
        return 1
    print("SCHEMA_VALID (domain integrity, approval authenticity, and export not checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
