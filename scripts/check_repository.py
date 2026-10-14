"""Offline compile, metadata/link and basic public-artifact checks."""

from pathlib import Path
import json
import py_compile
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".ruff_cache", "build", "dist"}


def main():
    files = [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and not EXCLUDED.intersection(p.relative_to(ROOT).parts)
    ]
    python = [p for p in files if p.suffix == ".py"]
    if not python:
        raise SystemExit("No Python sources inspected")
    with tempfile.TemporaryDirectory() as cache:
        for index, path in enumerate(python):
            py_compile.compile(str(path), cfile=str(Path(cache) / f"{index}.pyc"), doraise=True)
    for path in files:
        if path.suffix == ".json":
            json.loads(path.read_text())
        if path.suffix == ".md":
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
                if "://" not in target and not target.startswith("#"):
                    local = target.split("#", 1)[0]
                    if not (path.parent / local).is_file():
                        raise SystemExit(f"Broken local link in {path.relative_to(ROOT)}: {target}")
        if path.suffix in {".wxapkg", ".pcap", ".pcapng"}:
            raise SystemExit("Private vendor/capture artifact present")
        if path.suffix in {".py", ".json", ".md", ".toml", ".yml", ".yaml"}:
            text = path.read_text()
            # Assemble private-path patterns so this check does not self-match.
            if "/" + "Users/" in text or "/" + "Volumes/" in text:
                raise SystemExit(f"Private absolute path in {path.relative_to(ROOT)}")
            addresses = re.findall(
                r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])", text
            )
            if any(a.upper() != "02:00:00:00:00:01" for a in addresses):
                raise SystemExit(f"Non-fictional MAC in {path.relative_to(ROOT)}")
            private_ip = re.search(
                r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\d.])",
                text,
            )
            if private_ip:
                raise SystemExit(f"Private IPv4 address in {path.relative_to(ROOT)}")
    manifest = json.loads((ROOT / "custom_components/jomoo_ble/manifest.json").read_text())
    if manifest["domain"] != "jomoo_ble" or not manifest["config_flow"]:
        raise SystemExit("Invalid component metadata")
    print(f"py_compile: {len(python)} Python files OK")
    print(f"Metadata, local links and basic public hygiene: {len(files)} files OK")


if __name__ == "__main__":
    main()
