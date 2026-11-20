"""Local synthetic subject. Input: [[quantity, unit price], ...], KRW."""
import json
import sys

SETTINGS = {"currency": "KRW", "external_sync": False}


def basket_subtotal(items):
    return sum(quantity * price for quantity, price in items)


def shipping(subtotal):
    return 0 if subtotal > 10000 else 3000


def receipt(items):
    subtotal = basket_subtotal(items)
    fee = shipping(subtotal)
    return {"subtotal": subtotal, "shipping": fee, "total": subtotal + fee,
            "currency": SETTINGS["currency"]}


if __name__ == "__main__":
    print(json.dumps(receipt(json.load(sys.stdin))))
