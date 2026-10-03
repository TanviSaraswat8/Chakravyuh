"""Roles and the permissions the API actually enforces.

Only permissions that some route checks are defined here; every one of them is enforced server-side by
`require_permission` in app/deps.py. Roles planned for later (RESEARCHER, SECURITY_ADMIN, SYSTEM_ADMIN)
are not defined yet because nothing would enforce them.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "VIEWER"                  # read own resources
    ANALYST = "ANALYST"                # create and use own sessions; review campaigns
    MODEL_ENGINEER = "MODEL_ENGINEER"  # analyst + run and persist defender adaptation; no security settings
    ADMIN = "ADMIN"                    # analyst + manage users/roles, read audit log and beta data


V, A, M, AD = Role.VIEWER, Role.ANALYST, Role.MODEL_ENGINEER, Role.ADMIN

PERMISSIONS: dict[str, frozenset[Role]] = {
    "sessions:read": frozenset({V, A, M, AD}),     # own sessions only (ownership checked per resource)
    "sessions:write": frozenset({A, M, AD}),       # create, add events, close, answer alerts (own only)
    "campaigns:manage": frozenset({A, M, AD}),     # recluster and approve/reject campaign cards
    "model:adapt": frozenset({M}),                 # swap the live defender in memory
    "model:persist": frozenset({M}),               # overwrite artifacts on disk (+ step-up)
    "users:manage": frozenset({AD}),               # list users, change role/status (+ step-up)
    "audit:read": frozenset({AD}),
    "beta:read": frozenset({AD}),                  # tester list and feedback
}

# Permissions that also need a password re-entry within REAUTH_WINDOW_SECONDS.
STEP_UP: frozenset[str] = frozenset({"model:persist", "users:manage"})

# Model changes are kept away from ADMIN on purpose (separation of duties): an admin who needs them
# assigns MODEL_ENGINEER to an account, which is itself an audited, step-up-protected role change.


def allowed(role: str, permission: str) -> bool:
    try:
        return Role(role) in PERMISSIONS.get(permission, frozenset())
    except ValueError:
        return False


def permissions_of(role: str) -> list[str]:
    return sorted(p for p in PERMISSIONS if allowed(role, p))
