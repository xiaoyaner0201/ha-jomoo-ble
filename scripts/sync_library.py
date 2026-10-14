"""Bundle our own pure library for copy-only custom-component installation."""

from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
FILES = ("__init__.py", "protocol.py", "client.py", "guard.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "custom_components/jomoo_ble/lib"
    if not args.check:
        target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        source = (ROOT / "jomoo_ble" / name).read_bytes()
        path = target / name
        if args.check:
            if not path.exists() or path.read_bytes() != source:
                raise SystemExit(f"Bundled library drift: {name}")
        else:
            path.write_bytes(source)
    print("Bundled library: identical")


if __name__ == "__main__":
    main()
