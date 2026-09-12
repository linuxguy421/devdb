import secrets
import string
from typing import List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecoveryCode, User


def generate_code() -> str:
    chars = "".join(
        c for c in string.ascii_uppercase + string.digits if c not in "0O1IL"
    )
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    return f"{part1}-{part2}"


async def generate_user_recovery_codes(
    db: AsyncSession,
    user_id: int,
    count: int = 8,
) -> List[str]:
    from app.routers.auth import get_password_hash

    await db.execute(
        delete(RecoveryCode).where(RecoveryCode.user_id == user_id)
    )

    raw_codes = []
    for _ in range(count):
        raw_code = generate_code()
        raw_codes.append(raw_code)

        db_code = RecoveryCode(
            user_id=user_id,
            code_hash=get_password_hash(raw_code),
            is_used=False,
        )
        db.add(db_code)

    await db.commit()
    return raw_codes


async def verify_and_consume_code(
    db: AsyncSession,
    user: User,
    raw_code: str,
) -> bool:
    from app.routers.auth import verify_password

    stmt = select(RecoveryCode).where(
        RecoveryCode.user_id == user.id,
        RecoveryCode.is_used == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    active_codes = result.scalars().all()

    clean_code = raw_code.strip().upper()

    for db_code in active_codes:
        if verify_password(clean_code, db_code.code_hash):
            db_code.is_used = True
            await db.commit()
            return True

    return False
