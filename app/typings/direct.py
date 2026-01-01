from .common import CommonFields, DomainResolver


class ServerOutbound(CommonFields):
    domain_resolver: DomainResolver
