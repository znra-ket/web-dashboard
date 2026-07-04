import ast
import re
from pathlib import Path

import backend.app.architecture as architecture
from backend.app.architecture import constants


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INVARIANTS = PROJECT_ROOT / "implementation" / "INVARIANTS.md"


def _text_block(heading: str) -> list[str]:
    text = INVARIANTS.read_text(encoding="utf-8")
    pattern = rf"### {re.escape(heading)}\n```text\n(.*?)\n```"
    match = re.search(pattern, text, flags=re.DOTALL)
    assert match is not None, f"Missing machine-readable block: {heading}"
    return [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _key_value_block(heading: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _text_block(heading):
        key, raw_value = line.split("=", 1)
        values[key] = int(raw_value)
    return values


def test_node_lifecycle_states_match_invariants() -> None:
    assert constants.NODE_LIFECYCLE_STATES_V1 == tuple(
        _text_block("Node Lifecycle States v1")
    )


def test_agent_limits_match_invariants() -> None:
    assert constants.AGENT_LIMITS_V1.as_mapping() == _key_value_block("Agent Limits v1")


def test_trigger_types_match_invariants() -> None:
    assert constants.TRIGGER_TYPES_V1 == tuple(_text_block("Trigger Types v1"))


def test_bootstrap_token_windows_match_invariants() -> None:
    source_values = _key_value_block("Bootstrap Token v1")

    assert constants.BOOTSTRAP_TOKEN_BYTES == source_values["bootstrap_token_bytes"]
    assert (
        constants.BOOTSTRAP_TOKEN_TTL_SECONDS
        == source_values["bootstrap_token_ttl_seconds"]
    )
    assert (
        constants.BOOTSTRAP_ABSOLUTE_WINDOW_SECONDS
        == source_values["bootstrap_absolute_window_seconds"]
    )


def test_pipeline_limit_matches_invariants() -> None:
    assert constants.MAX_PIPELINE_STEPS == _key_value_block("Pipeline Limits v1")[
        "max_pipeline_steps"
    ]


def test_agent_features_match_invariants() -> None:
    assert constants.AGENT_FEATURES_V1 == tuple(_text_block("Agent Features v1"))


def test_architecture_package_reexports_single_manifest_source() -> None:
    assert architecture.NODE_LIFECYCLE_STATES_V1 is constants.NODE_LIFECYCLE_STATES_V1
    assert architecture.AGENT_LIMITS_V1 is constants.AGENT_LIMITS_V1
    assert architecture.TRIGGER_TYPES_V1 is constants.TRIGGER_TYPES_V1
    assert architecture.AGENT_FEATURES_V1 is constants.AGENT_FEATURES_V1


def test_runtime_modules_do_not_duplicate_manifest_constants() -> None:
    forbidden_literals = {
        repr(value)
        for value in (
            *constants.NODE_LIFECYCLE_STATES_V1,
            *constants.TRIGGER_TYPES_V1,
            *constants.AGENT_FEATURES_V1,
        )
    }
    forbidden_literals |= {
        str(value)
        for value in (
            constants.MAX_PIPELINE_STEPS,
            constants.BOOTSTRAP_TOKEN_TTL_SECONDS,
            constants.BOOTSTRAP_ABSOLUTE_WINDOW_SECONDS,
            constants.AGENT_LIMITS_V1.max_script_upload_bytes,
            constants.AGENT_LIMITS_V1.max_execute_body_bytes,
            constants.AGENT_LIMITS_V1.max_stdout_bytes,
            constants.AGENT_LIMITS_V1.max_stderr_bytes,
            constants.AGENT_LIMITS_V1.max_memory_bytes_per_run,
        )
    }

    scanned_files = [
        *PROJECT_ROOT.joinpath("backend", "app").rglob("*.py"),
        *PROJECT_ROOT.joinpath("agent", "webxray_agent").rglob("*.py"),
    ]
    for path in scanned_files:
        if path.name == "constants.py" or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals = {
            repr(node.value) if isinstance(node.value, str) else str(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
        }
        duplicates = literals & forbidden_literals
        assert not duplicates, f"{path} duplicates architecture manifest values: {duplicates}"
