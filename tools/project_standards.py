"""Purpose-based standards mapping for project plans 1.1. The catalog holds names only, never ISO text."""
import json
import re
from pathlib import Path

from itr_store import need

CATALOG_PATH = Path(__file__).resolve().parents[1] / "schemas" / "standards.json"
QUALITY_MODELS = {"ISO/IEC 25010:2023", "ISO/IEC 25019:2023", "ISO/IEC 25012:2008"}
TECHNIQUES = "ISO/IEC/IEEE 29119-4:2021"
REVIEWS = "ISO/IEC 20246:2017"
IN_USE = {"ISO/IEC 25019:2023", "ISO 9241-11:2018"}
UX_ITEMS = {("ISO/IEC 25019:2023", "beneficialness.usability"), ("ISO/IEC 25019:2023", "beneficialness.accessibility")}
ITEM = re.compile(r"[a-z0-9_]+(\.[a-z0-9_]+)?")


def read_catalog(raw):
    data = json.loads(raw.decode("utf-8"))
    need(isinstance(data, dict) and data.get("catalog_version") == "1.0", "표준 목록 1.0 형식 오류")
    catalog = {}
    for entry in data["standards"]:
        need(entry["ref"] not in catalog and len(set(entry["items"])) == len(entry["items"]), "표준 목록 중복")
        catalog[entry["ref"]] = entry
    return catalog


def is_ux(tag):
    if tag["ref"] == "ISO/IEC 25010:2023":
        return any(item.startswith("interaction_capability.") for item in tag["items"])
    return any((tag["ref"], item) in UX_ITEMS for item in tag["items"])


def check_standards(plan_standards, checks, catalog):
    """Each check names the standards that fit its purpose; every applied item-level standard has a selected check."""
    need(isinstance(plan_standards, list) and all(
        isinstance(s, dict) and set(s) == {"edition", "applied", "reason"} and isinstance(s["applied"], bool)
        and all(isinstance(s[k], str) and s[k].strip() for k in ("edition", "reason")) for s in plan_standards),
        "표준 선택은 edition, applied, reason을 사용합니다.")
    editions = [s["edition"] for s in plan_standards]
    need(len(editions) == len(set(editions)), "표준 선택에 같은 판본이 두 번 있습니다.")
    applied = {s["edition"] for s in plan_standards if s["applied"]}
    used = set()
    for key, check in checks.items():
        tags = check.get("standards")
        need(isinstance(tags, list) and tags, f"{key} 검사에 적용 표준(standards)이 없습니다.")
        # A deferred check (selected: false) may name an edition this attempt does not apply yet.
        selected = check.get("selected", True)
        refs = [tag["ref"] for tag in tags]
        need(len(refs) == len(set(refs)), f"{key} 같은 표준을 두 번 붙였습니다.")
        for tag in tags:
            ref, items = tag["ref"], tag["items"]
            need(all(isinstance(item, str) and ITEM.fullmatch(item) for item in items), f"{key} {ref} 항목 이름 형식 오류")
            if selected:
                need(ref in applied, f"{key} 계획에서 적용하지 않은 표준 · {ref}")
            else:
                need(ref in editions, f"{key} 계획의 표준 선택에 없는 판본 · {ref}")
            entry = catalog.get(ref)
            if entry and entry["items"]:
                need(items and set(items) <= set(entry["items"]), f"{key} {ref} 항목 오류 · 표준 목록의 항목만 씁니다.")
            elif entry:
                need(not items, f"{key} {ref}는 부 단위 표준이라 항목을 붙이지 않습니다.")
        refs = set(refs)
        if selected:
            used |= refs
        need(refs & QUALITY_MODELS, f"{key} 품질 모델(25010·25019·25012) 항목이 필요합니다.")
        need(check["method"] != "execution" or TECHNIQUES in refs, f"{key} 실행 검사에는 29119-4 설계 기법이 필요합니다.")
        need(check["method"] != "inspection" or REVIEWS in refs, f"{key} 인스펙션에는 20246 리뷰 항목이 필요합니다.")
        need(not any(is_ux(tag) for tag in tags) or any(r.startswith("ISO 9241-") and r in catalog for r in refs),
             f"{key} UX/UI 검사에는 표준 목록의 ISO 9241 부가 필요합니다.")
        need((check["stage"] != "acceptance" and check["role"] != "bb_context") or refs & IN_USE,
             f"{key} 인수·사용 맥락 검사에는 25019 또는 9241-11이 필요합니다.")
    for ref in sorted(applied - used):
        need(not (catalog.get(ref) or {}).get("items"),
             f"적용으로 표시한 {ref}에 연결된 검사가 없습니다. 선택하지 않은 검사는 세지 않습니다.")
    return used
