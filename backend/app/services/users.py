"""Creating accounts (API sign-up, CLI, startup bootstrap) in one place, with the same password policy."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from ..security.passwords import hash_password, policy_problem
from ..security.rbac import Role

log = logging.getLogger("chakravyuh.users")


class UserError(ValueError):
    pass


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, email: str, password: str, role: str = Role.ANALYST) -> User:
    email = normalise_email(email)
    Role(role)                                   # raises ValueError for unknown roles
    problem = policy_problem(password, email)
    if problem:
        raise UserError(problem)
    if db.scalar(select(User).where(User.email == email)):
        raise UserError("An account with this email already exists")
    u = User(email=email, password_hash=hash_password(password), role=str(role), status="active")
    db.add(u)
    db.commit()
    return u


def bootstrap_admin(db: Session) -> None:
    """Create the first ADMIN from BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD if it doesn't exist.

    A weak or default password raises, so the API refuses to start rather than run with a known secret.
    An existing account is never modified here.
    """
    if settings.legacy_admin_api_key_set:
        log.warning("ADMIN_API_KEY is set but no longer used; admin access needs an ADMIN account")
    if not settings.bootstrap_admin_email:
        return
    email = normalise_email(settings.bootstrap_admin_email)
    problem = policy_problem(settings.bootstrap_admin_password, email)
    if problem:
        raise RuntimeError(f"BOOTSTRAP_ADMIN_PASSWORD rejected: {problem}")
    if db.scalar(select(User).where(User.email == email)):
        return
    create_user(db, email, settings.bootstrap_admin_password, Role.ADMIN)
    log.info("created bootstrap admin account %s", email)
