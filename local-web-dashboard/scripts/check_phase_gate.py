#!/usr/bin/env python3
"""Validate web-xray-dashboard phase gates from implementation markdown files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ALLOWED_STATUSES = {
    "planned",
    "implemented",
    "tested",
    "blocked",
    "deferred_after_mvp",
}
FORBIDDEN_ALIASES = {
    "partial",
    "untested",
    "xfail",
    "todo",
    "later",
    "covered_by_docs",
}
REQUIRED_TRACE_COLUMNS = [
    "requirement_id",
    "source_doc",
    "requirement",
    "criticality",
    "prompt_id",
    "phase_gate",
    "implementation_files_expected",
    "test_files_expected",
    "implementation_files_actual",
    "test_files_actual",
    "status",
    "evidence",
]
REQUIRED_COVERAGE_COLUMNS = [
    "requirement_id",
    "prompt_id",
    "test_id/test_file",
    "phase gate",
    "current status",
]

PHASES: dict[str, list[str]] = {
    "phase_0": [],
    "phase_1": [
        "foundation",
        "foundation_schema",
        "schema_triggers",
        "transaction_boundaries",
    ],
    "phase_2": [
        "agent_foundation",
        "agent_storage",
        "agent_api",
        "executor",
    ],
    "phase_3": [
        "onboarding_security",
        "lifecycle",
        "mtls_runtime",
    ],
    "phase_4": [
        "onboarding",
    ],
    "phase_5": [
        "folder_service",
        "triggers",
        "scheduler",
        "pipeline",
        "reconciliation",
    ],
    "phase_6": [
        "background_workers",
        "api_contracts",
    ],
    "phase_7": [
        "release_readiness",
    ],
}

SECURITY_LIFECYCLE_FOUNDATION_GATES = {
    "foundation",
    "foundation_schema",
    "schema_triggers",
    "transaction_boundaries",
    "agent_foundation",
    "agent_storage",
    "agent_api",
    "executor",
    "onboarding_security",
    "lifecycle",
    "mtls_runtime",
    "onboarding",
    "reconciliation",
}


def parse_markdown_table(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header: list[str] | None = None
    rows: list[dict[str, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not header:
            header = cells
            continue
        if len(cells) != len(header):
            raise ValueError(
                f"{path}: table row has {len(cells)} cells but header has "
                f"{len(header)}: {stripped}"
            )
        rows.append(dict(zip(header, cells)))

    if not header:
        raise ValueError(f"{path}: no markdown table found")
    return rows


def table_header(path: Path) -> list[str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and "---" not in stripped:
            return [cell.strip() for cell in stripped.strip("|").split("|")]
    raise ValueError(f"{path}: no markdown table header found")


def normalize_header(header: list[str]) -> list[str]:
    return [re.sub(r":.*$", "", item).strip() for item in header]


def phase_rank_map() -> dict[str, int]:
    ranks: dict[str, int] = {}
    for index, phase in enumerate(PHASES):
        ranks[phase] = index
        for gate in PHASES[phase]:
            ranks[gate] = index
    return ranks


def is_blank(value: str) -> bool:
    clean = value.strip().strip("`")
    return clean == ""


def validate(args: argparse.Namespace) -> tuple[bool, list[str]]:
    root = Path(__file__).resolve().parents[1]
    implementation_dir = root / "implementation"
    trace_path = implementation_dir / "TRACEABILITY.md"
    coverage_path = implementation_dir / "PROMPT_COVERAGE.md"
    blocking_path = implementation_dir / "BLOCKING_REQUIREMENTS.md"
    conflicts_path = implementation_dir / "CONFLICTS.md"
    phase_gates_path = implementation_dir / "PHASE_GATES.md"

    errors: list[str] = []
    for path in [
        trace_path,
        coverage_path,
        blocking_path,
        conflicts_path,
        phase_gates_path,
    ]:
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(root)}")
    if errors:
        return False, errors

    ranks = phase_rank_map()
    current_rank = ranks[args.phase]
    due_gates = {gate for gate, rank in ranks.items() if rank <= current_rank}

    try:
        trace_header = normalize_header(table_header(trace_path))
        coverage_header = table_header(coverage_path)
        trace_rows = parse_markdown_table(trace_path)
        coverage_rows = parse_markdown_table(coverage_path)
        blocking_rows = parse_markdown_table(blocking_path)
    except ValueError as exc:
        return False, [str(exc)]

    for required in REQUIRED_TRACE_COLUMNS:
        if required not in trace_header:
            errors.append(f"TRACEABILITY.md missing required column: {required}")
    for required in REQUIRED_COVERAGE_COLUMNS:
        if required not in coverage_header:
            errors.append(f"PROMPT_COVERAGE.md missing required column: {required}")
    if errors:
        return False, errors

    coverage_by_id = {row["requirement_id"]: row for row in coverage_rows}
    blocking_ids = {row["requirement_id"] for row in blocking_rows}

    for row in trace_rows:
        req_id = row["requirement_id"]
        status = row["status"].strip()
        criticality = row["criticality"].strip()
        phase_gate = row["phase_gate"].strip()

        if status not in ALLOWED_STATUSES:
            errors.append(f"{req_id}: invalid status {status!r}")
        if status in FORBIDDEN_ALIASES:
            errors.append(f"{req_id}: forbidden status alias {status!r}")
        if phase_gate not in ranks:
            errors.append(f"{req_id}: unknown phase_gate {phase_gate!r}")
            continue
        if req_id not in coverage_by_id:
            errors.append(f"{req_id}: missing PROMPT_COVERAGE row")
            continue

        coverage = coverage_by_id[req_id]
        if coverage["prompt_id"] != row["prompt_id"]:
            errors.append(
                f"{req_id}: prompt mismatch TRACEABILITY={row['prompt_id']!r} "
                f"COVERAGE={coverage['prompt_id']!r}"
            )
        if coverage["phase gate"] != phase_gate:
            errors.append(
                f"{req_id}: phase gate mismatch TRACEABILITY={phase_gate!r} "
                f"COVERAGE={coverage['phase gate']!r}"
            )
        if coverage["current status"] != status:
            errors.append(
                f"{req_id}: status mismatch TRACEABILITY={status!r} "
                f"COVERAGE={coverage['current status']!r}"
            )

        future = phase_gate not in due_gates
        if criticality == "blocking":
            for field in ["prompt_id", "phase_gate", "test_files_expected"]:
                if is_blank(row[field]):
                    errors.append(f"{req_id}: blocking requirement missing {field}")
            if is_blank(coverage["test_id/test_file"]):
                errors.append(f"{req_id}: blocking requirement missing coverage test")
            if future:
                continue

        if not future and criticality != "after_mvp" and status != "tested":
            errors.append(
                f"{req_id}: phase_gate {phase_gate!r} is due for {args.phase}, "
                f"but status is {status!r}, expected 'tested'"
            )

        if (
            not future
            and criticality == "blocking"
            and phase_gate in SECURITY_LIFECYCLE_FOUNDATION_GATES
            and status in {"deferred_after_mvp", *FORBIDDEN_ALIASES}
        ):
            errors.append(
                f"{req_id}: security/lifecycle/foundation blocking requirement "
                f"cannot use status {status!r} after phase gate is reached"
            )

    trace_ids = {row["requirement_id"] for row in trace_rows}
    for req_id in coverage_by_id:
        if req_id not in trace_ids:
            errors.append(f"{req_id}: coverage row has no TRACEABILITY row")

    for row in blocking_rows:
        req_id = row["requirement_id"]
        if req_id not in trace_ids:
            errors.append(f"{req_id}: blocking row has no TRACEABILITY row")

    return not errors, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check web-xray phase gate.")
    parser.add_argument(
        "--phase",
        required=True,
        choices=list(PHASES),
        help="Current phase gate, for example phase_0 or phase_1.",
    )
    args = parser.parse_args()

    ok, errors = validate(args)
    if ok:
        print(f"GO: {args.phase}")
        return 0

    print(f"NO-GO: {args.phase}")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
