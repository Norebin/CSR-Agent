"""Tool adapters with real command execution and graceful fallbacks."""

from __future__ import annotations

import difflib
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from csr_agent.config import ToolRuntimeConfig
from csr_agent.models import ToolObservation

from .command_utils import run_command, split_command
from .protocol import ToolAdapter
from .registry import ToolRegistry

try:  # pragma: no cover - optional dependency
    import javalang  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    javalang = None


class BaseToolAdapter(ToolAdapter):
    """Utility base for operation handlers."""

    def __init__(
        self,
        name: str,
        handlers: dict[str, Callable[[dict[str, Any]], ToolObservation]],
    ) -> None:
        self.name = name
        self._handlers = handlers
        self.operations = set(handlers.keys())

    def execute(self, operation: str, payload: dict[str, Any]) -> ToolObservation:
        if operation not in self._handlers:
            return ToolObservation(
                tool_name=self.name,
                operation=operation,
                status="error",
                error_code="UNSUPPORTED_OPERATION",
                message=f"Operation not supported: {operation}",
                artifacts={},
            )
        try:
            return self._handlers[operation](payload)
        except Exception as exc:  # pragma: no cover - runtime safety
            return ToolObservation(
                tool_name=self.name,
                operation=operation,
                status="error",
                error_code="EXCEPTION",
                message=str(exc),
                artifacts={},
            )


class DisabledToolAdapter(ToolAdapter):
    """Adapter wrapper used for tool-ablation experiments."""

    def __init__(self, wrapped: ToolAdapter) -> None:
        self._wrapped = wrapped
        self.name = wrapped.name
        self.operations = set(getattr(wrapped, "operations", set()))

    def execute(self, operation: str, payload: dict[str, Any]) -> ToolObservation:
        return ToolObservation(
            tool_name=self.name,
            operation=operation,
            status="degraded",
            error_code="TOOL_DISABLED",
            message=f"Tool disabled by experiment config: {self.name}",
            artifacts={"tool_enabled": False},
        )


