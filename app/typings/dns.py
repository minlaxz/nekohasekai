from typing import TypedDict, List


class DNSServer(TypedDict):
    type: str
    tag: str


class DNS(TypedDict):
    servers: List[DNSServer]
