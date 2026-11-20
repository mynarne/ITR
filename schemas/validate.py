"""Validate ITR 1.0 JSON shapes using only Python's standard library.

Implements the keywords used in the bundled schema. File hashes, references,
ordering, and storage policy are checked by the ITR engine.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


class Invalid(ValueError):
    """The supplied JSON value does not satisfy the schema."""


SCHEMA_PATH = Path(__file__).with_name("record.schema.json")
KEYWORDS = {
    "$schema", "$defs", "$ref", "title", "description", "default",
    "type", "const", "enum", "pattern", "format", "minLength", "maxLength",
    "minimum", "properties", "required", "additionalProperties",
    "items", "minItems", "uniqueItems", "anyOf", "allOf", "if", "then", "else",
}
TYPES = {
    "null": lambda value: value is None,
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: type(value) is int or
        (type(value) is float and value.is_integer()),
    "string": lambda value: isinstance(value, str),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid(f"중복 객체 키 {key!r}")
        result[key] = value
    return result


def _invalid_constant(name):
    raise Invalid(f"JSON에 없는 숫자 {name}")


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_object, parse_constant=_invalid_constant)


def _matches(value, spec, root, path):
    try:
        _check(value, spec, root, path)
    except Invalid:
        return False
    return True


def _check(value, spec, root, path):
    unsupported = set(spec) - KEYWORDS
    if unsupported:
        raise RuntimeError(f"검사기가 지원하지 않는 스키마 키 {sorted(unsupported)}")
    if "$ref" in spec:
        ref = spec["$ref"]
        if not ref.startswith("#/$defs/"):
            raise RuntimeError(f"검사기가 지원하지 않는 참조 {ref}")
        _check(value, root["$defs"][ref[len("#/$defs/"):]], root, path)
    if "type" in spec and not TYPES[spec["type"]](value):
        raise Invalid(f"{path} 기대 형식 {spec['type']}")
    if "enum" in spec and value not in spec["enum"]:
        raise Invalid(f"{path} 허용값 {spec['enum']}")
    if "const" in spec and value != spec["const"]:
        raise Invalid(f"{path} 고정값 {spec['const']!r}")
    for part in spec.get("allOf", []):
        _check(value, part, root, path)
    if "anyOf" in spec and not any(
        _matches(value, part, root, path) for part in spec["anyOf"]
    ):
        raise Invalid(f"{path} 허용된 형식과 일치하지 않음")
    if "if" in spec:
        branch = "then" if _matches(value, spec["if"], root, path) else "else"
        if branch in spec:
            _check(value, spec[branch], root, path)

    if isinstance(value, dict):
        missing = set(spec.get("required", [])) - set(value)
        if missing:
            raise Invalid(f"{path} 필수 키 누락 {sorted(missing)}")
        properties = spec.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _check(item, properties[key], root, f"{path}.{key}")
            elif spec.get("additionalProperties") is False:
                raise Invalid(f"{path} 정의되지 않은 키 {key!r}")
    elif isinstance(value, list):
        if len(value) < spec.get("minItems", 0):
            raise Invalid(f"{path} 최소 항목 수 {spec['minItems']}")
        if spec.get("uniqueItems"):
            # The v1 schema uses uniqueItems only on arrays of string IDs.
            seen = set()
            for item in value:
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    raise Invalid(f"{path} 중복 항목")
                seen.add(key)
        if "items" in spec:
            for index, item in enumerate(value):
                _check(item, spec["items"], root, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < spec.get("minLength", 0):
            raise Invalid(f"{path} 최소 문자 수 {spec['minLength']}")
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            raise Invalid(f"{path} 최대 문자 수 {spec['maxLength']}")
        if "pattern" in spec and re.search(spec["pattern"], value, re.ASCII) is None:
            raise Invalid(f"{path} 패턴 불일치 {spec['pattern']}")
        if "format" in spec:
            if spec["format"] != "date-time":
                raise RuntimeError(f"검사기가 지원하지 않는 포맷 {spec['format']}")
            try:
                stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.utcoffset() is None or (not value.endswith("Z") and int(value[-2:]) > 59):
                    raise ValueError("offset")
            except ValueError as error:
                raise Invalid(f"{path} 오프셋을 포함한 날짜·시각 필요") from error
    elif type(value) in (int, float) and "minimum" in spec:
        if value < spec["minimum"]:
            raise Invalid(f"{path} 최솟값 {spec['minimum']}")


def validate(value, part=None, *, schema_path=SCHEMA_PATH):
    """Raise Invalid on shape errors, or return None for a valid ITR value."""
    root = read_json(schema_path)
    spec = root if part is None else root["$defs"][part]
    _check(value, spec, root, "$")


def main():
    parser = argparse.ArgumentParser(description="ITR 1.0 기록의 필드 및 자료형 검사")
    parser.add_argument("record", type=Path, nargs="+")
    parser.add_argument("--part", choices=sorted(read_json(SCHEMA_PATH)["$defs"]),
                        help="예: input, event, evidence, defect")
    args = parser.parse_args()
    for path in args.record:
        try:
            validate(read_json(path), part=args.part)
        except (ValueError, OSError, UnicodeError) as error:
            print(f"{path} — {error}", file=sys.stderr)
            return 1
        print(f"형식 유효  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
