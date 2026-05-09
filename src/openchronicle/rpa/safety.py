"""Provider-neutral RPA safety policy."""

from __future__ import annotations

from typing import Any

from .errors import RPASafetyError

REQUIRES_CONFIRMATION = {
    "payment",
    "order",
    "delete",
    "send_message",
    "login",
    "permission_grant",
}

BLOCKED_ACTIONS = {
    "adb_shell",
    "exec",
    "factory_reset",
    "install_apk",
    "rm",
    "raw_shell",
    "shell",
    "delete_file",
    "reset_device",
    "uninstall_app",
    "install_unknown_apk",
    "read_private_dir",
    "bulk_contacts",
    "bulk_sms",
    "bulk_photos",
}

HIGH_RISK_TERMS = {
    "pay": "payment",
    "payment": "payment",
    "checkout": "order",
    "order": "order",
    "delete": "delete",
    "remove": "delete",
    "send_message": "send_message",
    "sms": "send_message",
    "login": "login",
    "password": "login",
    "permission": "permission_grant",
}


def action_type(action: dict[str, Any]) -> str:
    return str(action.get("action") or action.get("type") or "").strip()


def assess_action(action: dict[str, Any]) -> dict[str, Any]:
    kind = action_type(action)
    text = " ".join(str(v).lower() for v in action.values() if isinstance(v, str))
    categories = set(action.get("safety_categories") or [])
    if kind in REQUIRES_CONFIRMATION:
        categories.add(kind)
    for term, category in HIGH_RISK_TERMS.items():
        if term in kind.lower() or term in text:
            categories.add(category)

    confirmed = bool(action.get("confirmed"))
    blocked = kind in BLOCKED_ACTIONS
    requires_confirmation = sorted(categories & REQUIRES_CONFIRMATION)
    allowed = not blocked and (not requires_confirmation or confirmed)
    risk = "high" if blocked or requires_confirmation else "low"
    reason = ""
    if blocked:
        reason = f"blocked dangerous RPA action: {kind}"
    elif requires_confirmation and not confirmed:
        reason = "action requires confirmation: " + ", ".join(requires_confirmation)
    return {
        "risk": risk,
        "confirmed": confirmed,
        "allowed": allowed,
        "requires_confirmation": requires_confirmation,
        "reason": reason,
    }


def assert_action_allowed(action: dict[str, Any]) -> dict[str, Any]:
    assessment = assess_action(action)
    if not assessment["allowed"]:
        raise RPASafetyError(assessment["reason"])
    return assessment
