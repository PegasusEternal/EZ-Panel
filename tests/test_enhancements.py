from ez_panel.utils import network_scan as ns


def test_vendor_from_mac():
    # Known prefixes in fixture
    assert ns._vendor_from_mac('00:50:56:AA:BB:CC') == 'VMware, Inc.'
    assert ns._vendor_from_mac('b8-27-eb-12-34-56') == 'Raspberry Pi Foundation'
    assert ns._vendor_from_mac('ZZ:ZZ:ZZ:ZZ:ZZ:ZZ') is None


def test_parse_dnsmasq_leases(tmp_path):
    content = """
    1735689600 aa:bb:cc:dd:ee:ff 192.0.2.10 testhost *
    1735689600 11:22:33:44:55:66 192.0.2.11 * *
    """.strip()
    p = tmp_path / 'dnsmasq.leases'
    p.write_text(content)
    res = ns.parse_dnsmasq_leases(str(p))
    assert any(d['ip'] == '192.0.2.10' and d['name'] == 'testhost' for d in res)


def test_parse_dhcpd_leases(tmp_path):
    content = """
    lease 192.0.2.20 {
      starts 6 2025/09/15 12:00:00;
      ends 6 2025/09/15 13:00:00;
      hardware ethernet 00:11:22:33:44:55;
      client-hostname "lab-device";
    }
    """.strip()
    p = tmp_path / 'dhcpd.leases'
    p.write_text(content)
    res = ns.parse_dhcpd_leases(str(p))
    assert any(d['ip'] == '192.0.2.20' and d['mac'] == '00:11:22:33:44:55' and d['name'] == 'lab-device' for d in res)
