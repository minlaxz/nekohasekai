from typing import Literal, List
from typings.common import CommonFields, ListenFields, DailFields
from typings.tls import Handshake, ClientTLSInsecure
from typings.common import NamePasswordUser


class InboundShadowTLS(CommonFields, ListenFields):
    version: Literal[1, 2, 3]
    users: List[NamePasswordUser]
    handshake: Handshake


class OutboundShadowTLS(CommonFields, DailFields):
    version: Literal[1, 2, 3]
    password: str
    tls: ClientTLSInsecure
