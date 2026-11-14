"""上行通道鉴权的端侧测试。

测的是**凭据真的被带上了**以及**鉴权失败与网络失败被区分开**。
"""

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.edge.transport import uplink as uplink_module
from core.edge.transport.uplink import UplinkAuthError, UplinkClient, UplinkError


@pytest.fixture
def spy_connect(monkeypatch):
    """替换上行模块里的 connect，记录每次调用的附加请求头。

    之所以替换**模块内的** connect 而不是 ``websockets.asyncio.client.connect``：
    上行模块用的是 ``from ... import connect``，持有的是函数对象的直接引用，
    替换包属性不会影响到它。

    @param monkeypatch pytest 夹具
    @return 记录列表
    """
    observed: list = []
    original = uplink_module.connect

    def spy(*args, **kwargs):
        observed.append(kwargs.get("additional_headers"))
        return original(*args, **kwargs)

    monkeypatch.setattr(uplink_module, "connect", spy)
    return observed


@pytest.mark.asyncio
async def test_token_is_sent_as_bearer_header(serve_echo, spy_connect):
    """凭据必须走请求头而不是 URL —— URL 会被记进访问日志。"""

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url, token="secret-token")
        await client.connect(DEFAULT_FORMAT)
        await client.close()

    assert spy_connect == [{"Authorization": "Bearer secret-token"}]


@pytest.mark.asyncio
async def test_no_token_means_no_auth_header(serve_echo, spy_connect):
    """不带凭据时不应发送空的身份头。"""

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.close()

    assert spy_connect == [{}]


@pytest.mark.asyncio
async def test_server_receives_the_bearer_header(serve_echo):
    """服务端确实收到了身份头 —— 客户端参数对了不等于线上带过去了。"""
    received_headers = []

    async def handler(connection):
        request = connection.request
        received_headers.append(dict(request.headers))
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url, token="secret-token")
        await client.connect(DEFAULT_FORMAT)
        await client.close()

    # HTTP 头名不区分大小写，websockets 侧统一小写。
    assert received_headers
    lowered = {key.lower(): value for key, value in received_headers[0].items()}
    assert lowered.get("authorization") == "Bearer secret-token"


@pytest.mark.asyncio
async def test_handshake_rejection_raises_auth_error_not_generic_error():
    """握手被拒（403）必须报鉴权错误，不能混成网络错误。

    两者要分开：网络断了可以降级继续跑，凭据错了必须让人去改配置。
    """

    class FakeResponse:
        status_code = 403

    class FakeHandshakeError(Exception):
        response = FakeResponse()

    client = UplinkClient(session_id="s-1", base_url="ws://127.0.0.1:1/x", token="bad")

    error = client._classify_connect_error(FakeHandshakeError())
    assert isinstance(error, UplinkAuthError)
    assert "403" in str(error)


@pytest.mark.asyncio
async def test_connection_refused_raises_generic_uplink_error():
    """连不上（无 HTTP 状态码）必须报普通上行错误。"""

    class FakeHandshakeError(Exception):
        response = None

    client = UplinkClient(session_id="s-1", base_url="ws://127.0.0.1:1/x")

    error = client._classify_connect_error(FakeHandshakeError())
    assert isinstance(error, UplinkError)
    assert not isinstance(error, UplinkAuthError)


@pytest.mark.asyncio
async def test_status_is_read_from_args_like_websockets_15():
    """websockets 15 把响应放在 args[0] 里，没有 response 属性。

    只认 response 属性的话，升级 websockets 后鉴权失败会被误判成网络失败，
    端侧就会静默降级到离线模式，而不是报"凭据错了"。
    """

    class FakeResponse:
        status_code = 401

    class FakeInvalidStatus(Exception):
        def __init__(self, response):
            super().__init__(response)

    client = UplinkClient(session_id="s-1", base_url="ws://127.0.0.1:1/x", token="bad")

    error = client._classify_connect_error(FakeInvalidStatus(FakeResponse()))
    assert isinstance(error, UplinkAuthError)
    assert "401" in str(error)


@pytest.mark.asyncio
async def test_status_401_is_recognised_as_auth_failure():
    """401 与 403 都算鉴权失败。"""

    class FakeResponse:
        status_code = 401

    class FakeInvalidStatus(Exception):
        def __init__(self, response):
            super().__init__(response)

    client = UplinkClient(session_id="s-1", base_url="ws://127.0.0.1:1/x", token="bad")

    error = client._classify_connect_error(FakeInvalidStatus(FakeResponse()))
    assert isinstance(error, UplinkAuthError)


@pytest.mark.asyncio
async def test_auth_error_message_does_not_leak_token():
    """异常消息不得包含凭据本身。"""

    class FakeResponse:
        status_code = 401

    class FakeHandshakeError(Exception):
        response = FakeResponse()

    client = UplinkClient(session_id="s-1", base_url="ws://127.0.0.1:1/x", token="leaked-value")

    error = client._classify_connect_error(FakeHandshakeError())
    assert "leaked-value" not in str(error)


def test_auth_error_is_a_kind_of_uplink_error():
    """鉴权错误仍是上行错误 —— 上层按 UplinkError 捕获时不会漏掉它。"""
    assert issubclass(UplinkAuthError, UplinkError)


@pytest.mark.asyncio
async def test_reconnect_also_sends_token(serve_echo, spy_connect):
    """重连必须继续带凭据，否则重连后会被拒。"""

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url, token="secret-token")
        await client.connect(DEFAULT_FORMAT)
        await client.reconnect()
        await client.close()

    assert len(spy_connect) == 2
    assert all(headers == {"Authorization": "Bearer secret-token"} for headers in spy_connect)
