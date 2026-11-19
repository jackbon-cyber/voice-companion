"""端到端脚本的记忆状态归零。

为什么需要它
------------
端到端断言会用两个固定的用户标识（``e2e-user-a`` / ``e2e-user-b``），
云端据此把记忆写进对应作用域。**上一轮跑完留下的记忆会留在作用域里**，
于是第二轮的断言是在一个有历史包袱的状态上跑的。

这不是"测试有点脏"的问题，而是会**直接改变结论**的问题：

* 用户 B 的作用域里残留着上一轮的记忆，召回列表第一条可能不再是本轮写的；
* 泄漏检测项断言"B 的回复不含 A 的事实"——
  若上一轮恰好在 B 的作用域里留下了与 A 同名的事实，
  这一项会**因为状态残留而失败**，而失败原因与隔离机制本身无关；
* 反过来，若残留内容的文字不同，这一项会**因为状态残留而通过**，
  而通过原因与隔离机制本身也无关。

也就是说：**残留让断言的结论与被测机制脱钩**。
唯一能保证结论可信的办法，是每次跑之前把状态归零。

做法
----
用 Chroma 的 REST 接口按作用域删除记录。
删除条件里**只带作用域元数据**，不带其它条件 ——
它只会删掉本脚本自己的作用域，绝不波及生产数据或评测作用域。

之所以不走 ChromaDB 客户端库：端到端脚本要能只靠标准库跑起来，
少一个依赖就少一处环境问题。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

# Chroma v2 的租户与数据库名，与云端 application.yml 的默认值一致。
DEFAULT_TENANT = "default_tenant"
DEFAULT_DATABASE = "default_database"

# 长期记忆集合名，与云端 ChromaProperties 的默认值一致。
DEFAULT_COLLECTION = "mem_longterm"

# 记忆作用域里的租户标识。
#
# **注意区分两个"租户"**：上面那个是 Chroma 服务自己的租户
# （数据隔离的物理边界），这一个是指��在记忆记录元数据里的作用域租户
# （业务侧的隔离标识）。云端用的是后者，取值固定为 "default"，
# 与 MemoryScope.DEFAULT_TENANT_ID 一致。
SCOPE_TENANT = "default"

# 超时秒数。Chroma 在本地运行，这个值只需覆盖最坏情况的冷启动。
REQUEST_TIMEOUT_SECONDS = 15.0


class MemoryResetError(RuntimeError):
    """记忆归零失败。"""


@dataclass
class ChromaEndpoint:
    """Chroma 服务的定位信息。

    :param base_url: 服务基址，不含 /api/v2 路径片段
    :param tenant: 租户名
    :param database: 数据库名
    :param collection: 集合名
    """

    base_url: str
    tenant: str = DEFAULT_TENANT
    database: str = DEFAULT_DATABASE
    collection: str = DEFAULT_COLLECTION

    def collections_url(self) -> str:
        """返回集合列表地址。

        :return: 集合列表的完整地址
        """
        return (
            f"{self.base_url}/api/v2/tenants/{self.tenant}"
            f"/databases/{self.database}/collections"
        )


def _request_json(
    url: str, payload: dict[str, object] | None = None, method: str = "POST"
) -> object:
    """发起一次 JSON 请求。

    :param url: 目标地址
    :param payload: 请求体；为 None 时不发请求体
    :param method: HTTP 方法
    :return: 解析后的响应
    :raises MemoryResetError: 请求失败或响应无法解析时抛出
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise MemoryResetError(f"Chroma 请求失败（HTTP {error.code}）：{url}") from error
    except OSError as error:
        raise MemoryResetError(f"Chroma 不可达：{url} —— {error}") from error

    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise MemoryResetError(f"Chroma 响应不是合法 JSON：{url}") from error


def resolve_collection_id(endpoint: ChromaEndpoint) -> str:
    """查出集合的 id。

    :param endpoint: Chroma 定位信息
    :return: 集合 id
    :raises MemoryResetError: 集合不存在时抛出
    """
    payload = _request_json(endpoint.collections_url(), method="GET")
    if not isinstance(payload, list):
        raise MemoryResetError("Chroma 集合列表响应不是数组")
    for item in payload:
        if isinstance(item, dict) and item.get("name") == endpoint.collection:
            collection_id = item.get("id")
            if isinstance(collection_id, str):
                return collection_id
    raise MemoryResetError(f"Chroma 集合不存在：{endpoint.collection}")


def clear_scope(endpoint: ChromaEndpoint, owner_key: str) -> int:
    """清空指定主体的全部长期记忆（含已归档记录）。

    :param endpoint: Chroma 定位信息
    :param owner_key: 主体标识
    :return: 被删除的记录数
    :raises MemoryResetError: 删除失败时抛出
    """
    collection_id = resolve_collection_id(endpoint)
    collection_url = f"{endpoint.collections_url()}/{collection_id}"

    # 删除条件只按作用域过滤，不带 archived 条件 ——
    # 带上的话归档记录会残留下来，记录总数持续增长，"已清空"就成了假象。
    #
    # **条件必须写成 $and 的形式**：Chroma v2 不接受顶层并列的两个字段，
    # 会返回 400 "Invalid where clause"。这一点是实测踩出来的 ——
    # 写成 {"scope_tenant": {...}, "scope_owner": {...}} 会被服务端拒绝。
    where = {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": owner_key}},
        ]
    }
    result = _request_json(f"{collection_url}/delete", {"where": where})
    if not isinstance(result, dict):
        return 0
    deleted = result.get("deleted")
    return deleted if isinstance(deleted, int) else 0


def clear_scopes(endpoint: ChromaEndpoint, owner_keys: list[str]) -> dict[str, int]:
    """清空多个主体的长期记忆。

    :param endpoint: Chroma 定位信息
    :param owner_keys: 主体标识列表
    :return: 主体标识到删除条数的映射
    :raises MemoryResetError: 任意一次删除失败时抛出
    """
    return {owner: clear_scope(endpoint, owner) for owner in owner_keys}
