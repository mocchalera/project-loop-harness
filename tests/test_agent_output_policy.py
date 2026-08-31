from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import pcl.contracts.agent_output as agent_output_contract
from pcl.agent_output_policy import (
    canonical_agent_output_policy,
    classify_agent_output_argv,
    classify_agent_output_command,
)
from pcl.agent_output_renderer import AGENT_OUTPUT_HOSTS, render_agent_output_host
from pcl.cli import main
from pcl.contracts.agent_output import (
    AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
    AGENT_OUTPUT_POLICY_CONTRACT_VERSION,
    validate_agent_output_classification,
    validate_agent_output_policy,
)


ELIGIBLE_CASES = [
    (["pytest"], "pytest_direct"),
    (["python", "-m", "pytest"], "python_module_pytest"),
    (["ruff", "check"], "ruff_check"),
    (["mypy"], "mypy"),
    (["pyright"], "pyright"),
    (["python", "-m", "build"], "python_module_build"),
    (["npm", "test"], "npm_test"),
    (["npm", "run", "test"], "npm_run_test_script"),
    (["npm", "run", "test:unit"], "npm_run_test_unit_script"),
    (["npm", "run", "lint"], "npm_run_lint_script"),
    (["npm", "run", "typecheck"], "npm_run_typecheck_script"),
    (["npm", "run", "build"], "npm_run_build_script"),
    (["npm", "run", "verify"], "npm_run_verify_command"),
    (["npm", "run", "verify:full"], "npm_run_verify_script"),
    (["pytest", "-k", "pass"], "pytest_direct"),
    (["pytest", "-k", "authorization"], "pytest_direct"),
    (["pytest", "-k", "report"], "pytest_direct"),
    (["pytest", "tests/test_functional.py"], "pytest_direct"),
    (["pytest", "-k", "markers"], "pytest_direct"),
    (["pytest", "-k", "functionality"], "pytest_direct"),
    (["pytest", "-k", "funcargs"], "pytest_direct"),
    (["pytest", "-k", "fixtures"], "pytest_direct"),
    (["pytest", "-k", "setup-plan"], "pytest_direct"),
    (["pytest", "-k", "trace-config"], "pytest_direct"),
    (["pytest", "tests/test_funcargs.py"], "pytest_direct"),
    (["pnpm", "test"], "pnpm_test"),
    (["yarn", "test"], "yarn_test"),
    (["tsc", "--noEmit"], "tsc_no_emit"),
    (["eslint"], "eslint"),
    (["cargo", "test"], "cargo_test"),
    (["cargo", "build"], "cargo_build"),
    (["cargo", "clippy"], "cargo_clippy"),
    (["go", "test"], "go_test"),
    (["go", "test", "./..."], "go_test_all_packages"),
    (["go", "build"], "go_build"),
    (["pip", "install", "--no-input", "package"], "pip_install_non_interactive"),
    (["pip", "install", "package", "--no-input"], "pip_install_non_interactive"),
    (
        ["python", "-m", "pip", "install", "--no-input", "package"],
        "python_pip_install_non_interactive",
    ),
    (
        ["python", "-m", "pip", "install", "package", "--no-input"],
        "python_pip_install_non_interactive",
    ),
    (["pip3", "install", "--no-input", "package"], "pip3_install_non_interactive"),
    (
        ["python3", "-m", "pip", "install", "--no-input", "package"],
        "python3_pip_install_non_interactive",
    ),
    (["go", "install", "example.com/tool@v1.2.3"], "go_install"),
]


def _assert_no_sensitive_fixture_leak(value: str) -> None:
    if "SENTINEL" in value:
        raise AssertionError("sensitive fixture value was leaked")


def _assert_no_path_fixture_leak(value: str) -> None:
    if "REVIEWER_PATH_SENTINEL" in value:
        raise AssertionError("path fixture value was leaked")


