"""Today's autonomous-execution usage per merchant.

`merchant_policy_engine.evaluate_merchant_policy` stays a pure function --
it takes usage as a plain `(amount, count)` tuple rather than a db session,
so it remains unit-testable without a database exactly like before. This
module is the one place that reads and writes the real counter, and the
only place that increments it: `record_autonomous_transaction` is called
exactly once per real autonomous order, from `main.py`'s
`create_razorpay_test_order`, right after the order is actually created.

The increment is a single atomic upsert (`INSERT ... ON CONFLICT DO
UPDATE ... SET amount_used = amount_used + :amount`), not a read-modify-
write, so two concurrent autonomous orders for the same merchant on the
same day can never race each other into an inconsistent count -- the same
concurrency discipline already used for `MerchantApprovalDB`'s partial
unique index (see its comment in db/models.py).
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from backend.app.db.models import MerchantAutonomousUsageDB


def _today_utc():
    return datetime.now(timezone.utc).date()


def get_today_usage(db: Session, merchant_id: str) -> tuple[int, int]:
    row = db.execute(
        select(
            MerchantAutonomousUsageDB.amount_used,
            MerchantAutonomousUsageDB.transaction_count,
        ).where(
            MerchantAutonomousUsageDB.merchant_id == merchant_id,
            MerchantAutonomousUsageDB.usage_date == _today_utc(),
        )
    ).first()
    if row is None:
        return (0, 0)
    return (row.amount_used, row.transaction_count)


def record_autonomous_transaction(db: Session, merchant_id: str, amount: int) -> None:
    today = _today_utc()
    dialect_insert = postgresql.insert if db.bind.dialect.name == "postgresql" else sqlite.insert

    stmt = dialect_insert(MerchantAutonomousUsageDB).values(
        merchant_id=merchant_id,
        usage_date=today,
        amount_used=amount,
        transaction_count=1,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            MerchantAutonomousUsageDB.merchant_id,
            MerchantAutonomousUsageDB.usage_date,
        ],
        set_={
            "amount_used": MerchantAutonomousUsageDB.amount_used + amount,
            "transaction_count": MerchantAutonomousUsageDB.transaction_count + 1,
        },
    )
    db.execute(stmt)
    db.commit()
