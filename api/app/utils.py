from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import re
import logging
import os
import time
import urllib.parse
from typing import Any, Callable, Dict, List

import anyio
import httpx
from fastapi import HTTPException

from app import ssm_api, store

# -------------------------------------------------------------------
# Environment & Constants
# -------------------------------------------------------------------

APP_CLIENT_DIR = os.getenv("APP_INTERNAL_CLIENT_DIR", "/sing-box/client")
APP_DEFAULT_QUOTA_IN_BYTES = int(os.getenv("APP_DEFAULT_QUOTA_IN_BYTES", "30000000000"))
APP_TS_CONTROL_URL = os.getenv("APP_TS_CONTROL_URL", "")
HTTP_TIMEOUT = 5  # seconds

# Client template sections, one `<name>.json` each, in Profile config order.
TEMPLATE_SECTIONS = (
    "log", "dns", "outbounds", "inbounds", "experimental", "services", "route", "http_clients", "endpoints",
)
MESH_ENDPOINT_TAG = "ts-ep"
MESH_DNS_TAG = "dns-mesh"  # tailscale DNS server: resolves MagicDNS names via ts-ep
WARP_ENDPOINT_TAG = "warp-ep"
FULL_MODE = "Full"  # clash_mode that proxies everything; admin-only
# User rule set fetch limits: fixed hosts keep the API from reaching internal services (SSRF).
USER_RULES_HOSTS = ("gist.githubusercontent.com", "raw.githubusercontent.com")
USER_RULES_MAX_BYTES = 64 * 1024
PROXY_OUTBOUND = "shadowsocks-uot"

logger = logging.getLogger(__name__)


# A user's `k`: 20 base64 characters plus `==`. It is not a valid SS-2022 key by itself.
K_PATTERN = re.compile(r"^[A-Za-z0-9+/]{20}==$")
SS_METHOD = "2022-blake3-aes-128-gcm"


def ssm_key(k: str) -> str:
    """The SS-2022 user key for a `k` (#24): drop `==`, append the first 4 characters.
    24 base64 characters, 18 bytes; sing-box hashes keys longer than 16 bytes down to 16.
    `k` stays what the user holds; this is what ssm-api and the client outbounds get."""
    if not K_PATTERN.match(k):
        raise ValueError("PSK must be 20 base64 characters followed by '=='")
    key = k[:-2] + k[:4]
    assert len(base64.b64decode(key, validate=True)) == 18
    return key


def client_key(k: str) -> str:
    """The key the client outbounds get for a `k` (#24). sing-box's server (sing-shadowsocks) reduces
    the 18-byte ssm_key to 16 bytes with SHA-256; its client (sing-shadowsocks2) takes exactly
    16 bytes and nothing else, so the API applies the same reduction (verified, sing-box 1.14.2)."""
    raw = base64.b64decode(ssm_key(k))
    return base64.b64encode(hashlib.sha256(raw).digest()[:16]).decode()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def user_entry(username: str) -> Dict[str, Any]:
    """The user's User record; {} when absent."""
    return store.get(username) or {}


def apply_full_mode(route: Dict[str, Any], admin: bool) -> None:
    """Full mode (proxy everything) is admin-only: strip its route rules for
    everyone else so the mode is a no-op in their dashboard. Mutates `route`."""
    if not admin:
        route["rules"] = [
            r for r in route.get("rules", []) if r.get("clash_mode") != FULL_MODE
        ]


def apply_rules_detour(route: Dict[str, Any], http_client: str) -> None:
    """Download every remote rule set through the top-level HTTP client tagged
    `http_client` (`proxy` or `direct` in the template). Mutates `route`."""
    route["default_http_client"] = http_client


