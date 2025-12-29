from typing import List, NotRequired, Literal
from typings.common import CommonFields, ListenFields, NamePasswordUser, DailFields
from typings.multiplex import InboundMultiplex, OutboundMultiplex
from typings.tls import InboundTlsCertificate, OutboundTlsCertificate


class InboundTrojan(CommonFields, ListenFields):
    users: List[NamePasswordUser]
    tls: InboundTlsCertificate
    multiplex: NotRequired[InboundMultiplex]


class OutboundTrojan(CommonFields, DailFields):
    password: str
    tls: OutboundTlsCertificate
    multiplex: NotRequired[OutboundMultiplex]
    network: NotRequired[Literal["tcp", "udp"]]
