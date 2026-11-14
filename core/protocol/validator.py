"""协议消息的统一校验入口。

所有需要校验协议消息的地方都走这里，而不是直接
``Draft202012Validator(load_schema(name))`` —— 后者遇到相对引用会去网络上
拉取 schema，离线环境下校验直接失败。

新增 schema 时的唯一动作：在 ``core/protocol/loader.py`` 的 ``SCHEMA_NAMES``
里加一行；其余（注册表、样例、跨语言一致性测试）自动跟上。
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

from core.protocol.loader import build_registry, load_schema


def build_validator(name: str) -> Draft202012Validator:
    """构造一份绑定了本地注册表的校验器。

    @param name schema 名
    @return 校验器
    @throws KeyError schema 名未知时抛出
    """
    schema = load_schema(name)
    return Draft202012Validator(schema, registry=build_registry())


def validation_errors(name: str, payload: dict) -> list[str]:
    """校验一条消息并返回错误列表。

    @param name schema 名
    @param payload 消息载荷
    @return 错误列表，空列表表示通过
    @throws KeyError schema 名未知时抛出
    """
    validator = build_validator(name)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    messages = []
    for error in errors:
        field = ".".join(str(part) for part in error.absolute_path) or "(根)"
        messages.append(f"字段 {field}：{error.message}")
    return messages
