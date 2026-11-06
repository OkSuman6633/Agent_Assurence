import ipaddress
import os
import socket
from urllib.parse import urlparse

class UnsafeEndpoint(ValueError):
    pass

def validate_endpoint(endpoint_url: str, allowed_hosts: list[str] | None = None) -> None:
    parsed = urlparse(endpoint_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeEndpoint("Endpoint hostname is missing.")

    is_local_host = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")
    is_dev = os.getenv("ENVIRONMENT", "development").lower() != "production" or os.getenv("AGENT_ASSURANCE_DEV_ALLOW_PRIVATE_HOSTS", "").lower() == "true"

    if parsed.scheme != "https":
        # Local HTTP is permitted in development
        if not (is_dev and is_local_host and parsed.scheme == "http"):
            raise UnsafeEndpoint("Remote agent endpoints must use HTTPS (HTTP is permitted for local endpoints in development).")

    if parsed.username or parsed.password:
        raise UnsafeEndpoint("Credentials must not be embedded in endpoint URLs.")

    if allowed_hosts:
        allow = {h.lower().rstrip(".") for h in allowed_hosts}
        if host not in allow and not (is_dev and is_local_host):
            raise UnsafeEndpoint(f"Endpoint hostname '{host}' is not in the explicit allowlist.")

    try:
        addresses = {x[4][0] for x in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror:
        if is_local_host:
            addresses = {"127.0.0.1"}
        else:
            raise UnsafeEndpoint(f"Endpoint hostname '{host}' could not be resolved.")

    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        # Block private IP ranges unless it's explicitly a local test host in development mode
        if not (is_local_host and is_dev) and (not ip.is_global):
            raise UnsafeEndpoint("Endpoint resolves to a non-public IP address.")
