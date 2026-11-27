"""Operational CLI: migrate, sync-catalog, seed-plans, bootstrap super admin, export contracts.

Usage: python -m app.cli <command> [options]
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import DbScope, dispose_engine, unit_of_work
from app.core.security import hash_password
from app.domain import constants
from app.domain.capabilities import ALL_CAPABILITIES, CAPABILITIES, CATALOG_VERSION
from app.models import CapabilityCatalog, CapabilityDependency, Plan, PlanCapability, User

# Illustrative launch packages (§11). Prices in paise; Enterprise is custom-priced.
DEFAULT_PLANS: list[dict] = [
    {
        "code": "assistant-free",
        "name": "Assistant Free",
        "product": "assistant",
        "price_minor": 0,
        "caps": {"assistant.text": {"monthly": 300}, "assistant.memory": {}, "assistant.identity": {}},
    },
    {
        "code": "assistant-plus",
        "name": "Assistant Plus",
        "product": "assistant",
        "price_minor": 49_900,
        "caps": {
            "assistant.text": {"monthly": 3000},
            "assistant.voice": {"monthly": 36_000},
            "assistant.memory": {},
            "assistant.memory.write": {},
            "assistant.research": {"monthly": 300},
            "assistant.identity": {},
        },
    },
    {
        "code": "assistant-pro",
        "name": "Assistant Pro",
        "product": "assistant",
        "price_minor": 99_900,
        "caps": {
            "assistant.text": {"monthly": 10_000},
            "assistant.voice": {"monthly": 108_000},
            "assistant.memory": {},
            "assistant.memory.write": {},
            "assistant.research": {"monthly": 1500},
            "assistant.identity": {},
            "assistant.handsfree": {},
        },
    },
    {
        "code": "voice-starter",
        "name": "Voice Starter",
        "product": "voice",
        "price_minor": 299_900,
        "caps": {
            "assistant.text": {},
            "voice.agents": {},
            "voice.inbound": {"monthly": 500},
            "voice.crm": {},
            "assistant.identity": {},
        },
    },
    {
        "code": "voice-business",
        "name": "Voice Business",
        "product": "voice",
        "price_minor": 999_900,
        "caps": {
            "assistant.text": {},
            "assistant.identity": {},
            "voice.agents": {},
            "voice.inbound": {"monthly": 3000},
            "voice.outbound": {"monthly": 3000},
            "voice.crm": {},
            "voice.appointments": {},
            "connect.embed": {},
            "connect.analytics": {},
        },
    },
    {
        "code": "enterprise-custom",
        "name": "Enterprise (custom)",
        "product": "custom",
        "price_minor": 0,
        "caps": {c.key: {} for c in ALL_CAPABILITIES if c.purchasable},
    },
]


async def sync_catalog() -> None:
    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        existing = {c.key: c for c in (await db.scalars(select(CapabilityCatalog))).all()}
        for c in ALL_CAPABILITIES:
            row = existing.get(c.key)
            if row is None:
                db.add(
                    CapabilityCatalog(
                        key=c.key,
                        requirement_id=c.requirement_id,
                        module=c.module,
                        product=c.product.value,
                        description=c.description,
                        quota_metric=c.quota_metric,
                        purchasable=c.purchasable,
                        active=True,
                        version=CATALOG_VERSION,
                    )
                )
            else:
                row.description, row.quota_metric, row.purchasable, row.active = (
                    c.description,
                    c.quota_metric,
                    c.purchasable,
                    True,
                )
        # Keys removed from code are deactivated, never deleted (stable identifiers, §29.1).
        for key, row in existing.items():
            if key not in CAPABILITIES:
                row.active = False
        await db.flush()
        await db.execute(delete(CapabilityDependency))
        for c in ALL_CAPABILITIES:
            for d in c.dependencies:
                db.add(CapabilityDependency(capability_key=c.key, depends_on=d))
    print(f"catalog synced: {len(ALL_CAPABILITIES)} capabilities")


async def seed_plans() -> None:
    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        for p in DEFAULT_PLANS:
            if await db.scalar(select(Plan.id).where(Plan.code == p["code"])):
                continue
            plan = Plan(
                code=p["code"],
                version=1,
                name=p["name"],
                product=p["product"],
                price_minor=p["price_minor"],
                currency="INR",
                limits={},
            )
            db.add(plan)
            await db.flush()
            for key, limits in p["caps"].items():
                db.add(PlanCapability(plan_id=plan.id, capability_key=key, enabled=True, limits=limits))
    print("default plans present")


async def create_super_admin(email: str, display_name: str) -> None:
    """One-time bootstrap (§32.1). Refuses if any super admin exists. MFA must be enrolled at first login."""
    password = os.environ.get("KOKILA_BOOTSTRAP_PASSWORD") or getpass.getpass("Super admin password: ")
    if len(password) < 16:
        sys.exit("password must be at least 16 characters")
    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        if await db.scalar(select(User.id).where(User.platform_role == constants.PlatformRole.SUPER_ADMIN)):
            sys.exit("a super admin already exists; bootstrap refused")
        existing = await db.scalar(select(User).where(User.email == email.lower()))
        if existing:
            existing.platform_role = constants.PlatformRole.SUPER_ADMIN
        else:
            db.add(
                User(
                    email=email.lower(),
                    password_hash=hash_password(password),
                    display_name=display_name,
                    platform_role=constants.PlatformRole.SUPER_ADMIN,
                    email_verified_at=datetime.now(UTC),
                )
            )
    print("super admin created; enrol MFA via POST /v1/auth/mfa/enroll before platform login")


def export_contracts(out: Path) -> None:
    """Generate TypeScript constants from the canonical Python registry (§29.1)."""
    enums = {
        name: [m.value for m in obj]
        for name, obj in vars(constants).items()
        if isinstance(obj, type) and issubclass(obj, constants.StrEnum) and obj is not constants.StrEnum
    }
    caps = [
        {
            "key": c.key,
            "requirementId": c.requirement_id,
            "module": c.module,
            "dependencies": list(c.dependencies),
            "purchasable": c.purchasable,
            "description": c.description,
        }
        for c in ALL_CAPABILITIES
    ]
    lines = ["// GENERATED by `python -m app.cli export-contracts`. Do not edit by hand.", ""]
    for name, values in sorted(enums.items()):
        lines.append(
            f"export const {name} = {json.dumps({v.upper().replace('.', '_').replace('-', '_'): v for v in values}, ensure_ascii=False)} as const;"
        )
        lines.append(f"export type {name} = (typeof {name})[keyof typeof {name}];")
    lines.append(f"export const CAPABILITIES = {json.dumps(caps, indent=2, ensure_ascii=False)} as const;")
    lines.append(f'export const API_PREFIX = "{constants.API_PREFIX}";')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="kokila")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-catalog")
    sub.add_parser("seed-plans")
    sub.add_parser("bootstrap", help="sync catalog + seed default plans (run after alembic upgrade)")
    sa = sub.add_parser("create-super-admin")
    sa.add_argument("--email", required=True)
    sa.add_argument("--name", default="Manima Super Admin")
    ec = sub.add_parser("export-contracts")
    ec.add_argument("--out", default="../../apps/web/src/lib/contracts.generated.ts")
    args = ap.parse_args()

    async def run() -> None:
        try:
            if args.cmd == "sync-catalog":
                await sync_catalog()
            elif args.cmd == "seed-plans":
                await seed_plans()
            elif args.cmd == "bootstrap":
                await sync_catalog()
                await seed_plans()
            elif args.cmd == "create-super-admin":
                await create_super_admin(args.email, args.name)
        finally:
            await dispose_engine()

    if args.cmd == "export-contracts":
        export_contracts(Path(args.out))
    else:
        asyncio.run(run())


if __name__ == "__main__":
    main()
