from collections.abc import Callable

from dendroflow import database

from .models import ApplyItemResult, ApplyStageStatus


class StageTransactionError(RuntimeError):
    """Internal stage failure with its known transaction outcome.

    The original connection, execution, or commit error is retained
    through exception chaining. Rollback and close errors are retained
    separately.

    Items are reported only when commit was acknowledged.
    """

    def __init__(
        self,
        status: ApplyStageStatus,
        *,
        items: tuple[ApplyItemResult, ...] = (),
        rollback_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        super().__init__(
            f"stage transaction ended with status {status.value}"
        )
        self.status = status
        self.items = items
        self.rollback_error = rollback_error
        self.close_error = close_error


def run_write_stage(
    database_name: str,
    execute: Callable[[object], tuple[ApplyItemResult, ...]],
) -> tuple[ApplyItemResult, ...]:
    """Execute one write stage on a fresh owned connection.

    The callback must not manage transactions, close the connection,
    or change its autocommit setting.

    Ordinary failures raise StageTransactionError. A commit error
    remains UNKNOWN even if a subsequent rollback succeeds.

    Process-control exceptions propagate directly, with connection
    closure still attempted. There are no automatic retries.
    """
    try:
        connection = database.connect(database_name)
    except Exception as error:
        raise StageTransactionError(
            ApplyStageStatus.FAILED,
        ) from error

    status = ApplyStageStatus.FAILED
    items: tuple[ApplyItemResult, ...] = ()
    cause: Exception | None = None
    rollback_error: Exception | None = None
    close_error: Exception | None = None

    try:
        try:
            items = execute(connection)
        except Exception as error:  # noqa: BLE001 -- re-raised below with stage outcome
            cause = error
        else:
            # Until commit returns successfully, its outcome is uncertain.
            status = ApplyStageStatus.UNKNOWN

            try:
                connection.commit()
            except Exception as error:  # noqa: BLE001 -- re-raised below with stage outcome
                cause = error
            else:
                status = ApplyStageStatus.COMMITTED

        if cause is not None:
            try:
                connection.rollback()
            except Exception as error:  # noqa: BLE001 -- retained as rollback error
                rollback_error = error
                status = ApplyStageStatus.UNKNOWN
    finally:
        try:
            connection.close()
        except Exception as error:  # noqa: BLE001 -- retained as close error
            close_error = error

    if cause is not None or close_error is not None:
        primary_error = cause if cause is not None else close_error

        raise StageTransactionError(
            status,
            items=(
                items
                if status == ApplyStageStatus.COMMITTED
                else ()
            ),
            rollback_error=rollback_error,
            close_error=close_error,
        ) from primary_error

    return items

