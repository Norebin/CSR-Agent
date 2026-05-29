from __future__ import annotations

from csr_agent.tools.default_adapters import _stdout_contains_smell


def test_target_smell_detection_uses_target_file_only():
    stdout = "\n".join(
        [
            "src/A.java:1: ExcessiveMethodLength",
            "src/B.java:2: CyclomaticComplexity",
        ]
    )
    assert _stdout_contains_smell(stdout, "LongMethod", file_path="src/A.java") is True
    assert _stdout_contains_smell(stdout, "LongMethod", file_path="src/B.java") is False


def test_target_smell_detection_ignores_other_smells():
    stdout = "src/A.java:2: CyclomaticComplexity"
    assert _stdout_contains_smell(stdout, "LongMethod", file_path="src/A.java") is False
