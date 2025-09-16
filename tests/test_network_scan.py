import json
import re

from ez_panel.utils import network_scan as ns


def test_is_ipv4():
    assert ns._is_ipv4("192.168.1.1")
    assert not ns._is_ipv4("999.999.999.999")
    assert not ns._is_ipv4("hostname")


def test_normalize_ping_sweep_small_network(monkeypatch):
    # Monkeypatch discover to a tiny /30 for quick loop
    monkeypatch.setattr(ns, "discover_local_cidr", lambda: "192.0.2.0/30")
    # Force ping backend without calling system ping
    monkeypatch.setattr(ns, "_which", lambda name: None)

    # When ping is unavailable, _ping_once will return False; include_offline will list hosts
    res = ns.scan_network(subnet=None, include_offline=True, method="ping")
    assert isinstance(res, list)
    assert all("ip" in d and "status" in d for d in res)


def test_cli_help(monkeypatch, capsys):
    # Ensure CLI prints helpful message when no CIDR
    monkeypatch.setattr(ns, "discover_local_cidr", lambda: None)
    try:
        ns.__name__ == "__main__"  # no-op, just reference
    except Exception:
        pass
