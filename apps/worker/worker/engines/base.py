"""EngineAdapter Protocol (Phase 3).

A Protocol, not an ABC (no repository convention requires ABC, and a
Protocol is the smaller commitment — any object with a matching
`execute` method satisfies this, no inheritance required).

An EngineAdapter must not know about FastAPI, AsyncSession, ORM
objects, HTTP request/response objects from the API layer, or
authorization. Its entire world is one `ExecutionContext` in, one
`ExecutionResult` out.
"""

from typing import Protocol

from worker.core.execution import ExecutionContext, ExecutionResult


class EngineAdapter(Protocol):
    async def execute(self, context: ExecutionContext) -> ExecutionResult: ...
