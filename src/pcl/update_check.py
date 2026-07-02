from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
import json
from json import JSONDecodeError
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


PACKAGE_NAME = "project-loop-harness"
PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
NO_VERSION_CHECK_ENV = "PCL_NO_VERSION_CHECK"
DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60

_VERSION_RE = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+)*)"
    r"(?:(?P<pre>a|b|rc)(?P<pre_n>\d+))?"
    r"(?:\.post(?P<post_n>\d+))?"
    r"(?:\.dev(?P<dev_n>\d+))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InstallContext:
    method: str
    command: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "method": self.method,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    package: str
    current_version: str
    latest_version: str | None
    update_available: bool
    source_url: str
    checked_at: str
    install: InstallContext
    cache_used: bool = False
    cache_path: Path | None = None
    disabled: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache": {
                "path": str(self.cache_path) if self.cache_path else None,
                "used": self.cache_used,
            },
            "checked_at": self.checked_at,
            "current_version": self.current_version,
            "disabled": self.disabled,
            "error": self.error,
            "install": self.install.to_dict(),
            "latest_version": self.latest_version,
            "ok": self.ok,
            "package": self.package,
            "source_url": self.source_url,
            "update_available": self.update_available,
        }


def check_for_update(
    *,
    current_version: str = __version__,
    package: str = PACKAGE_NAME,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    cache_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    fetcher: Callable[[str, float], dict[str, Any]] | None = None,
    now: Callable[[], datetime] | None = None,
) -> UpdateCheckResult:
    environment = env if env is not None else os.environ
    clock = now or _utc_now
    checked_at = _format_timestamp(clock())
    source_url = PYPI_JSON_URL.format(package=package)
    context = detect_install_context(package)
    resolved_cache_path = cache_path or default_cache_path(environment)

    if _truthy(environment.get(NO_VERSION_CHECK_ENV)):
        return UpdateCheckResult(
            ok=True,
            package=package,
            current_version=current_version,
            latest_version=None,
            update_available=False,
            source_url=source_url,
            checked_at=checked_at,
            install=context,
            cache_path=resolved_cache_path,
            disabled=True,
        )

    if use_cache:
        cached_version = _read_cached_latest_version(
            resolved_cache_path,
            now=clock(),
            ttl_seconds=cache_ttl_seconds,
        )
        if cached_version:
            return _result_from_latest(
                package=package,
                current_version=current_version,
                latest_version=cached_version,
                source_url=source_url,
                checked_at=checked_at,
                install=context,
                cache_path=resolved_cache_path,
                cache_used=True,
            )

    try:
        data = (fetcher or _fetch_project_json)(source_url, timeout)
        latest_version = _extract_latest_version(data)
    except (HTTPError, URLError, TimeoutError, OSError, JSONDecodeError, ValueError) as exc:
        return UpdateCheckResult(
            ok=False,
            package=package,
            current_version=current_version,
            latest_version=None,
            update_available=False,
            source_url=source_url,
            checked_at=checked_at,
            install=context,
            cache_path=resolved_cache_path,
            error=str(exc),
        )

    _write_cached_latest_version(resolved_cache_path, latest_version=latest_version, checked_at=checked_at)
    return _result_from_latest(
        package=package,
        current_version=current_version,
        latest_version=latest_version,
        source_url=source_url,
        checked_at=checked_at,
        install=context,
        cache_path=resolved_cache_path,
    )


def detect_install_context(package: str = PACKAGE_NAME) -> InstallContext:
    executable = Path(sys.executable).as_posix()
    prefix = Path(sys.prefix).as_posix()
    if "/pipx/venvs/" in executable or "/pipx/venvs/" in prefix:
        return InstallContext(
            method="pipx",
            command=f"pipx upgrade {package}",
            reason="current Python executable appears to run from a pipx venv",
        )
    if _is_editable_install(package):
        return InstallContext(
            method="editable",
            command="git pull && python -m pip install -e '.[dev]'",
            reason="package metadata reports an editable local install",
        )
    return InstallContext(
        method="pip",
        command=f"python -m pip install --upgrade {package}",
        reason="default pip upgrade command for non-pipx installs",
    )


def is_newer_version(latest_version: str, current_version: str) -> bool:
    latest_key = _version_key(latest_version)
    current_key = _version_key(current_version)
    if latest_key is None or current_key is None:
        return latest_version != current_version
    return latest_key > current_key


def default_cache_path(env: Mapping[str, str] | None = None) -> Path:
    environment = env if env is not None else os.environ
    cache_home = environment.get("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base / "project-loop-harness" / "update-check.json"


def _result_from_latest(
    *,
    package: str,
    current_version: str,
    latest_version: str,
    source_url: str,
    checked_at: str,
    install: InstallContext,
    cache_path: Path,
    cache_used: bool = False,
) -> UpdateCheckResult:
    return UpdateCheckResult(
        ok=True,
        package=package,
        current_version=current_version,
        latest_version=latest_version,
        update_available=is_newer_version(latest_version, current_version),
        source_url=source_url,
        checked_at=checked_at,
        install=install,
        cache_used=cache_used,
        cache_path=cache_path,
    )


def _fetch_project_json(url: str, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "project-loop-harness",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def _is_editable_install(package: str) -> bool:
    try:
        dist = metadata.distribution(package)
    except metadata.PackageNotFoundError:
        return False
    direct_url = dist.read_text("direct_url.json")
    if not direct_url:
        return False
    try:
        data = json.loads(direct_url)
    except JSONDecodeError:
        return False
    dir_info = data.get("dir_info")
    return isinstance(dir_info, dict) and dir_info.get("editable") is True


def _extract_latest_version(data: dict[str, Any]) -> str:
    info = data.get("info")
    if not isinstance(info, dict):
        raise ValueError("PyPI response is missing info metadata")
    version = info.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("PyPI response is missing info.version")
    return version


def _read_cached_latest_version(path: Path, *, now: datetime, ttl_seconds: int) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return None
    latest_version = data.get("latest_version")
    checked_at = data.get("checked_at")
    if not isinstance(latest_version, str) or not isinstance(checked_at, str):
        return None
    cached_at = _parse_timestamp(checked_at)
    if cached_at is None:
        return None
    if (now - cached_at).total_seconds() > ttl_seconds:
        return None
    return latest_version


def _write_cached_latest_version(path: Path, *, latest_version: str, checked_at: str) -> None:
    payload = {
        "checked_at": checked_at,
        "latest_version": latest_version,
        "source": PYPI_JSON_URL.format(package=PACKAGE_NAME),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def _version_key(value: str) -> tuple[int, ...] | None:
    normalized = value.strip().split("+", 1)[0]
    match = _VERSION_RE.match(normalized)
    if not match:
        return None
    release = [int(part) for part in match.group("release").split(".")]
    release = (release + [0, 0, 0])[:4]
    dev_n = match.group("dev_n")
    pre = match.group("pre")
    pre_n = match.group("pre_n")
    post_n = match.group("post_n")
    if dev_n is not None:
        phase = -4
        phase_number = int(dev_n)
    elif pre is not None:
        phase = {"a": -3, "b": -2, "rc": -1}[pre.lower()]
        phase_number = int(pre_n or 0)
    elif post_n is not None:
        phase = 1
        phase_number = int(post_n)
    else:
        phase = 0
        phase_number = 0
    return tuple(release + [phase, phase_number])


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
