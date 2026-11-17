"""Role → permission mapping. Enforced server-side on every tenant endpoint."""

from enum import StrEnum


class Role(StrEnum):
    COMPANY_ADMIN = "COMPANY_ADMIN"
    MANAGER = "MANAGER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


READ = {
    "agents:read",
    "phone_numbers:read",
    "contacts:read",
    "leads:read",
    "campaigns:read",
    "calls:read",
    "appointments:read",
    "analytics:read",
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: set(READ),
    Role.OPERATOR: READ
    | {
        "leads:write_assigned",
        "contacts:write",
        "appointments:write",
        "calls:transcript",
        "calls:handoff",
    },
    Role.MANAGER: READ
    | {
        "leads:write",
        "leads:assign",
        "contacts:write",
        "contacts:import",
        "consent:write",
        "campaigns:write",
        "campaigns:control",
        "appointments:write",
        "calls:transcript",
        "calls:handoff",
        "agents:test",
        "users:read",
    },
    Role.COMPANY_ADMIN: READ
    | {
        "leads:write",
        "leads:assign",
        "contacts:write",
        "contacts:import",
        "contacts:delete",
        "consent:write",
        "campaigns:write",
        "campaigns:control",
        "appointments:write",
        "calls:transcript",
        "calls:handoff",
        "agents:write",
        "agents:publish",
        "agents:test",
        "phone_numbers:write",
        "integrations:read",
        "integrations:write",
        "billing:read",
        "billing:write",
        "users:read",
        "users:write",
        "tenant:write",
        "audit:read",
        "retention:write",
    },
}


def has_permission(role: str, permission: str) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