def apply_mesh(
    endpoints: List[Dict[str, Any]],
    route: Dict[str, Any],
    dns: Dict[str, Any],
    username: str,
    key: str,
    control_url: str,
) -> List[Dict[str, Any]]:
    """Fill the Mesh endpoint for a user with a Mesh key; strip it (and every
    route rule, DNS server and DNS rule pointing at it) for a user without one.
    Mutates `route` and `dns`."""
    if not key:
        route["rules"] = [
            r for r in route.get("rules", []) if r.get("outbound") != MESH_ENDPOINT_TAG
        ]
        # sing-box refuses to start with a tailscale DNS server whose endpoint is missing.
        dns["servers"] = [s for s in dns.get("servers", []) if s.get("tag") != MESH_DNS_TAG]
        dns["rules"] = [r for r in dns.get("rules", []) if r.get("server") != MESH_DNS_TAG]
        return [ep for ep in endpoints if ep.get("tag") != MESH_ENDPOINT_TAG]
    for ep in endpoints:
        if ep.get("tag") == MESH_ENDPOINT_TAG:
            ep["auth_key"] = key
            ep["hostname"] = username
            ep["control_url"] = control_url
    return endpoints


def apply_warp(
    endpoints: List[Dict[str, Any]],
    route: Dict[str, Any],
    dns: Dict[str, Any],
    key: str,
    ipv6: str,
) -> List[Dict[str, Any]]:
    """Fill the WARP endpoint for a user with a WARP key; strip it, every route
    rule pointing at it, and the DNS rules that answer AAAA for its domains, for
    a user without one. Mutates `route` and `dns`."""
    if not key:
        warp_rules = [r for r in route.get("rules", []) if r.get("outbound") == WARP_ENDPOINT_TAG]
        route["rules"] = [r for r in route.get("rules", []) if r not in warp_rules]
        domains = [r["domain_suffix"] for r in warp_rules if "domain_suffix" in r]
        dns["rules"] = [r for r in dns.get("rules", []) if r.get("domain_suffix") not in domains]
        return [ep for ep in endpoints if ep.get("tag") != WARP_ENDPOINT_TAG]
    for ep in endpoints:
        if ep.get("tag") == WARP_ENDPOINT_TAG:
            ep["private_key"] = key
            if ipv6:  # WARP assigns each account its own IPv6; IPv4 is the same for all
                ep["address"].append(ipv6)
    return endpoints


def strip_tun_ipv6(inbounds: List[Dict[str, Any]]) -> None:
    """Drop the IPv6 addresses from the tun inbound. Without WARP the profile has no
    IPv6 path, and a tun IPv6 address makes apps try IPv6 and stall. Mutates `inbounds`."""
    for ib in inbounds:
        if ib.get("type") == "tun":
            ib["address"] = [a for a in ib.get("address", []) if ":" not in a]


def apply_warp_rules(
    route: Dict[str, Any], dns: Dict[str, Any], matchers: Dict[str, List[str]]
) -> None:
    """Fill the WARP domains (the warp-ep route rule and the DNS rule with the same
    domain_suffix, both empty in the template) from an `r6` rule set; strip both
    when there is none, since an empty rule would match everything. Mutates both."""
    routes = [r for r in route.get("rules", []) if r.get("outbound") == WARP_ENDPOINT_TAG and "domain_suffix" in r]
    domains = [r["domain_suffix"] for r in routes]
    dnses = [r for r in dns.get("rules", []) if r.get("domain_suffix") in domains]
    if not matchers:
        route["rules"] = [r for r in route.get("rules", []) if r not in routes]
        dns["rules"] = [r for r in dns.get("rules", []) if r not in dnses]
        return
    for target in routes + dnses:
        for field, values in matchers.items():
            existing = target.setdefault(field, [])
            existing.extend(v for v in dict.fromkeys(values) if v not in existing)


def _bad_rules(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=f"User rule set: {detail}")


USER_RULE_FIELDS = ("domain_suffix", "domain_keyword", "domain_regex")