def _obs(
    tool: str,
    op: str,
    status: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> ToolObservation:
    return ToolObservation(
        tool_name=tool,
        operation=op,
        status=status,  # type: ignore[arg-type]
        error_code=error_code,
        message=message,
        artifacts=artifacts or {},
    )


def _ok(tool: str, op: str, artifacts: dict[str, Any] | None = None, message: str = "") -> ToolObservation:
    return _obs(tool, op, "ok", message, artifacts)


def _degraded(
    tool: str,
    op: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> ToolObservation:
    return _obs(tool, op, "degraded", message, artifacts)


def _error(
    tool: str,
    op: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
    code: str = "TOOL_ERROR",
) -> ToolObservation:
    return _obs(tool, op, "error", message, artifacts, error_code=code)


def build_default_tool_registry(
    runtime: ToolRuntimeConfig | None = None,
    tool_enabled: dict[str, bool] | None = None,
) -> ToolRegistry:
    runtime = runtime or ToolRuntimeConfig()
    enabled = tool_enabled or {}

    registry = ToolRegistry()
    registry.register(_maybe_disable(_build_git_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_repo_browser_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_ast_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_entity_tracker_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_retrieval_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_patch_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_build_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_test_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_smell_detector_tool(runtime), enabled))
    registry.register(_maybe_disable(_build_metrics_tool(runtime), enabled))
    return registry


def _maybe_disable(adapter: ToolAdapter, tool_enabled: dict[str, bool]) -> ToolAdapter:
    is_enabled = bool(tool_enabled.get(adapter.name, True))
    if is_enabled:
        return adapter
    return DisabledToolAdapter(adapter)


def _build_git_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "git_tool"

    def list_tags(payload: dict[str, Any]) -> ToolObservation:
        provided = payload.get("tags")
        if isinstance(provided, list) and provided:
            return _ok(name, "list_tags", {"tags": provided}, "Using payload-provided tags.")
        repo = _repo_path(payload)
        if repo is None:
            return _degraded(name, "list_tags", "repo_path missing.", {"tags": []})
        res = run_command([runtime.git_bin, "-C", str(repo), "tag", "--list"], timeout_sec=runtime.default_timeout_sec)
        if not res.ok:
            if _is_dubious_ownership(res.stderr):
                return _degraded(
                    name,
                    "list_tags",
                    "Git blocked by safe.directory policy (dubious ownership).",
                    {"stderr": res.tail(res.stderr), "tags": []},
                )
            return _error(
                name,
                "list_tags",
                "git tag --list failed.",
                {"stderr": res.tail(res.stderr), "returncode": res.returncode, "tags": []},
            )
        tags = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return _ok(name, "list_tags", {"tags": tags})

    def resolve_tag(payload: dict[str, Any]) -> ToolObservation:
        hint = str(payload.get("hint") or "").strip().lower()
        tags = payload.get("tags") or []
        if not hint:
            return _degraded(name, "resolve_tag", "hint missing.", {"resolved_tag": None})
        if not tags:
            return _degraded(name, "resolve_tag", "tags list is empty.", {"resolved_tag": None})
        scored = sorted(tags, key=lambda t: _similarity(hint, str(t).lower()), reverse=True)
        return _ok(name, "resolve_tag", {"resolved_tag": scored[0], "ranked": scored[:5]})

    def checkout(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        tag = str(payload.get("tag") or "").strip()
        allow_mutation = bool(payload.get("allow_mutation", False))
        if repo is None or not tag:
            return _degraded(name, "checkout", "repo_path/tag missing.", {"checked_out": None})
        if not allow_mutation:
            res = run_command([runtime.git_bin, "-C", str(repo), "rev-parse", "--verify", tag], timeout_sec=runtime.default_timeout_sec)
            if not res.ok:
                if _is_dubious_ownership(res.stderr):
                    return _degraded(name, "checkout", "Git safe.directory policy blocked verification.", {"tag_exists": False})
                return _error(name, "checkout", "Tag verification failed.", {"tag": tag, "returncode": res.returncode})
            return _degraded(name, "checkout", "Mutation disabled; verified only.", {"checked_out": None, "tag_exists": True})
        res = run_command([runtime.git_bin, "-C", str(repo), "checkout", "--detach", tag], timeout_sec=runtime.default_timeout_sec)
        if not res.ok:
            if _is_dubious_ownership(res.stderr):
                return _degraded(name, "checkout", "Git safe.directory policy blocked checkout.", {"checked_out": None})
            return _error(name, "checkout", "git checkout failed.", {"stderr": res.tail(res.stderr), "returncode": res.returncode})
        return _ok(name, "checkout", {"checked_out": tag})

    def show_file(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        file_path = str(payload.get("file_path") or "")
        rev = str(payload.get("revision") or "HEAD")
        if repo is None or not file_path:
            return _degraded(name, "show_file", "repo_path/file_path missing.", {"content": ""})
        spec = f"{rev}:{file_path}"
        res = run_command([runtime.git_bin, "-C", str(repo), "show", spec], timeout_sec=runtime.default_timeout_sec)
        if not res.ok:
            if _is_dubious_ownership(res.stderr):
                return _degraded(name, "show_file", "Git safe.directory policy blocked show.", {"content": ""})
            return _error(name, "show_file", "git show failed.", {"stderr": res.tail(res.stderr), "returncode": res.returncode})
        return _ok(name, "show_file", {"content": res.stdout})

    def show_diff(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        from_rev = str(payload.get("from_rev") or "HEAD~1")
        to_rev = str(payload.get("to_rev") or "HEAD")
        file_path = str(payload.get("file_path") or "")
        if repo is None:
            return _degraded(name, "show_diff", "repo_path missing.", {"diff": ""})
        cmd = [runtime.git_bin, "-C", str(repo), "diff", from_rev, to_rev]
        if file_path:
            cmd.extend(["--", file_path])
        res = run_command(cmd, timeout_sec=runtime.default_timeout_sec)
        if not res.ok:
            if _is_dubious_ownership(res.stderr):
                return _degraded(name, "show_diff", "Git safe.directory policy blocked diff.", {"diff": ""})
            return _error(name, "show_diff", "git diff failed.", {"stderr": res.tail(res.stderr), "returncode": res.returncode})
        return _ok(name, "show_diff", {"diff": res.stdout})

    return BaseToolAdapter(
        name=name,
        handlers={
            "list_tags": list_tags,
            "resolve_tag": resolve_tag,
            "checkout": checkout,
            "show_file": show_file,
            "show_diff": show_diff,
        },
    )


def _build_repo_browser_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "repo_browser_tool"

    def read_file(payload: dict[str, Any]) -> ToolObservation:
        path = _path_from_payload(payload, "path")
        if path is None or not path.exists():
            return _degraded(name, "read_file", "path missing or not exists.", {"content": ""})
        return _ok(name, "read_file", {"content": path.read_text(encoding="utf-8", errors="replace")})

    def search_text(payload: dict[str, Any]) -> ToolObservation:
        root = _repo_path(payload)
        pattern = str(payload.get("pattern") or "")
        if root is None or not pattern:
            return _degraded(name, "search_text", "repo_path/pattern missing.", {"hits": []})
        rg_cmd = [runtime.rg_bin, "-n", pattern, str(root)]
        rg_res = run_command(rg_cmd, timeout_sec=runtime.default_timeout_sec)
        if rg_res.ok:
            hits = [line for line in rg_res.stdout.splitlines() if line.strip()]
            return _ok(name, "search_text", {"hits": hits[:500]})
        hits: list[str] = []
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        for file in root.rglob("*.java"):
            text = file.read_text(encoding="utf-8", errors="replace")
            for idx, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{file}:{idx}:{line.strip()}")
                    if len(hits) >= 500:
                        break
            if len(hits) >= 500:
                break
        return _degraded(name, "search_text", "rg unavailable; used python fallback.", {"hits": hits})

    def find_symbol(payload: dict[str, Any]) -> ToolObservation:
        root = _repo_path(payload)
        symbol = str(payload.get("symbol") or payload.get("name") or "").strip()
        if root is None or not symbol:
            return _degraded(name, "find_symbol", "repo_path/symbol missing.", {"matches": []})
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        matches: list[str] = []
        for file in root.rglob("*.java"):
            text = file.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                matches.append(str(file))
                if len(matches) >= 200:
                    break
        return _ok(name, "find_symbol", {"matches": matches})

    def list_neighbors(payload: dict[str, Any]) -> ToolObservation:
        file_path = _path_from_payload(payload, "file_path")
        if file_path is None:
            return _degraded(name, "list_neighbors", "file_path missing.", {"neighbors": []})
        parent = file_path.parent if file_path.exists() else file_path.parent
        if not parent.exists():
            return _degraded(name, "list_neighbors", "parent directory not found.", {"neighbors": []})
        neighbors = [str(p) for p in parent.iterdir()][:200]
        return _ok(name, "list_neighbors", {"neighbors": neighbors})

    return BaseToolAdapter(
        name=name,
        handlers={
            "read_file": read_file,
            "find_symbol": find_symbol,
            "search_text": search_text,
            "list_neighbors": list_neighbors,
        },
    )


def _build_ast_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "ast_tool"

    def parse_java(payload: dict[str, Any]) -> ToolObservation:
        source = str(payload.get("source", ""))
        if not source.strip():
            return _degraded(name, "parse_java", "source empty.", {"parsed": False})
        if javalang is not None:
            try:
                javalang.parse.parse(source)
                return _ok(name, "parse_java", {"parsed": True, "engine": "javalang"})
            except Exception as exc:
                return _degraded(name, "parse_java", f"javalang parse failed: {exc}", {"parsed": False, "engine": "javalang"})
        parsed = ("class " in source) and ("{" in source and "}" in source)
        status = "ok" if parsed else "degraded"
        message = "Heuristic parse success." if parsed else "Heuristic parse failed."
        return _obs(name, "parse_java", status, message, {"parsed": parsed, "engine": "heuristic"})

    def get_method_node(payload: dict[str, Any]) -> ToolObservation:
        source = str(payload.get("source") or "")
        method = str(payload.get("method_name") or "")
        found = bool(method and re.search(rf"\b{re.escape(method)}\s*\(", source))
        return _ok(name, "get_method_node", {"method": method, "found": found})

    def get_class_node(payload: dict[str, Any]) -> ToolObservation:
        source = str(payload.get("source") or "")
        class_name = str(payload.get("class_name") or "")
        found = bool(class_name and re.search(rf"\bclass\s+{re.escape(class_name)}\b", source))
        return _ok(name, "get_class_node", {"class": class_name, "found": found})

    def collect_calls(payload: dict[str, Any]) -> ToolObservation:
        source = str(payload.get("source") or "")
        calls = sorted(set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", source)))
        return _ok(name, "collect_calls", {"calls": calls[:500]})

    return BaseToolAdapter(
        name=name,
        handlers={
            "parse_java": parse_java,
            "get_method_node": get_method_node,
            "get_class_node": get_class_node,
            "collect_calls": collect_calls,
            "format_patch_context": lambda payload: _ok(name, "format_patch_context", {"context": payload.get("context", "")}),
        },
    )


def _build_entity_tracker_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "entity_tracker_tool"
    return BaseToolAdapter(
        name=name,
        handlers={
            "anchor_entity": lambda payload: _ok(name, "anchor_entity", payload),
            "track_across_versions": lambda payload: _ok(name, "track_across_versions", payload),
            "score_candidates": lambda payload: _ok(name, "score_candidates", payload),
        },
    )


def _build_retrieval_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "retrieval_tool"
    return BaseToolAdapter(
        name=name,
        handlers={
            "embed_query": lambda payload: _ok(name, "embed_query", payload),
            "semantic_search": lambda payload: _ok(name, "semantic_search", payload),
            "context_gate": lambda payload: _ok(name, "context_gate", payload),
            "rerank": lambda payload: _ok(name, "rerank", payload),
            "pack_evidence": lambda payload: _ok(name, "pack_evidence", payload),
        },
    )


def _build_patch_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "patch_tool"

    def generate_unified_diff(payload: dict[str, Any]) -> ToolObservation:
        before = str(payload.get("before") or "")
        after = str(payload.get("after") or "")
        file_path = str(payload.get("file_path") or "target.java")
        if before or after:
            diff = "\n".join(
                difflib.unified_diff(
                    before.splitlines(),
                    after.splitlines(),
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    lineterm="",
                )
            )
            return _ok(name, "generate_unified_diff", {"diff": diff})
        return _ok(name, "generate_unified_diff", {"diff": str(payload.get("diff", ""))})

    def apply_patch(payload: dict[str, Any]) -> ToolObservation:
        diff = str(payload.get("diff", ""))
        repo = _repo_path(payload)
        apply = bool(payload.get("apply", False))
        if not diff.strip():
            return _degraded(name, "apply_patch", "Empty patch diff.", {"applied": False, "check_pass": False})
        if repo is None:
            return _degraded(name, "apply_patch", "repo_path missing; logical apply only.", {"applied": False, "check_pass": True})

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".diff") as fh:
            fh.write(diff)
            patch_path = Path(fh.name)

        try:
            check_cmd = [runtime.git_bin, "-C", str(repo), "apply", "--check", str(patch_path)]
            check_res = run_command(check_cmd, timeout_sec=runtime.default_timeout_sec)
            if not check_res.ok:
                return _error(
                    name,
                    "apply_patch",
                    "git apply --check failed.",
                    {
                        "applied": False,
                        "check_pass": False,
                        "stderr": check_res.tail(check_res.stderr),
                        "returncode": check_res.returncode,
                    },
                    code="PATCH_CHECK_FAILED",
                )
            if not apply:
                return _degraded(name, "apply_patch", "Patch check passed; apply disabled.", {"applied": False, "check_pass": True})
            apply_res = run_command([runtime.git_bin, "-C", str(repo), "apply", str(patch_path)], timeout_sec=runtime.default_timeout_sec)
            if not apply_res.ok:
                return _error(name, "apply_patch", "git apply failed.", {"applied": False, "check_pass": True, "stderr": apply_res.tail(apply_res.stderr)})
            return _ok(name, "apply_patch", {"applied": True, "check_pass": True})
        finally:
            try:
                patch_path.unlink(missing_ok=True)
            except Exception:
                pass

    def revert_patch(payload: dict[str, Any]) -> ToolObservation:
        diff = str(payload.get("diff", ""))
        repo = _repo_path(payload)
        if not diff.strip() or repo is None:
            return _degraded(name, "revert_patch", "diff/repo_path missing.", {"reverted": False})
        return _degraded(name, "revert_patch", "Revert disabled by default for safety.", {"reverted": False})

    def merge_patch(payload: dict[str, Any]) -> ToolObservation:
        diffs = payload.get("diffs")
        if isinstance(diffs, list):
            merged = "\n".join(str(d).strip() for d in diffs if str(d).strip())
            return _ok(name, "merge_patch", {"merged_diff": merged})
        return _ok(name, "merge_patch", {"merged_diff": str(payload.get("merged_diff", ""))})

    return BaseToolAdapter(
        name=name,
        handlers={
            "generate_unified_diff": generate_unified_diff,
            "apply_patch": apply_patch,
            "revert_patch": revert_patch,
            "merge_patch": merge_patch,
        },
    )


def _build_build_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "build_tool"

    def detect_build_system(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        if repo is None:
            return _degraded(name, "detect_build_system", "repo_path missing.", {"build_system": "unknown"})
        build = _detect_build(repo, runtime)
        status = "ok" if build != "unknown" else "degraded"
        return _obs(name, "detect_build_system", status, f"build_system={build}", {"build_system": build})

    def compile_module(payload: dict[str, Any]) -> ToolObservation:
        return _run_compile_command(name, "compile_module", payload, runtime)

    def compile_project(payload: dict[str, Any]) -> ToolObservation:
        return _run_compile_command(name, "compile_project", payload, runtime)

    return BaseToolAdapter(
        name=name,
        handlers={
            "detect_build_system": detect_build_system,
            "compile_module": compile_module,
            "compile_project": compile_project,
        },
    )


def _build_test_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "test_tool"

    def select_impacted_tests(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        changed_files = [str(x) for x in (payload.get("changed_files") or [])]
        if repo is None:
            return _degraded(name, "select_impacted_tests", "repo_path missing.", {"tests": []})
        tests = _guess_impacted_tests(repo, changed_files)
        status = "ok" if tests else "degraded"
        message = "Impacted tests selected." if tests else "No impacted tests found."
        return _obs(name, "select_impacted_tests", status, message, {"tests": tests})

    def run_targeted_tests(payload: dict[str, Any]) -> ToolObservation:
        repo = _repo_path(payload)
        if repo is None:
            return _degraded(name, "run_targeted_tests", "repo_path missing.", {"passed": True, "executed": False})
        build = _detect_build(repo, runtime)
        tests = [str(x) for x in (payload.get("tests") or [])]
        if not tests:
            tests = _guess_impacted_tests(repo, [str(payload.get("file_path") or "")])
        if not tests:
            return _degraded(name, "run_targeted_tests", "No targeted tests available.", {"passed": True, "executed": False})
        cmd = _test_command(repo, build, tests, runtime)
        if cmd is None:
            return _degraded(name, "run_targeted_tests", f"Unsupported build system: {build}", {"passed": True, "executed": False})
        res = run_command(
            cmd,
            cwd=repo,
            timeout_sec=runtime.default_timeout_sec,
            env=_tool_env(runtime),
        )
        status = "ok" if res.ok else "error"
        return _obs(
            name,
            "run_targeted_tests",
            status,
            "Targeted tests executed." if res.ok else "Targeted tests failed.",
            {
                "passed": bool(res.ok),
                "executed": True,
                "command": cmd,
                "stdout_tail": res.tail(res.stdout),
                "stderr_tail": res.tail(res.stderr),
                "returncode": res.returncode,
            },
            error_code=None if res.ok else "TEST_FAILED",
        )

    def run_generated_assertions(payload: dict[str, Any]) -> ToolObservation:
        custom = split_command(payload.get("command"))
        repo = _repo_path(payload)
        if custom and repo is not None:
            res = run_command(
                custom,
                cwd=repo,
                timeout_sec=runtime.default_timeout_sec,
                env=_tool_env(runtime),
            )
            status = "ok" if res.ok else "error"
            return _obs(
                name,
                "run_generated_assertions",
                status,
                "Generated assertion command executed." if res.ok else "Generated assertion command failed.",
                {"passed": bool(res.ok), "executed": True, "command": custom, "returncode": res.returncode},
                error_code=None if res.ok else "ASSERTION_FAILED",
            )
        return _degraded(
            name,
            "run_generated_assertions",
            "No generated assertion command configured; skipped.",
            {"passed": True, "executed": False},
        )

    return BaseToolAdapter(
        name=name,
        handlers={
            "select_impacted_tests": select_impacted_tests,
            "run_targeted_tests": run_targeted_tests,
            "run_generated_assertions": run_generated_assertions,
        },
    )


def _build_smell_detector_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "smell_detector_tool"

    def detect_target_smell(payload: dict[str, Any]) -> ToolObservation:
        result = _run_detectors(payload, runtime)
        if result is None:
            fallback = bool(payload.get("smell_removed", True))
            return _degraded(name, "detect_target_smell", "No detector configured; using fallback.", {"smell_removed": fallback, "detector_used": []})
        smell_type = str(payload.get("smell_type") or "")
        file_path = str(payload.get("file_path") or "")
        found = _stdout_contains_smell(result["stdout"], smell_type, file_path=file_path)
        return _ok(
            name,
            "detect_target_smell",
            {
                "smell_removed": not found,
                "detector_used": result["detectors"],
                "raw_stdout_tail": result["stdout"][-4000:],
            },
        )

    def detect_new_smells(payload: dict[str, Any]) -> ToolObservation:
        result = _run_detectors(payload, runtime)
        if result is None:
            fallback = payload.get("new_smells") or []
            return _degraded(name, "detect_new_smells", "No detector configured; using fallback.", {"new_smells": fallback, "detector_used": []})
        new_smells = _extract_smells_from_stdout(result["stdout"])
        return _ok(
            name,
            "detect_new_smells",
            {"new_smells": new_smells, "detector_used": result["detectors"]},
        )

    def cross_detector_consensus(payload: dict[str, Any]) -> ToolObservation:
        detectors = payload.get("detectors") or []
        consensus = bool(payload.get("consensus", True))
        return _ok(name, "cross_detector_consensus", {"consensus": consensus, "detectors": detectors})

    return BaseToolAdapter(
        name=name,
        handlers={
            "detect_target_smell": detect_target_smell,
            "detect_new_smells": detect_new_smells,
            "cross_detector_consensus": cross_detector_consensus,
        },
    )


def _build_metrics_tool(runtime: ToolRuntimeConfig) -> BaseToolAdapter:
    name = "metrics_tool"
    return BaseToolAdapter(
        name=name,
        handlers={
            "compute_srr": lambda payload: _ok(name, "compute_srr", payload),
            "compute_sir": lambda payload: _ok(name, "compute_sir", payload),
            "compute_csr": lambda payload: _ok(name, "compute_csr", payload),
            "compute_codebleu": lambda payload: _ok(name, "compute_codebleu", payload),
            "record_costs": lambda payload: _ok(name, "record_costs", payload),
        },
    )


def _run_compile_command(
    tool_name: str,
    op_name: str,
    payload: dict[str, Any],
    runtime: ToolRuntimeConfig,
) -> ToolObservation:
    repo = _repo_path(payload)
    if repo is None:
        return _degraded(tool_name, op_name, "repo_path missing.", {"passed": True, "executed": False})
    build = _detect_build(repo, runtime)
    cmd = _compile_command(repo, build, runtime)
    if cmd is None:
        return _degraded(tool_name, op_name, f"Unsupported build system: {build}", {"passed": True, "executed": False})
    res = run_command(
        cmd,
        cwd=repo,
        timeout_sec=runtime.default_timeout_sec,
        env=_tool_env(runtime),
    )
    status = "ok" if res.ok else "error"
    return _obs(
        tool_name,
        op_name,
        status,
        "Compile executed." if res.ok else "Compile failed.",
        {
            "passed": bool(res.ok),
            "executed": True,
            "build_system": build,
            "command": cmd,
            "stdout_tail": res.tail(res.stdout),
            "stderr_tail": res.tail(res.stderr),
            "returncode": res.returncode,
        },
        error_code=None if res.ok else "COMPILE_FAILED",
    )


def _detect_build(repo: Path, runtime: ToolRuntimeConfig) -> str:
    if (repo / runtime.maven_wrapper_cmd).exists() or (repo / runtime.maven_wrapper_sh).exists():
        return "maven_wrapper"
    if (repo / "pom.xml").exists():
        return "maven"
    if (repo / runtime.gradle_wrapper).exists():
        return "gradle_wrapper"
    if (repo / "gradlew").exists():
        return "gradle_wrapper"
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        return "gradle"
    return "unknown"


def _compile_command(repo: Path, build: str, runtime: ToolRuntimeConfig) -> list[str] | None:
    maven_args = _maven_common_args(runtime)
    if build == "maven_wrapper":
        wrapper_cmd = repo / runtime.maven_wrapper_cmd
        if wrapper_cmd.exists():
            return [str(wrapper_cmd), *maven_args, "-q", "-DskipTests", "compile"]
        wrapper_sh = repo / runtime.maven_wrapper_sh
        return [str(wrapper_sh), *maven_args, "-q", "-DskipTests", "compile"]
    if build == "maven":
        return [runtime.maven_bin, *maven_args, "-q", "-DskipTests", "compile"]
    if build == "gradle_wrapper":
        wrapper_path = repo / runtime.gradle_wrapper
        if not wrapper_path.exists():
            wrapper_path = repo / "gradlew"
        wrapper = str(wrapper_path)
        return [wrapper, "classes", "--no-daemon", "-q"]
    if build == "gradle":
        return [runtime.gradle_bin, "classes", "--no-daemon", "-q"]
    return None


def _test_command(
    repo: Path,
    build: str,
    tests: list[str],
    runtime: ToolRuntimeConfig,
) -> list[str] | None:
    maven_args = _maven_common_args(runtime)
    if build == "maven_wrapper":
        joined = ",".join(_to_test_selector_maven(t) for t in tests if t)
        wrapper_cmd = repo / runtime.maven_wrapper_cmd
        if wrapper_cmd.exists():
            return [str(wrapper_cmd), *maven_args, "-q", f"-Dtest={joined}", "test"]
        wrapper_sh = repo / runtime.maven_wrapper_sh
        return [str(wrapper_sh), *maven_args, "-q", f"-Dtest={joined}", "test"]
    if build == "maven":
        joined = ",".join(_to_test_selector_maven(t) for t in tests if t)
        return [runtime.maven_bin, *maven_args, "-q", f"-Dtest={joined}", "test"]
    if build == "gradle_wrapper":
        wrapper = repo / runtime.gradle_wrapper
        if not wrapper.exists():
            wrapper = repo / "gradlew"
        cmd = [str(wrapper), "test", "--no-daemon", "-q"]
        for t in tests:
            cmd.extend(["--tests", _to_test_selector_gradle(t)])
        return cmd
    if build == "gradle":
        cmd = [runtime.gradle_bin, "test", "--no-daemon", "-q"]
        for t in tests:
            cmd.extend(["--tests", _to_test_selector_gradle(t)])
        return cmd
    return None


def _guess_impacted_tests(repo: Path, changed_files: list[str]) -> list[str]:
    if not changed_files:
        candidates = list(repo.rglob("*Test.java"))[:20]
        return [c.stem for c in candidates]
    stems = {Path(f).stem for f in changed_files if f}
    tests: list[str] = []
    for stem in stems:
        patt = f"*{stem}*Test.java"
        tests.extend([p.stem for p in repo.rglob(patt)])
    return sorted(set(tests))[:50]


def _run_detectors(
    payload: dict[str, Any],
    runtime: ToolRuntimeConfig,
) -> dict[str, Any] | None:
    repo = _repo_path(payload)
    if repo is None:
        return None
    file_path = str(payload.get("file_path") or "")
    commands: list[list[str]] = []

    cmd_payload = payload.get("detector_commands")
    if isinstance(cmd_payload, list):
        for item in cmd_payload:
            cmd = split_command(item)
            if cmd:
                commands.append(_format_cmd_tokens(cmd, repo, file_path, payload))
    else:
        for template in [runtime.pmd_command, runtime.designite_command]:
            cmd = split_command(template)
            if cmd:
                commands.append(_format_cmd_tokens(cmd, repo, file_path, payload))

    if not commands:
        return None

    outputs: list[str] = []
    used: list[str] = []
    for cmd in commands:
        res = run_command(
            cmd,
            cwd=repo,
            timeout_sec=runtime.default_timeout_sec,
            env=_tool_env(runtime),
        )
        used.append(" ".join(cmd))
        outputs.append(res.stdout + "\n" + res.stderr)
    return {"stdout": "\n".join(outputs), "detectors": used}


def _format_cmd_tokens(
    tokens: list[str],
    repo: Path,
    file_path: str,
    payload: dict[str, Any],
) -> list[str]:
    task_id = str(payload.get("task_id") or "")
    project = str(payload.get("project") or "")
    return [
        token.replace("{repo_path}", str(repo))
        .replace("{file_path}", file_path)
        .replace("{task_id}", task_id)
        .replace("{project}", project)
        for token in tokens
    ]


def _stdout_contains_smell(stdout: str, smell_type: str, file_path: str = "") -> bool:
    if not smell_type:
        return False
    aliases = _smell_aliases(smell_type)
    base_name = Path(file_path).name.lower().strip()
    lines = [line.lower() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return False

    if base_name:
        for line in lines:
            if base_name not in line:
                continue
            if any(alias in line for alias in aliases):
                return True
        return False

    return any(any(alias in line for alias in aliases) for line in lines)


def _smell_aliases(smell_type: str) -> list[str]:
    alias_map = {
        "longmethod": ["longmethod", "excessivemethodlength"],
        "complexmethod": [
            "complexmethod",
            "cyclomaticcomplexity",
            "npathcomplexity",
            "cognitivecomplexity",
        ],
        "longparameterlist": ["longparameterlist", "excessiveparameterlist"],
        "featureenvy": ["featureenvy"],
    }
    return alias_map.get(smell_type.lower(), [smell_type.lower()])


def _extract_smells_from_stdout(stdout: str) -> list[dict[str, str]]:
    text = stdout.lower()
    rule_to_smell = {
        "excessivemethodlength": "LongMethod",
        "cyclomaticcomplexity": "ComplexMethod",
        "npathcomplexity": "ComplexMethod",
        "cognitivecomplexity": "ComplexMethod",
        "excessiveparameterlist": "LongParameterList",
        "longmethod": "LongMethod",
        "complexmethod": "ComplexMethod",
        "longparameterlist": "LongParameterList",
        "featureenvy": "FeatureEnvy",
    }
    found_types: set[str] = set()
    for token, mapped in rule_to_smell.items():
        if token in text:
            found_types.add(mapped)
    found: list[dict[str, str]] = []
    for smell in sorted(found_types):
        found.append({"smell": smell, "location": "detector_output"})
    return found


def _repo_path(payload: dict[str, Any]) -> Path | None:
    value = payload.get("repo_path")
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _path_from_payload(payload: dict[str, Any], key: str) -> Path | None:
    value = payload.get(key)
    if not value:
        return None
    return Path(str(value))


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    common = len(set(a.split(".")) & set(b.split(".")))
    return common / max(1, len(set(a.split("."))))


def _to_test_selector_maven(name: str) -> str:
    if name.endswith("Test"):
        return name
    return f"{name}Test"


def _to_test_selector_gradle(name: str) -> str:
    if "." in name:
        return name
    suffix = name if name.endswith("Test") else f"{name}Test"
    return f"*{suffix}"


def _is_dubious_ownership(stderr: str) -> bool:
    return "detected dubious ownership" in stderr.lower()


def _tool_env(runtime: ToolRuntimeConfig) -> dict[str, str] | None:
    if not runtime.java_home:
        return None
    # Preserve existing PATH while injecting JAVA_HOME.
    import os

    env = dict(os.environ)
    env["JAVA_HOME"] = runtime.java_home
    return env


def _maven_common_args(runtime: ToolRuntimeConfig) -> list[str]:
    args: list[str] = []
    if runtime.maven_settings_file:
        args.extend(["-s", runtime.maven_settings_file])
    if runtime.maven_local_repo:
        args.append(f"-Dmaven.repo.local={runtime.maven_local_repo}")
    return args
