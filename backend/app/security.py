import ipaddress
import os
import socket
from urllib.parse import urlparse

class UnsafeEndpoint(ValueError):
    pass

def validate_endpoint(endpoint_url: str, allowed_hosts: list[str]) -> None:
    parsed = urlparse(endpoint_url)
    if parsed.scheme != "https":
        # Local HTTP is permitted only in explicit development mode.
        local_dev = os.getenv("AGENT_ASSURANCE_DEV_ALLOW_PRIVATE_HOSTS", "").lower() == "true"
        if not (local_dev and parsed.scheme == "http"):
            raise UnsafeEndpoint("Remote agent endpoints must use HTTPS.")
    if parsed.username or parsed.password:
        raise UnsafeEndpoint("Credentials must not be embedded in endpoint URLs.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeEndpoint("Endpoint hostname is missing.")
    allow = {h.lower().rstrip(".") for h in allowed_hosts}
    if host not in allow:
        raise UnsafeEndpoint("Endpoint hostname is not in the explicit allowlist.")
    # Development guard against common SSRF targets. This is not a substitute for
    # production egress firewalling, DNS pinning, and cloud-level network policy.
    dev_private = os.getenv("AGENT_ASSURANCE_DEV_ALLOW_PRIVATE_HOSTS", "").lower() == "true"
    try:
        addresses = {x[4][0] for x in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror:
        raise UnsafeEndpoint("Endpoint hostname could not be resolved.")
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if not dev_private and (not ip.is_global):
            raise UnsafeEndpoint("Endpoint resolves to a non-public IP address.")