def parse_user_rules(body: bytes) -> Dict[str, List[str]]:
    """Domain matchers from a User rule set, by field. Structure only; the client
    validates the rest (e.g. domain_regex syntax)."""
    try:
        data = json.loads(body)
    except ValueError:
        raise _bad_rules("not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("version"), int):
        raise _bad_rules("missing integer 'version'")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _bad_rules("'rules' must be a non-empty list")
    matchers: Dict[str, List[str]] = {}
    for rule in rules:
        if not isinstance(rule, dict) or not rule or not set(rule) <= set(USER_RULE_FIELDS):
            raise _bad_rules(f"each rule may only contain {', '.join(USER_RULE_FIELDS)}")
        for field, values in rule.items():
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise _bad_rules(f"'{field}' must be a list of strings")
            matchers.setdefault(field, []).extend(values)
    return matchers


def fetch_user_rules(url: str) -> Dict[str, List[str]]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in USER_RULES_HOSTS:
        raise _bad_rules(f"URL must be https on {', '.join(USER_RULES_HOSTS)}")
    # GitHub CDN caches raw content ~5 min per URL; fresh query string bypasses it.
    url = f"{url}{'&' if parts.query else '?'}_={int(time.time())}"
    body = b""
    try:
        with httpx.stream("GET", url, timeout=HTTP_TIMEOUT, follow_redirects=False) as r:
            if r.status_code != 200:
                raise _bad_rules(f"fetch returned HTTP {r.status_code}")
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > USER_RULES_MAX_BYTES:
                    raise _bad_rules(f"larger than {USER_RULES_MAX_BYTES} bytes")
    except httpx.HTTPError as exc:
        raise _bad_rules(f"fetch failed ({type(exc).__name__})")
    return parse_user_rules(body)


def parse_user_ips(raw: str) -> List[str]:
    """A User IP list (`rr.ip_cidr`) as sing-box `ip_cidr` values: bare IPv4 only, one host each."""
    try:
        return [f"{ipaddress.IPv4Address(ip)}/32" for ip in raw.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"rr.ip_cidr: {exc}")


def apply_user_rules(route: Dict[str, Any], matchers: Dict[str, List[str]]) -> None:
    """Add a User rule set's or User IP list's matchers to every rule holding a domain_suffix
    list under the proxied (`shadowsocks-uot` outbound) rules. sing-box ORs the domain_* and
    ip_cidr fields within one rule, so they all sit beside the suffixes. Mutates `route`."""
    targets: List[Dict[str, Any]] = []

    def walk(rule: Dict[str, Any]) -> None:
        if isinstance(rule.get("domain_suffix"), list):
            targets.append(rule)
        for child in rule.get("rules", []):
            walk(child)

    for rule in route.get("rules", []):
        if rule.get("outbound") == PROXY_OUTBOUND:
            walk(rule)
    if not targets:
        logger.error("Client template route has no proxied domain_suffix list")
        raise HTTPException(status_code=500, detail="No proxied domain_suffix list in route.")
    for target in targets:
        for field, values in matchers.items():
            existing = target.setdefault(field, [])
            existing.extend(v for v in dict.fromkeys(values) if v not in existing)


# -------------------------------------------------------------------
# User check
# -------------------------------------------------------------------


def verify_user(username: str, psk: str) -> None:
    """Raise 400 unless ssm-api holds `username` under the key derived from `psk` and quota is left."""
    try:
        # Sync routes run in an anyio worker thread; ssm-api is reached from the event loop.
        data = anyio.from_thread.run(ssm_api.client.get_user, username)
        if data is None:
            raise ValueError("No such user in ssm-api")

        if data.get("uPSK") != ssm_key(psk):
            raise ValueError("User or PSK mismatch")

        used_bytes = data.get("uplinkBytes", 0) + data.get("downlinkBytes", 0)
        if used_bytes > APP_DEFAULT_QUOTA_IN_BYTES:
            raise ValueError("Quota exceeded")

        logger.info("User %s verified", username)
    except Exception as exc:
        logger.error("User verification failed: %s", exc)
        raise HTTPException(
            status_code=400, detail="User verification failed or quota exceeded."
        )


# -------------------------------------------------------------------
# Profile config
# -------------------------------------------------------------------


def load_template(client_dir: str = APP_CLIENT_DIR) -> Dict[str, Any]:
    """The Client template: every section by name."""
    return {name: load_json(f"{client_dir}/{name}.json")[name] for name in TEMPLATE_SECTIONS}


def build_profile(
    template: Dict[str, Any],
    user: Dict[str, Any],
    *,
    username: str,
    psk: str,
    log_level: str,
    dns_host: str,
    dns_sni: str,
    dns_path: str,
    dns_detour: str,
    dns_final: str,
    dns_resolver: str,
    rules_url: str = "",
    rules_detour: str = "",
    rules_v6_url: str = "",
    user_ips: str = "",
    control_url: str = APP_TS_CONTROL_URL,
    fetch_rules: Callable[[str], Dict[str, List[str]]] = fetch_user_rules,
) -> Dict[str, Any]:
    """The Profile config for one user: the Client template plus per-user values.
    `user` is the User record, {} when there is none. `template` is left unchanged.
    The user is not checked here: call verify_user first."""
    logger.info("Injecting config for user %s", username)
    config = copy.deepcopy(template)
    endpoints = config.pop("endpoints")

    if log_level:
        config["log"]["level"] = log_level

    dns = config["dns"]
    if dns_final:
        dns["final"] = dns_final
    for server in dns.get("servers", []):
        match server.get("tag"):
            case "dns-remote":
                server["server"] = dns_host
                server["path"] = f"{dns_path}{username}"
                if dns_sni:  # host is a pinned IP; SNI + cert check need the name
                    server["tls"] = {"enabled": True, "server_name": dns_sni}
            case "dns-resolver":
                server["server"] = dns_resolver
                server["detour"] = dns_detour
            case "dns-resolver-bypass":
                server["server"] = dns_resolver

    for ob in config["outbounds"]:
        if ob.get("type") != "shadowsocks":
            continue  # ShadowTLS password is shared, set by Init
        # SIP022 `iPSK:uPSK`; Init wrote the server PSK into the template's `password`
        ob["password"] = f"{ob['password']}:{client_key(psk)}"

    apply_full_mode(config["route"], bool(user.get("admin")))
    if rules_url:
        apply_user_rules(config["route"], fetch_rules(rules_url))
    if user_ips:
        apply_user_rules(config["route"], {"ip_cidr": parse_user_ips(user_ips)})
    if rules_detour:
        if rules_detour not in {hc["tag"] for hc in config["http_clients"]}:
            raise HTTPException(status_code=400, detail=f"rd: no HTTP client tagged {rules_detour!r}")
        apply_rules_detour(config["route"], rules_detour)
    key = user.get("ts_auth_key") or ""
    if key and not control_url:
        logger.error("User %s has a Mesh key but APP_TS_CONTROL_URL is empty", username)
        raise HTTPException(status_code=500, detail="APP_TS_CONTROL_URL is not set.")
    endpoints = apply_mesh(endpoints, config["route"], dns, username, key, control_url)
    # A WARP rule set (r6) turns WARP on: its domains get AAAA answers and IPv6 goes to warp-ep.
    warp_key = (user.get("warp_key") or "") if rules_v6_url else ""
    warp_domains = fetch_rules(rules_v6_url) if warp_key else {}
    apply_warp_rules(config["route"], dns, warp_domains)
    endpoints = apply_warp(endpoints, config["route"], dns, warp_key, user.get("warp_ipv6") or "")
    if not warp_key:
        strip_tun_ipv6(config["inbounds"])
    if endpoints:
        config["endpoints"] = endpoints
    return config
