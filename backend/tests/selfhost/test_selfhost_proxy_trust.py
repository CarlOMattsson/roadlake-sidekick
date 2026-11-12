"""Only Caddy is a trusted proxy of the api: forwarded headers from any other peer are ignored."""

import ipaddress
from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "selfhost" / "compose.yaml"


@pytest.fixture(name="compose")
def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _address(service: dict, network: str) -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(service["networks"][network]["ipv4_address"])


def _trusted(api: dict) -> str:
    flags = [a for a in api["command"] if a.startswith("--forwarded-allow-ips=")]
    assert len(flags) == 1
    return flags[0].partition("=")[2]


def test_api_trusts_one_exact_address_not_every_sender(compose: dict) -> None:
    trusted = _trusted(compose["services"]["api"])
    # `*`, a list or a network would let another container on edge forge X-Forwarded-For/-Proto.
    assert "*" not in trusted and "," not in trusted and "/" not in trusted
    ipaddress.IPv4Address(trusted)


def test_the_trusted_address_is_caddys_on_the_network_it_shares_only_with_api(
    compose: dict,
) -> None:
    services = compose["services"]
    proxy = compose["networks"]["proxy"]
    assert proxy["internal"] is True
    subnet = ipaddress.IPv4Network(proxy["ipam"]["config"][0]["subnet"])
    members = [n for n, s in services.items() if "proxy" in (s.get("networks") or {})]
    assert sorted(members) == ["api", "caddy"]
    caddy_address = _address(services["caddy"], "proxy")
    assert str(caddy_address) == _trusted(services["api"])
    assert caddy_address in subnet and _address(services["api"], "proxy") in subnet
    assert caddy_address != _address(services["api"], "proxy")
    # edge has no fixed addresses, so no container on it can hold the trusted one.
    assert "ipam" not in compose["networks"]["edge"]


def test_caddy_reaches_api_by_its_proxy_address_not_the_edge_one(compose: dict) -> None:
    # Docker's DNS would answer `api` with the edge address, which api does not trust.
    services = compose["services"]
    assert services["caddy"]["extra_hosts"] == [f"api:{_address(services['api'], 'proxy')}"]
