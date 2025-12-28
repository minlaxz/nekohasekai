from typing import Literal, TypedDict


class DomainResolver(TypedDict):
    server: str
    strategy: Literal["ipv4_only", "prefer_ipv4"]


class ServerOutbound(TypedDict):
    type: Literal["direct", "shadowsocks", "socks"]
    tag: str
    domain_resolver: DomainResolver
