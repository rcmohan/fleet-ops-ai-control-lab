"""Format service Operation definitions as multiline keyword calls."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSITIONAL_NAMES = (
    "method",
    "path",
    "operation_id",
    "summary",
    "response",
    "request",
    "parameters",
)


def _offset(line_starts: list[int], line: int, column: int) -> int:
    return line_starts[line - 1] + column


def _format_call(source: str, node: ast.Call) -> str:
    arguments: list[tuple[str, ast.expr]] = []
    for index, value in enumerate(node.args):
        if index >= len(POSITIONAL_NAMES):
            raise ValueError("Operation call has more positional arguments than expected")
        arguments.append((POSITIONAL_NAMES[index], value))
    for keyword in node.keywords:
        if keyword.arg is None:
            raise ValueError("Operation calls cannot use **kwargs")
        arguments.append((keyword.arg, keyword.value))

    indent = " " * node.col_offset
    continuation = indent + " " * 4
    lines = ["Operation("]
    for name, value in arguments:
        rendered = ast.get_source_segment(source, value)
        if rendered is None:
            rendered = ast.unparse(value)
        rendered_lines = rendered.strip().splitlines()
        lines.append(f"{continuation}{name}={rendered_lines[0]}")
        lines.extend(f"{continuation}{line}" for line in rendered_lines[1:])
        lines[-1] += ","
    lines.append(f"{indent})")
    return "\n".join(lines)


def format_file(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    line_starts: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(line)

    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Operation":
            continue
        if node.end_lineno is None or node.end_col_offset is None:
            raise ValueError(f"Missing source location for Operation in {path}")
        start = _offset(line_starts, node.lineno, node.col_offset)
        end = _offset(line_starts, node.end_lineno, node.end_col_offset)
        replacements.append((start, end, _format_call(source, node)))

    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    path.write_text(source, encoding="utf-8")
    return len(replacements)


def main() -> None:
    total = 0
    paths = sorted((ROOT / "services").glob("*/contract.py"))
    for path in paths:
        count = format_file(path)
        total += count
        print(f"formatted {count:2d} calls in {path.relative_to(ROOT)}")
    subprocess.run(
        [sys.executable, "-m", "black", *(str(path) for path in paths)],
        cwd=ROOT,
        check=True,
    )
    print(f"formatted {total} Operation calls")


if __name__ == "__main__":
    main()
