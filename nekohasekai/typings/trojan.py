from typing import List, NotRequired, Literal
from typings.common import CommonFields, ListenFields, NamePasswordUser, DailFields
from typings.multiplex import InboundMultiplex, OutboundMultiplex
from typings.tls import InboundTLSCertificate, ServerRealityTLS, ClientTLSInsecure


class InboundTrojan(CommonFields, ListenFields):
    users: List[NamePasswordUser]
    tls: InboundTLSCertificate | ServerRealityTLS
    multiplex: NotRequired[InboundMultiplex]


class OutboundTrojan(CommonFields, DailFields):
    password: str
    tls: ClientTLSInsecure
    multiplex: NotRequired[OutboundMultiplex]
    network: NotRequired[Literal["tcp", "udp"]]