@pytest.mark.parametrize(("argv", "reason_code"), ELIGIBLE_CASES)
def test_eligible_verification_families_are_classified_without_rewrite(
    argv: list[str], reason_code: str
) -> None:
    result = classify_agent_output_argv(argv)

    assert result == {
        "schema": AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
        "classification": "eligible",
        "reason_code": reason_code,
        "recommended_argv_prefix": ["pcl", "exec", "--"],
        "may_rewrite": False,
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["cat", "README.md"],
        ["sed", "-n", "1,20p", "README.md"],
        ["head", "README.md"],
        ["tail", "README.md"],
        ["rg", "needle"],
        ["grep", "needle", "file"],
        ["find", ".", "-type", "f"],
        ["git", "diff"],
        ["git", "show", "HEAD"],
        ["git", "log", "-1"],
        ["report", "--json"],
        ["python", "-m", "report"],
        ["npm", "run", "report"],
        ["pytest", "--junitxml=results.xml"],
        ["pytest", "--output-is-artifact=true"],
        ["pytest", "--help"],
        ["mypy", "--version"],
        ["mypy", "-V"],
        ["go", "test", "-list", "."],
        ["npm", "test", "--", "--listTests"],
        ["cargo", "test", "--", "--list"],
        ["pytest", "--co"],
        ["python", "-m", "pytest", "--co"],
        ["pytest", "--fixtures"],
        ["python", "-m", "pytest", "--fixtures"],
        ["pytest", "--markers"],
        ["python", "-m", "pytest", "--markers"],
        ["pytest", "--funcargs"],
        ["python", "-m", "pytest", "--funcargs"],
        ["pytest", "--fixtures-per-test"],
        ["python", "-m", "pytest", "--fixtures-per-test"],
        ["pytest", "--setup-plan"],
        ["python", "-m", "pytest", "--setup-plan"],
        ["pytest", "--trace-config"],
        ["python", "-m", "pytest", "--trace-config"],
        ["pytest", "--setup-only"],
        ["python", "-m", "pytest", "--setup-only"],
        ["pytest", "--setup-show"],
        ["python", "-m", "pytest", "--setup-show"],
        ["pytest", "--durations=10"],
        ["python", "-m", "pytest", "--durations", "10"],
        ["pytest", "--report-chars", "f"],
        ["python", "-m", "pytest", "-r", "f"],
        ["pytest", "-V"],
        ["python", "-m", "pytest", "-V"],
        ["pytest", "--collect-only"],
        ["pytest", "--junit-xml", "results.xml"],
        ["pytest", "--junit-xml=results.xml"],
        ["pytest", "--report=results.xml"],
        ["pytest", "-VV"],
        ["python", "-m", "pytest", "-VV"],
        ["pytest", "-qVV"],
        ["python", "-m", "pytest", "-xVV"],
        ["ruff", "check", "--output-format=json"],
        ["ruff", "check", "--output-format", "json"],
        ["ruff", "check", "--output-file=results.json"],
        ["ruff", "check", "--output-file", "results.json"],
    ],
)
def test_reads_searches_diffs_and_reports_remain_negative(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "negative"
    assert result["recommended_argv_prefix"] == []
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["interactive"],
        ["watch", "pytest"],
        ["server"],
        ["python", "-m", "http.server"],
        ["npm", "run", "watch"],
        ["npm", "run", "dev"],
        ["npm", "run", "test:watchAll"],
        ["npm", "run", "test:debug"],
        ["docker", "logs", "-f", "app"],
        ["npm", "install"],
        ["pnpm", "install"],
        ["yarn", "install"],
        ["pip", "install", "package"],
        ["python", "-m", "pip", "install", "package"],
        ["cargo", "install", "package"],
    ],
)
def test_interactive_watch_server_stream_and_installers_remain_negative(
    argv: list[str],
) -> None:
    assert classify_agent_output_argv(argv)["classification"] == "negative"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "--pdb"],
        ["pytest", "--trace"],
        ["python", "-m", "pytest", "--pdb"],
        ["python", "-m", "pytest", "--trace"],
        ["npm", "test", "--", "--watchAll"],
        ["npm", "test", "--", "--watchAll=true"],
        ["npm", "test", "--", "--watch"],
        ["npm", "test", "--", "--watch=true"],
        ["npm", "test", "--", "--debug"],
        ["npm", "test", "--", "--inspect"],
        ["npm", "test", "--", "--inspect-brk"],
    ],
)
def test_watch_and_debug_flags_are_negative_before_eligible_prefixes(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "negative"
    assert result["recommended_argv_prefix"] == []
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "--watcher"],
        ["pytest", "--debugger"],
        ["npm", "test", "--", "--watchdog"],
        ["npm", "test", "--", "--debugger"],
    ],
)
def test_similar_non_mode_flags_do_not_trigger_broad_watch_or_debug_matching(
    argv: list[str],
) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-qh"],
        ["python", "-m", "pytest", "-qh"],
        ["pytest", "-xqh"],
        ["pytest", "-rP"],
        ["python", "-m", "pytest", "-ra"],
        ["pytest", "-r", "P"],
        ["python", "-m", "pytest", "-rEw"],
    ],
)
def test_pytest_combined_help_and_report_short_options_are_negative(
    argv: list[str],
) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "negative"
    assert result["reason_code"] == "complete_output"
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-k", "-qh"],
        ["python", "-m", "pytest", "-m", "-rP"],
        ["pytest", "-k=-rP"],
        ["python", "-m", "pytest", "-m=-qh"],
        ["pytest", "-k-rP"],
        ["python", "-m", "pytest", "-m-qh"],
    ],
)
def test_pytest_selection_expressions_are_not_scanned_as_short_presentation_options(
    argv: list[str],
) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] in {"pytest_direct", "python_module_pytest"}


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "--client-secret", "SENTINEL"],
        ["pytest", "--client-secret=SENTINEL"],
        ["pytest", "--AuthToken=SENTINEL"],
        ["pytest", "--Client-Secret=SENTINEL"],
        ["pytest", "--ClientSecret=SENTINEL"],
        ["pytest", "--clientSecret=SENTINEL"],
        ["pytest", "--client_secret=SENTINEL"],
        ["pytest", "--client-secret:SENTINEL=tail"],
        ["pytest", "--client-secret:SENTINEL"],
        ["pytest", "API_TOKEN=SENTINEL"],
        ["pytest", "--CLIENT_SECRET=SENTINEL"],
        ["pytest", "AWS_SECRET_ACCESS_KEY=SENTINEL"],
        ["pytest", "authorization:SENTINEL=tail"],
        ["pytest", "proxy-authorization:SENTINEL=tail"],
    ],
)
def test_compound_secret_keys_are_unknown_without_echoing_values(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "secret_shaped_argv"
    _assert_no_sensitive_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "token=VALUE"],
        ["pytest", "password:SENTINEL"],
        ["pytest", "client-secret=SENTINEL"],
        ["pytest", "clientSecret:SENTINEL"],
        ["pytest", "AuthToken=SENTINEL"],
        ["pytest", "api_key:SENTINEL"],
        ["pytest", "PASSWORD=SENTINEL"],
    ],
)
def test_lowercase_and_mixed_explicit_secret_keys_are_unknown(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "secret_shaped_argv"
    _assert_no_sensitive_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "ordinary=value"],
        ["pytest", "name:value"],
        ["pytest", "-k", "password=VALUE"],
        ["pytest", "-m", "token:VALUE"],
        ["pytest", "-k=password:VALUE"],
        ["pytest", "-mtoken=VALUE"],
    ],
)
def test_positional_and_selection_values_are_not_secret_keys(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["pytest", "--header=Authorization:Basic SENTINEL"],
            id="equals-authorization",
        ),
        pytest.param(
            ["pytest", "--header:Authorization:Basic SENTINEL"],
            id="colon-authorization",
        ),
        pytest.param(
            ["pytest", "--header", "Authorization:Basic SENTINEL"],
            id="separated-authorization",
        ),
        pytest.param(
            ["pytest", "--header=Proxy-Authorization:Basic SENTINEL"],
            id="equals-proxy-authorization",
        ),
        pytest.param(
            ["pytest", "--header", "pRoXy-AuThOrIzAtIoN:Basic SENTINEL"],
            id="separated-mixed-proxy-authorization",
        ),
    ],
)
def test_nested_sensitive_headers_are_unknown_without_echoing_values(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "secret_shaped_argv"
    _assert_no_sensitive_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-k", "funcargs"],
        ["pytest", "-k", "fixtures"],
        ["pytest", "-k", "setup-plan"],
        ["pytest", "-k", "trace-config"],
        ["pytest", "tests/test_funcargs.py"],
    ],
)
def test_pytest_presentation_words_in_values_remain_eligible(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-k", "pass"],
        ["pytest", "-k", "authorization"],
    ],
)
def test_pytest_select_expression_values_are_not_secret_keys(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["pytest", "/private/REVIEWER_PATH_SENTINEL/file.py"], id="posix-raw"),
        pytest.param(["pytest", r"C:\REVIEWER_PATH_SENTINEL\file.py"], id="windows-drive-raw"),
        pytest.param(["pytest", r"\\REVIEWER_PATH_SENTINEL\share\file.py"], id="windows-unc-raw"),
        pytest.param(["pytest", "~/REVIEWER_PATH_SENTINEL/file.py"], id="home-raw"),
        pytest.param(
            ["pytest", "--rootdir:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-colon",
        ),
        pytest.param(
            ["pytest", "--rootdir=/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-equals",
        ),
        pytest.param(
            ["pytest", "--rootdir", "/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-separated",
        ),
        pytest.param(
            ["pytest", r"--rootdir:C:\REVIEWER_PATH_SENTINEL\file.py"],
            id="windows-drive-colon",
        ),
        pytest.param(
            ["pytest", r"--rootdir=\\REVIEWER_PATH_SENTINEL\share\file.py"],
            id="windows-unc-equals",
        ),
        pytest.param(
            ["pytest", "--rootdir:~/REVIEWER_PATH_SENTINEL/file.py"],
            id="home-colon",
        ),
        pytest.param(
            ["pytest", "--rootdir=~/REVIEWER_PATH_SENTINEL/file.py"],
            id="home-equals",
        ),
        pytest.param(
            ["pytest", "--rootdir:/private/REVIEWER_PATH_SENTINEL/file=tail.py"],
            id="colon-value-with-equals",
        ),
        pytest.param(
            ["pytest", "file:///private/REVIEWER_PATH_SENTINEL/file.py"],
            id="file-uri-posix-raw",
        ),
        pytest.param(
            ["pytest", "file://localhost/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="file-uri-localhost-raw",
        ),
        pytest.param(
            ["pytest", "file:///C:/REVIEWER_PATH_SENTINEL/file.py"],
            id="file-uri-windows-drive",
        ),
        pytest.param(
            ["pytest", "--rootdir=file:///private/REVIEWER_PATH_SENTINEL/file.py"],
            id="file-uri-equals",
        ),
        pytest.param(
            ["pytest", "--rootdir:file://localhost/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="file-uri-colon",
        ),
        pytest.param(
            [
                "pytest",
                "--rootdir",
                "file:///private/REVIEWER_PATH_SENTINEL/file.py",
            ],
            id="file-uri-separated",
        ),
    ],
)
def test_path_bearing_argv_is_unknown_without_echoing_paths(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "absolute_path_argv"
    _assert_no_path_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["pytest", "--search-path=relative:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-equals",
        ),
        pytest.param(
            ["pytest", "--search-path:relative:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-colon",
        ),
        pytest.param(
            ["pytest", "--search-path", "relative:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-separated",
        ),
        pytest.param(
            ["pytest", "--search-path=relative;C:\\REVIEWER_PATH_SENTINEL\\file.py"],
            id="windows-drive-list",
        ),
        pytest.param(
            ["pytest", "--search-path", r"relative;\\REVIEWER_PATH_SENTINEL\share\file.py"],
            id="windows-unc-list",
        ),
        pytest.param(
            ["pytest", "--search-path=relative,~/REVIEWER_PATH_SENTINEL/file.py"],
            id="home-list",
        ),
        pytest.param(
            ["pytest", "SEARCH_PATH=relative:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="env-key-list",
        ),
    ],
)
def test_path_list_values_are_unknown_without_echoing_paths(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "absolute_path_argv"
    _assert_no_path_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "--search-path", "https://example.test/resource"],
        ["pytest", "--search-path=https://example.test/resource"],
        ["pytest", "--search-path", "relative:other"],
        ["pytest", "--url", "authorization://example.test/resource"],
        ["pytest", "--url", "Proxy-Authorization://example.test/resource"],
        ["pytest", "--url=authorization://example.test/resource"],
        ["pytest", "file://remote.example/resource"],
        ["pytest", "--url", "file://remote.example/resource"],
    ],
)
def test_path_lists_and_authorization_uris_remain_eligible(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["pytest", "--url", "Authorization:Basic SENTINEL"], id="authorization"),
        pytest.param(
            ["pytest", "--url", "pRoXy-AuThOrIzAtIoN:Basic SENTINEL"],
            id="proxy-authorization",
        ),
    ],
)
def test_separated_sensitive_headers_remain_unknown_without_echoing_values(
    argv: list[str],
) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "secret_shaped_argv"
    _assert_no_sensitive_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["pytest", "https://example.test/REVIEWER_PATH_SENTINEL"], id="url"),
        pytest.param(
            ["pytest", "--url:https://example.test/REVIEWER_PATH_SENTINEL"],
            id="option-url",
        ),
        pytest.param(
            ["pytest", "--url=authorization://example.test/resource"],
            id="authorization-url-scheme",
        ),
        pytest.param(["pytest", "name:REVIEWER_PATH_SENTINEL"], id="ordinary-colon"),
    ],
)
def test_colon_values_that_are_not_paths_remain_eligible(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


def test_policy_marker_semantics_survive_permissive_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = canonical_agent_output_policy()
    candidate["unsafe_shell_markers"].remove("|")
    monkeypatch.setattr(agent_output_contract, "validate_schema", lambda _value, _schema: [])

    validation = agent_output_contract.validate_agent_output_policy(candidate)
    result = classify_agent_output_argv(["pytest"], policy=candidate)

    assert validation.ok is False
    assert result["classification"] == "unknown"
    assert result["reason_code"] == "invalid_policy"


def test_policy_requires_the_full_canonical_unsafe_shell_marker_set() -> None:
    canonical = canonical_agent_output_policy()
    assert validate_agent_output_policy(canonical).ok is True

    for marker in canonical["unsafe_shell_markers"]:
        candidate = deepcopy(canonical)
        candidate["unsafe_shell_markers"].remove(marker)
        validation = validate_agent_output_policy(candidate)

        assert validation.ok is False
        assert (
            classify_agent_output_argv(["pytest"], policy=candidate)["reason_code"]
            == "invalid_policy"
        )

    incomplete = deepcopy(canonical)
    incomplete["unsafe_shell_markers"] = ["|"]
    assert validate_agent_output_policy(incomplete).ok is False


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "|", "cat"],
        ["pytest", ">", "result.txt"],
        ["pytest", ">>", "result.txt"],
        ["pytest", "<", "input.txt"],
        ["pytest", "$(cat", "input.txt)"],
        ["pytest", "`cat", "input.txt`"],
        ["pytest", "&&", "ruff", "check"],
        ["pytest", "||", "ruff", "check"],
        ["pytest", ";", "ruff", "check"],
        ["pytest", "&", "ruff", "check"],
        ["pytest", "line\nnext"],
        ["pytest", "function", "run"],
        ["pytest", "function foo"],
        ["pytest", "function()"],
        ["pytest", "heredoc"],
        ["pytest", "<<EOF"],
        ["pytest", "cat <<heredoc"],
        ["sh", "-c", "pytest"],
        ["python", "-c", "pytest"],
        ["pytest", "'unterminated"],
    ],
)
def test_shell_expressions_and_malformed_quoting_are_unknown(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] in {
        "unsafe_shell_expression",
        "shell_invocation",
        "malformed_quoting",
    }
    assert result["recommended_argv_prefix"] == []
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "tests/test_functional.py"],
        ["pytest", "-k", "markers"],
        ["pytest", "-k", "functionality"],
        ["pytest", "-k", "heredocs"],
    ],
)
def test_word_shell_markers_do_not_match_normal_argv_words(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "tests/a&b.py"],
        ["pytest", "--keyword=a&b"],
        ["pytest", "-k", "a&b"],
    ],
)
def test_embedded_ampersands_are_literal_argv_values(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "eligible"
    assert result["reason_code"] == "pytest_direct"


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "github_pat_abcdefghijklmnopqrstSENTINEL"],
        ["pytest", "AKIA1234567890ABCDEF"],
    ],
)
def test_known_executor_secret_signatures_are_unknown_without_echoing_values(
    argv: list[str],
) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "secret_shaped_argv"
    _assert_no_sensitive_fixture_leak(json.dumps(result))


