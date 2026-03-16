"""
Task JSON validator — validates task dicts against the JSON Schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).parent / "schema.json"
_schema: dict | None = None


def _get_schema() -> dict:
    global _schema
    if _schema is None:
        _schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema


def validate_task(task_dict: dict) -> tuple[bool, list[str]]:
    """
    Validate a task dict against the Task JSON Schema.

    Returns:
        (True, [])                  — valid
        (False, ["error1", ...])    — invalid, with error messages
    """
    schema = _get_schema()
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(task_dict), key=lambda e: list(e.path))
    if not errors:
        return True, []
    messages = [f"{'.'.join(str(p) for p in e.path) or 'root'}: {e.message}" for e in errors]
    return False, messages
