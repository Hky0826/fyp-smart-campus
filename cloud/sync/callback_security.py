"""Validation for administratively provisioned cloud-to-edge destinations."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


def validate_callback_url(url: str, *, allowed_cidrs: tuple[str, ...] | None = None) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("callback destinations must be HTTPS URLs without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("callback destinations may not contain query or fragment data")
    if parsed.hostname.casefold() in {"metadata", "metadata.google.internal", "instance-data", "169.254.169.254"}:
        raise ValueError("cloud metadata callback destinations are forbidden")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return parsed.geturl()
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise ValueError("callback destination is a reserved address")
    raw_networks = allowed_cidrs if allowed_cidrs is not None else tuple(v.strip() for v in os.getenv("EDGE_CALLBACK_ALLOWED_CIDRS", "").split(",") if v.strip())
    networks = tuple(ipaddress.ip_network(item, strict=False) for item in raw_networks)
    if address.is_private and not networks:
        raise ValueError("private callback destinations require an approved CIDR allowlist")
    if networks and not any(address in network for network in networks):
        raise ValueError("callback destination is outside approved edge networks")
    return parsed.geturl()


def validate_callback_host(value: str, *, allowed_cidrs: tuple[str, ...] | None = None) -> str:
    return validate_callback_url(value if "://" in value else f"https://{value}", allowed_cidrs=allowed_cidrs)