@pytest.mark.parametrize(
    "argv",
    [
        ["pip", "install", "--", "--no-input"],
        ["python", "-m", "pip", "install", "--", "--no-input"],
        ["pip3", "install", "package", "--", "--no-input"],
        ["python3", "-m", "pip", "install", "package", "--", "--no-input"],
    ],
)
def test_pip_noninteractive_flag_after_terminator_is_not_eligible(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "negative"
    assert result["reason_code"] in {"pip_install", "python_pip_install"}
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["pcl", "exec", "--", "pytest"],
        ["pcl", "exec", "--json", "--", "pytest"],
        ["pcl", "exec", "--root", "project", "--", "pytest"],
        ["pcl", "--json", "exec", "--", "npm", "test"],
        ["pcl", "--json", "exec", "--timeout-seconds", "300", "--", "cargo", "test"],
        [
            "pcl",
            "--root",
            "project",
            "--json",
            "exec",
            "--max-output-bytes=1024",
            "--redact-pattern",
            "TOKEN",
            "--allow-env=PATH",
            "--",
            "pytest",
        ],
        [
            "pcl",
            "exec",
            "--timeout-seconds=300",
            "--max-output-bytes",
            "1024",
            "--redact-pattern=TOKEN",
            "--allow-env",
            "PATH",
            "--",
            "pytest",
        ],
        ["pcl", "exec", "--timeout-seconds", "1", "--max-output-bytes", "1", "--", "pytest"],
        [
            "pcl",
            "exec",
            "--timeout-seconds=1",
            "--max-output-bytes=8388608",
            "--redact-pattern=.",
            "--allow-env=GOOD_NAME",
            "--",
            "pytest",
        ],
        ["pcl", "exec", "--redact-pattern=-x", "--", "pytest"],
        ["python", "-m", "pcl", "exec", "--redact-pattern=-x", "--", "pytest"],
        [
            "python",
            "-m",
            "pcl",
            "exec",
            "--timeout-seconds=1",
            "--max-output-bytes=8388608",
            "--redact-pattern",
            ".",
            "--allow-env",
            "GOOD_NAME",
            "--",
            "pytest",
        ],
        ["python", "-m", "pcl", "exec", "--", "cargo", "test"],
        [
            "python",
            "-m",
            "pcl",
            "--json",
            "exec",
            "--timeout-seconds",
            "300",
            "--",
            "cargo",
            "test",
        ],
        ["python3", "-m", "pcl", "--root=project", "exec", "--allow-env=PATH", "--", "pytest"],
        ["pcl", "exec", "--", "pcl", "exec", "--", "pytest"],
    ],
)
def test_already_wrapped_commands_are_not_nested(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "already_wrapped"
    assert result["reason_code"] == "already_wrapped_pcl_exec"
    assert result["recommended_argv_prefix"] == []
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["pcl", "exec"], id="missing-separator-and-child"),
        pytest.param(["pcl", "exec", "--"], id="missing-child"),
        pytest.param(["pcl", "exec", "--timeout-seconds", "--", "pytest"], id="missing-timeout"),
        pytest.param(
            ["pcl", "exec", "--max-output-bytes", "--", "pytest"],
            id="missing-max-output",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern", "--", "pytest"],
            id="missing-redact-pattern",
        ),
        pytest.param(
            ["pcl", "exec", "--allow-env", "--", "pytest"],
            id="missing-allow-env",
        ),
        pytest.param(
            ["pcl", "exec", "--timeout-seconds", "not-an-integer", "--", "pytest"],
            id="invalid-timeout",
        ),
        pytest.param(
            ["pcl", "exec", "--unknown", "value", "--", "pytest"],
            id="unknown-exec-option",
        ),
        pytest.param(
            ["pcl", "exec", "--timeout-seconds", "300", "pytest"],
            id="missing-separator",
        ),
        pytest.param(
            ["pcl", "--root", "--json", "exec", "--", "pytest"],
            id="missing-root-value",
        ),
        pytest.param(
            ["pcl", "--json", "exec", "--timeout-seconds=300"],
            id="missing-separator-and-child-after-option",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--max-output-bytes", "1024", "--"],
            id="python-missing-child",
        ),
        pytest.param(
            ["pcl", "--unknown", "exec", "--", "pytest"],
            id="unknown-global-option",
        ),
    ],
)
def test_malformed_already_wrapped_commands_remain_unknown(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["may_rewrite"] is False


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["pcl", "exec", "--timeout-seconds", "0", "--", "pytest"],
            id="pcl-timeout-zero-separated",
        ),
        pytest.param(
            ["pcl", "exec", "--timeout-seconds=-1", "--", "pytest"],
            id="pcl-timeout-negative-equals",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--timeout-seconds", "0", "--", "pytest"],
            id="python-timeout-zero-separated",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--timeout-seconds=-1", "--", "pytest"],
            id="python-timeout-negative-equals",
        ),
        pytest.param(
            ["pcl", "exec", "--max-output-bytes", "0", "--", "pytest"],
            id="pcl-max-zero-separated",
        ),
        pytest.param(
            ["pcl", "exec", "--max-output-bytes=8388609", "--", "pytest"],
            id="pcl-max-over-equals",
        ),
        pytest.param(
            [
                "python",
                "-m",
                "pcl",
                "exec",
                "--max-output-bytes",
                "8388609",
                "--",
                "pytest",
            ],
            id="python-max-over-separated",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--max-output-bytes=0", "--", "pytest"],
            id="python-max-zero-equals",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern", "[", "--", "pytest"],
            id="pcl-redact-invalid-separated",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern=[", "--", "pytest"],
            id="pcl-redact-invalid-equals",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--redact-pattern", "[", "--", "pytest"],
            id="python-redact-invalid-separated",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--redact-pattern=[", "--", "pytest"],
            id="python-redact-invalid-equals",
        ),
        pytest.param(
            ["pcl", "exec", "--allow-env", "BAD-NAME", "--", "pytest"],
            id="pcl-env-invalid-separated",
        ),
        pytest.param(
            ["pcl", "exec", "--allow-env=BAD-NAME", "--", "pytest"],
            id="pcl-env-invalid-equals",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--allow-env", "BAD-NAME", "--", "pytest"],
            id="python-env-invalid-separated",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--allow-env=BAD-NAME", "--", "pytest"],
            id="python-env-invalid-equals",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern", "--json", "--", "pytest"],
            id="pcl-redact-option-shaped-json",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern", "--timeout-seconds=1", "--", "pytest"],
            id="pcl-redact-option-shaped-timeout",
        ),
        pytest.param(
            ["pcl", "exec", "--redact-pattern", "-x", "--", "pytest"],
            id="pcl-redact-option-shaped-short",
        ),
        pytest.param(
            [
                "python",
                "-m",
                "pcl",
                "exec",
                "--redact-pattern",
                "--json",
                "--",
                "pytest",
            ],
            id="python-redact-option-shaped-json",
        ),
        pytest.param(
            [
                "python",
                "-m",
                "pcl",
                "exec",
                "--redact-pattern",
                "--timeout-seconds=1",
                "--",
                "pytest",
            ],
            id="python-redact-option-shaped-timeout",
        ),
        pytest.param(
            ["python", "-m", "pcl", "exec", "--redact-pattern", "-x", "--", "pytest"],
            id="python-redact-option-shaped-short",
        ),
    ],
)
def test_invalid_already_wrapped_values_remain_unknown(argv: list[str]) -> None:
    result = classify_agent_output_argv(argv)

    assert result["classification"] == "unknown"
    assert result["reason_code"] == "unsupported_argv"
    assert result["may_rewrite"] is False


def test_policy_and_classification_contracts_reject_unknown_fields() -> None:
    policy = canonical_agent_output_policy()
    policy["unexpected"] = True
    policy_result = validate_agent_output_policy(policy)
    assert policy_result.ok is False
    assert any("additional property is not allowed" in error for error in policy_result.errors)

    classification = classify_agent_output_argv(["pytest"])
    classification["unexpected"] = True
    classification_result = validate_agent_output_classification(classification)
    assert classification_result.ok is False
    assert any("additional property is not allowed" in error for error in classification_result.errors)


def test_policy_contract_freezes_result_handling_and_reason_codes() -> None:
    policy = canonical_agent_output_policy()
    assert policy["schema"] == AGENT_OUTPUT_POLICY_CONTRACT_VERSION
    assert policy["result_handling"] == {
        "pass_reads_diagnostics": False,
        "automatic_retry": False,
        "raw_log_upload": False,
    }
    reasons = [
        rule["reason_code"]
        for section in ("eligible_argv_rules", "negative_argv_rules")
        for rule in policy[section]
    ]
    assert len(reasons) == len(set(reasons))
    assert validate_agent_output_policy(policy).ok is True


def test_classification_is_deterministic_and_observing_a_string_does_not_shell_parse() -> None:
    argv = ["npm", "run", "verify:full"]
    assert classify_agent_output_argv(argv) == classify_agent_output_argv(tuple(argv))
    observed = classify_agent_output_command("npm run verify:full")
    assert observed["classification"] == "unknown"
    assert observed["reason_code"] == "host_command_string_not_tokenized"
    assert "npm run verify:full" not in json.dumps(observed)


def test_sensitive_oversized_and_absolute_argv_are_unknown_without_leaking_values() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    absolute = "/private/secret/project/file.py"
    cases = [
        ["pytest", "--token", secret],
        ["pytest", "--token"],
        ["pytest", f"--api-key={secret}"],
        ["pytest", absolute],
        ["pytest", "C:\\private\\secret\\file.py"],
        ["pytest", "\ud800"],
        ["pytest"] + ["x" * 1000] * 10,
        ["pytest", "x" * 5000],
    ]

    for argv in cases:
        result = classify_agent_output_argv(argv)
        serialized = json.dumps(result, ensure_ascii=False)
        assert result["classification"] == "unknown"
        assert secret not in serialized
        assert absolute not in serialized
        assert "private" not in serialized


def test_cli_classify_bounds_json_and_does_not_create_project_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    oversized = json.dumps(["pytest", "x" * 70_000])

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "agent-output",
                "classify",
                "--argv-json",
                json.dumps(["pytest", "--token", secret]),
                "--json",
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["classification"] == "unknown"
    assert secret not in json.dumps(first)

    assert main(["agent-output", "classify", "--argv-json", oversized, "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["reason_code"] == "argv_json_too_large"
    assert list(tmp_path.iterdir()) == []


def test_cli_policy_and_contract_validate_are_read_only(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "agent-output", "policy", "--json"]) == 0
    policy = json.loads(capsys.readouterr().out)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "contract",
                "validate",
                "--type",
                AGENT_OUTPUT_POLICY_CONTRACT_VERSION,
                str(policy_path),
                "--json",
            ]
        )
        == 0
    )
    validation = json.loads(capsys.readouterr().out)
    assert validation["ok"] is True
    assert not (tmp_path / ".project-loop").exists()


def test_host_projections_have_semantic_parity_and_are_deterministic() -> None:
    projections = {host: render_agent_output_host(host) for host in AGENT_OUTPUT_HOSTS}
    assert projections == {host: render_agent_output_host(host) for host in AGENT_OUTPUT_HOSTS}

    required_terms = (
        "eligible",
        "negative",
        "unknown",
        "already_wrapped",
        "PASS",
        "non-PASS",
        "retry",
        "rewrite",
        "raw logs",
        "audit-only",
    )
    for content in projections.values():
        for term in required_terms:
            assert term in content

    assert "enforcement hook" in projections["codex"]
    assert "enforcement hook" in projections["opencode"]
    assert "typed summaries only" in projections["cockpit"]
    assert "generic shell" not in projections["cockpit"]
    assert "raw stdout/stderr" in projections["cockpit"]


def test_classification_payloads_always_validate() -> None:
    for argv, _reason in ELIGIBLE_CASES:
        assert validate_agent_output_classification(classify_agent_output_argv(argv)).ok

    for argv in (["rg", "x"], ["pytest", "|", "cat"], ["not-a-check"]):
        assert validate_agent_output_classification(classify_agent_output_argv(argv)).ok
