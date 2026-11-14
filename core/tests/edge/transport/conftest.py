"""上行通道测试用的本地 WebSocket 服务夹具。"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable

import pytest
from websockets.asyncio.server import serve


@contextlib.asynccontextmanager
async def _serve_echo(handler: Callable[[object], object]) -> AsyncIterator[str]:
    """在随机端口起一个本地 WebSocket 服务。

    @param handler 连接处理协程
    @yield 服务地址（ws://127.0.0.1:<port>）
    """
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


@pytest.fixture
def serve_echo() -> Callable[[Callable[[object], object]], object]:
    """提供起本地 WebSocket 服务的上下文管理器。

    @return 上下文管理器工厂
    """
    return _serve_echo
