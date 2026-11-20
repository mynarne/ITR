"""ITR 일반 어댑터에서 호출하는 작은 프로젝트 소유 검사."""
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CASES = {
    "regular": (5, "ready"),
    "low": (2, "low"),
    "zero": (0, "empty"),
}


def main(case):
    remaining, expected = CASES[case]
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(HERE / "inventory.py"), str(remaining)],
        capture_output=True, text=True, timeout=3, check=True,
    )
    actual = result.stdout.strip()
    print(f"remaining={remaining} expected={expected} actual={actual}")
    return 0 if actual == expected else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
