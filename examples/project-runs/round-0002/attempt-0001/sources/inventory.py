"""합성 재고 분류기. 실서비스나 외부 데이터를 사용하지 않는다."""
import sys


def stock_status(remaining):
    """Return the display label for a synthetic quantity."""
    if remaining < 0:
        return "empty"
    if remaining <= 2:
        return "low"
    return "ready"


if __name__ == "__main__":
    print(stock_status(int(sys.argv[1])))
