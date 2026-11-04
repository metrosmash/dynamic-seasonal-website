from __future__ import annotations

from dataclasses import dataclass


class JsNotEnabled(PermissionError):
    pass


class JsNotImplemented(NotImplementedError):
    pass


@dataclass(frozen=True)
class JsResult:
    value: str = ""
    logs: tuple[str, ...] = ()


MAX_JS_CHARS = 2000


def run_js(config: dict, harness_name: str, code: str) -> JsResult:
    """Extension point for the full-JS sandbox (disabled by default).

    v1 keeps the agent on DOM+CSS tools. When ``HARNESS_ALLOW_JS=1`` the call
    is admitted here but still refused until a Browserbase CDP executor lands:
    arbitrary JS must only ever run inside the isolated session with network
    disabled, never in the app process. This function is where that executor
    plugs in; fail closed until then.
    """
    del harness_name
    if not config.get("HARNESS_ALLOW_JS"):
        raise JsNotEnabled(
            "JS execution is disabled. Set HARNESS_ALLOW_JS=1 to admit it, "
            "and only with an isolated Browserbase session."
        )
    if not code or len(code) > MAX_JS_CHARS:
        raise ValueError("JS snippet must be 1-2000 characters.")
    raise JsNotImplemented(
        "No JS executor is installed yet. Implement the Browserbase CDP "
        "executor behind this function before enabling agent JS."
    )
