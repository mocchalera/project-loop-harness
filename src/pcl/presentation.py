from __future__ import annotations

import json


def to_pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def impact_text_payload(impact: dict) -> tuple[dict, str | None]:
    display = dict(impact)
    excluded = display.pop("excluded_changed_files", [])
    display["excluded_changed_file_count"] = len(excluded)
    if not excluded:
        return display, None
    paths = [str(item.get("path", "")) for item in excluded if item.get("path")]
    visible = ", ".join(paths[:5])
    if len(paths) > 5:
        visible += f", ... (+{len(paths) - 5} more)"
    return display, f"Excluded changed files: {len(excluded)} ({visible})"


def format_context_check_summary(payload: dict) -> str:
    target = payload["target"]
    bound = payload["target_bound_code_context"]
    lines = [
        f"Context check: {target['type']} {target['id']}",
        f"Target-bound code context: {bound['status']}",
    ]
    receipt_ref = bound.get("receipt_ref")
    if isinstance(receipt_ref, dict):
        lines.append(
            f"Receipt: {receipt_ref.get('evidence_id', '')} ({receipt_ref.get('created_at', '')})"
        )
    lines.append(f"Supporting evidence: {payload['supporting_evidence_count']}")
    master_trace_context = payload.get("master_trace_context")
    if isinstance(master_trace_context, dict):
        lines.append(f"Master trace context: {master_trace_context.get('status', '')}")
    lines.append(f"Canonical pack command: {payload['canonical_context_pack_command']}")
    refresh_command = payload.get("recommended_refresh_command")
    if refresh_command:
        lines.append(f"Recommended refresh command: {refresh_command}")
    lines.extend(f"WARNING: {warning}" for warning in payload.get("warnings", []))
    return "\n".join(lines)


def format_next_explanation(action: dict) -> str:
    command = action.get("command") or "-"
    lines = [
        f"Next action: {action.get('type', '')}",
        f"Priority: {action.get('priority', '')}",
        f"Blocking: {yes_no(bool(action.get('blocking')))}",
        f"Requires human: {yes_no(bool(action.get('requires_human')))}",
        f"Safe to run: {yes_no(bool(action.get('safe_to_run')))}",
        f"Run policy: {action.get('run_policy', '')}",
        f"Human guidance: {action.get('human_guidance', '')}",
        f"Reason: {action.get('reason', '')}",
        f"Command: {command}",
        f"Expected after: {action.get('expected_after', '')}",
    ]
    target = action.get("target")
    if isinstance(target, dict) and target.get("id"):
        lines.append(f"Target: {target['id']}")
    if isinstance(target, dict) and isinstance(target.get("candidates"), list):
        lines.append("Candidates:")
        for candidate in target["candidates"]:
            if isinstance(candidate, dict):
                lines.append(
                    "- "
                    + " ".join(
                        str(candidate.get(key, ""))
                        for key in ("id", "status", "title")
                        if candidate.get(key)
                    )
                )
    return "\n".join(lines)


def format_finish_summary(payload: dict) -> str:
    target = payload["target"]
    lines = [
        f"Finish target: run={target['run'] or '-'} goal={target['goal'] or '-'}",
        f"Finished: {yes_no(bool(payload['finished']))}",
    ]
    steps = payload["remaining_steps"]
    if steps:
        lines.append("Remaining steps:")
        for index, step in enumerate(steps, start=1):
            lines.append(
                f"{index}. {step['command']} "
                f"(requires_human={yes_no(bool(step['requires_human']))}, "
                f"safe_to_run={yes_no(bool(step['safe_to_run']))})"
            )
    else:
        lines.append("Remaining steps: none")
    if "executed" in payload:
        executed = payload["executed"]
        if executed:
            lines.append("Executed:")
            for item in executed:
                lines.append(f"- {item['command']}: {'ok' if item['ok'] else 'failed'}")
        else:
            lines.append("Executed: none")
        lines.append(f"Changed: {yes_no(bool(payload['changed']))}")
    return "\n".join(lines)


def format_start_summary(payload: dict) -> str:
    result = payload["result"]
    lines = [
        f"Start status: {payload['status']}",
        f"Mutated: {yes_no(bool(payload['mutated']))}",
        f"Intent: {result['intent']}",
    ]
    target = result.get("target")
    if isinstance(target, dict) and target.get("id"):
        lines.append(f"Target: {target['type']} {target['id']}")
    initialization = result.get("initialization")
    if isinstance(initialization, dict):
        lines.append("Initialization plan:")
        for change in initialization.get("changes", []):
            lines.append(f"- {change['action']}: {change['path']} ({change['reason']})")
    for warning in payload["warnings"]:
        lines.append(f"WARNING: {warning}")
    if payload["next_actions"]:
        action = payload["next_actions"][0]
        lines.append(f"Next: {action['text']}")
        if action["command"]:
            lines.append(f"Run: {action['command']}")
    return "\n".join(lines)


def yes_no(value: bool) -> str:
    return "yes" if value else "no"
