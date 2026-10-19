"""Verify that timing-qualified FPGA sources changed only in comments."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fpga" / "golden_manifest.json"


def strip_verilog_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    state = "code"
    while i < len(text):
        pair = text[i : i + 2]
        ch = text[i]
        if state == "code":
            if pair == "//":
                state = "line"
                i += 2
                continue
            if pair == "/*":
                state = "block"
                i += 2
                continue
            out.append(ch)
            if ch == '"':
                state = "string"
        elif state == "string":
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                i += 1
                out.append(text[i])
            elif ch == '"':
                state = "code"
        elif state == "line":
            if ch in "\r\n":
                out.append(ch)
                state = "code"
        elif state == "block" and pair == "*/":
            state = "code"
            i += 2
            continue
        i += 1
    if state == "block":
        raise ValueError("unterminated block comment")
    return "".join(out)


def functional_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if path.suffix.lower() == ".xdc":
        text = "\n".join(line for line in text.splitlines() if not re.match(r"^\s*#", line))
    else:
        text = strip_verilog_comments(text)
    return re.sub(r"\s+", "", text).encode("utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(functional_bytes(path)).hexdigest()


def main() -> int:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    actual_paths = sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "fpga").iterdir()
        if p.suffix.lower() in {".v", ".sv", ".vh", ".xdc"}
    )
    failures: list[str] = []
    if actual_paths != sorted(expected):
        failures.append("golden source set differs")
        failures.extend(f"  unexpected: {p}" for p in sorted(set(actual_paths) - set(expected)))
        failures.extend(f"  missing: {p}" for p in sorted(set(expected) - set(actual_paths)))
    for name in sorted(set(actual_paths) & set(expected)):
        got = digest(ROOT / name)
        if got != expected[name]:
            failures.append(f"functional HDL/XDC changed: {name}")
    if failures:
        print("GOLDEN SOURCE CHECK: FAIL")
        print("\n".join(failures))
        print("Only comment edits are permitted in the timing-qualified FPGA sources.")
        return 1
    print(f"GOLDEN SOURCE CHECK: PASS ({len(expected)} files; comments ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
