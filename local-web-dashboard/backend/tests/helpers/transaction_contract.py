from backend.app.services.transaction import (
    assert_remote_call_allowed,
    current_transaction_marker,
)


class TransactionGuardedFakeAgentClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, operation: str = "fake agent execute") -> dict[str, object]:
        assert_remote_call_allowed(operation)
        marker = current_transaction_marker()
        call = {
            "operation": operation,
            "active_transaction": marker.active,
            "commit_sequence": marker.commit_sequence,
        }
        self.calls.append(call)
        return call
