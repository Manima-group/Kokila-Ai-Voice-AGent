"""Operational CLI.

python -m app.cli create-superadmin --email ops@manima.co.in   (password from SUPERADMIN_PASSWORD env)
python -m app.cli seed-dev                                      (development only; clearly labelled demo data)
"""

import argparse
import os
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal


def create_superadmin(email: str) -> None:
    from app.tenants.models import User

    password = os.environ.get("SUPERADMIN_PASSWORD", "")
    if len(password) < 12:
        sys.exit("Set SUPERADMIN_PASSWORD (>= 12 chars) in the environment")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user:
            user.is_superadmin = True
            user.password_hash = hash_password(password)
        else:
            db.add(User(email=email.lower(), full_name="Platform Admin", password_hash=hash_password(password), is_superadmin=True))
        db.commit()
    print(f"Super admin ready: {email}")


def seed_dev() -> None:
    from app.billing.models import Plan

    if get_settings().environment not in ("development", "test"):
        sys.exit("seed-dev is only allowed in development")
    demo_plans = [  # DEMO pricing for local development only. Real pricing is configured by the Super Admin.
        ("dev_starter", "[DEV] Starter", 299900, 500, 2, 2, 5),
        ("dev_growth", "[DEV] Growth", 999900, 2000, 5, 5, 15),
    ]
    with SessionLocal() as db:
        for code, name, price, minutes, agents, conc, users in demo_plans:
            if not db.scalar(select(Plan).where(Plan.code == code)):
                db.add(
                    Plan(
                        code=code,
                        name=name,
                        price_minor=price,
                        included_minutes=minutes,
                        max_agents=agents,
                        max_concurrent_calls=conc,
                        max_users=users,
                        features={"outbound": True, "calendar": True, "integrations": True},
                    )
                )
        db.commit()
    print("Development plans seeded (labelled [DEV]).")


def main() -> None:
    p = argparse.ArgumentParser(prog="kokila")
    sub = p.add_subparsers(dest="cmd", required=True)
    sa = sub.add_parser("create-superadmin")
    sa.add_argument("--email", required=True)
    sub.add_parser("seed-dev")
    args = p.parse_args()
    if args.cmd == "create-superadmin":
        create_superadmin(args.email)
    elif args.cmd == "seed-dev":
        seed_dev()


if __name__ == "__main__":
    main()
