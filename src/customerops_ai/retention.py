"""Explicit operator-run memory retention. No scheduler or destructive import-time behavior."""

import argparse
import asyncio

from sqlalchemy.exc import SQLAlchemyError

from customerops_ai.core.config import Settings
from customerops_ai.infrastructure.database import Database
from customerops_ai.services.retention import RetentionResult, RetentionService


async def purge(batch_size: int) -> RetentionResult:
    settings = Settings()
    if settings.database_password is None:
        raise SystemExit("Set CUSTOMEROPS_DATABASE_PASSWORD before applying retention.")
    database = Database(settings)
    total = RetentionResult()
    try:
        async with database.sessions() as session:
            service = RetentionService(session, settings)
            cursor = None
            while True:
                result, cursor = await service.purge_batch(cursor, batch_size)
                total.customers_processed += result.customers_processed
                total.messages_deleted += result.messages_deleted
                total.conversations_deleted += result.conversations_deleted
                total.summaries_cleared += result.summaries_cleared
                if cursor is None:
                    break
    except (SQLAlchemyError, OSError, TimeoutError):
        raise SystemExit(
            "Retention failed; completed batches remain committed. "
            "Retry after checking database availability."
        ) from None
    finally:
        await database.close()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Delete expired conversation data using configured retention windows",
    )
    parser.add_argument(
        "--batch-size", type=int, choices=range(1, 101), default=50, metavar="1..100"
    )
    args = parser.parse_args()
    print(asyncio.run(purge(args.batch_size)).model_dump_json())


if __name__ == "__main__":
    main()
