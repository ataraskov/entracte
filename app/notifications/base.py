from typing import Protocol


class Notifier(Protocol):
    async def send(self, title: str, body: str) -> None: ...
