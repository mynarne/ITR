"""Deterministic synthetic QA adapters. They receive no other role's verdict."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from itr_store import digest, need

RULES = [
    ("G-TOTAL", "goal", "고객에게 품목 금액과 배송비를 합한 원화 청구액을 표시한다."),
    ("R-FREE", "requirement", "품목 합계가 10,000원 이상이면 배송비는 0원, 미만이면 3,000원이다."),
    ("R-CONTRACT", "requirement", "영수증 JSON은 subtotal, shipping, total, currency 필드를 제공한다."),
    ("R-OFFLINE", "rule", "합성 결제기는 원화 단위를 사용하고 외부 동기화를 끈다."),
    ("R-DEVICE", "requirement", "선택된 실제 휴대 단말에서 현장 직원이 영수증을 읽을 수 있다."),
    ("R-LEDGER", "requirement", "별도 합성 장부가 제공된 회차에만 외부 장부 인계 시나리오를 검증한다."),
]

# id, title, stage, method, role, baselines, criterion, capabilities, prerequisites
PLAN = [
    ("unit-subtotal", "품목 합계", "unit", "execution", "runner", ["G-TOTAL"],
     "2×2,500원과 1×1,000원의 품목 합계가 6,000원이다.", ["local_python"], []),
    ("bb-goal", "장바구니 결제", "acceptance", "execution", "bb_goal", ["G-TOTAL", "R-FREE"],
     "6,000원 상품 2개의 청구액이 12,000원이며 배송비가 0원이다.", ["local_python"], ["system-receipt"]),
    ("bb-context", "소액 주문 영수증", "system", "execution", "bb_context", ["G-TOTAL", "R-CONTRACT"],
     "4,000원 주문에서 배송비를 포함한 7,000원과 KRW가 출력된다.", ["local_python"], ["integration-basket"]),
    ("bb-boundary", "무료 배송 경계", "system", "execution", "bb_boundary", ["G-TOTAL", "R-FREE"],
     "9,999원·10,000원·10,001원의 배송비가 순서대로 3,000·0·0원이다.", ["local_python"], ["integration-basket"]),
    ("wb-logic", "경계 비교식", "unit", "inspection", "wb_logic", ["R-FREE"],
     "배송비 분기의 AST가 subtotal >= 10000이고 참/거짓 금액이 0/3000이다.", ["source"], ["unit-subtotal"]),
    ("wb-contract", "영수증 출력 계약", "integration", "inspection", "wb_contract", ["R-CONTRACT"],
     "receipt가 반환하는 딕셔너리 키가 규정된 네 키와 일치한다.", ["source"], ["unit-subtotal"]),
    ("wb-config", "오프라인 설정", "system", "inspection", "wb_config", ["R-OFFLINE"],
     "설정 리터럴에서 통화 KRW 및 external_sync=false를 확인한다.", ["source"], ["unit-subtotal"]),
    ("integration-basket", "품목·배송비 결합", "integration", "execution", "runner", ["G-TOTAL", "R-CONTRACT"],
     "품목 합계 5,500원에 배송비 3,000원을 더해 8,500원의 영수증을 만든다.",
     ["local_python"], ["unit-subtotal", "wb-contract"]),
    ("system-receipt", "영수증 CLI 왕복", "system", "execution", "runner", ["G-TOTAL", "R-CONTRACT"],
     "12,500원 입력이 배송비 0원 및 총액 12,500원의 JSON으로 출력된다.",
     ["local_python"], ["integration-basket", "wb-contract"]),
    ("system-device", "실기기 열람", "system", "execution", "runner", ["R-DEVICE"],
     "실기기에서 직원이 추가 확대 없이 청구 총액을 정확히 읽는다.", ["physical_device"], ["integration-basket"]),
    ("link-ledger", "장부 인계", "intersystem", "execution", "runner", ["R-LEDGER"],
     "영수증과 장부 항목의 금액·통화가 일치한다.", ["sandbox_ledger"], ["integration-basket"]),
]

DELTA = {"unit-subtotal", "bb-goal", "bb-boundary", "wb-logic", "wb-contract", "integration-basket", "system-receipt"}


def subject_bytes(variant):
    source = Path(__file__).with_name("sample_receipt.py").read_bytes()
    if variant == "broken":
        needle = b"subtotal >= 10000"
        need(source.count(needle) == 1, "합성 소스의 경계 비교식 위치 불일치")
        return source.replace(needle, b"subtotal > 10000")
    return source


def plan(mode, source):
    checks = []
    for key, title, stage, method, role, criteria, condition, caps, deps in PLAN:
        selected = key != "link-ledger" if mode == "precision" else key in DELTA
        checks.append(dict(id=key, title=title, stage=stage, method=method, role=role,
                           criteria=criteria, pass_condition=condition, requires=caps,
                           depends_on=deps, selected=selected))
    return {"mode": mode, "product": "마을상점 영수증 · 합성 CLI", "revision": "sha256:" + digest(source),
            "baselines": [dict(id=key, kind=kind, text=text, version="1.0")
                          for key, kind, text in RULES],
            "capabilities": [dict(id=key, available=flag) for key, flag in
                             [("local_python", bool(sys.executable)), ("source", bool(source)),
                              ("physical_device", False), ("sandbox_ledger", False)]],
            "checks": checks}


def invoice(subject, items):
    # No workspace credentials or ambient application configuration enter the synthetic subject.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR") if k in os.environ}
    process = subprocess.run([sys.executable, "-I", "-B", str(subject)], input=json.dumps(items),
                             capture_output=True, text=True, encoding="utf-8", timeout=10, env=env,
                             cwd=subject.parent, check=True)
    return json.loads(process.stdout)


def inspect_source(key, text):
    tree = ast.parse(text)
    if key == "wb-config":
        value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(x, ast.Name) and x.id == "SETTINGS" for x in node.targets))
        return {"currency": "KRW", "external_sync": False}, ast.literal_eval(value)
    function = "shipping" if key == "wb-logic" else "receipt"
    node = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == function)
    expr = next(x.value for x in node.body if isinstance(x, ast.Return))
    if key == "wb-logic":
        expected = ast.parse("0 if subtotal >= 10000 else 3000", mode="eval").body
        return ast.dump(expected), ast.dump(expr)
    return sorted(["subtotal", "shipping", "total", "currency"]), sorted(ast.literal_eval(k) for k in expr.keys)


def observe(key, subject):
    """Trusted built-in adapters only. No user-supplied commands are interpreted."""
    if key.startswith("wb-"):
        expected, actual = inspect_source(key, subject.read_text(encoding="utf-8"))
        return expected, actual, {"source": "subject.py", "method": "Python AST"}
    if key == "unit-subtotal":
        # Isolate the real unit function from the CLI's transport and pricing layers.
        tree = ast.parse(subject.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "basket_subtotal")
        module = ast.Module(body=[fn], type_ignores=[])
        namespace = {"__builtins__": {"sum": sum}}
        exec(compile(module, "subject.py", "exec"), namespace)
        items = [[2, 2500], [1, 1000]]
        return 6000, namespace["basket_subtotal"](items), {"items": items}
    if key == "bb-boundary":
        totals = [9999, 10000, 10001]
        receipts = [invoice(subject, [[1, n]]) for n in totals]
        return [3000, 0, 0], [r["shipping"] for r in receipts], {"subtotals": totals, "receipts": receipts}
    items, subtotal, fee = {
        "bb-goal": ([[2, 6000]], 12000, 0),
        "bb-context": ([[1, 4000]], 4000, 3000),
        "integration-basket": ([[1, 2500], [2, 1500]], 5500, 3000),
        "system-receipt": ([[1, 12500]], 12500, 0),
    }[key]
    expected = dict(subtotal=subtotal, shipping=fee, total=subtotal + fee, currency="KRW")
    return expected, invoice(subject, items), {"items": items}
