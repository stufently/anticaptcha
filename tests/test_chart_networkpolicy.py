"""Static checks of the worker egress NetworkPolicy in the chart.

CI runs tests in the app image, which has no helm, so the template and the
defaults are checked as text/YAML here; rendering is checked with helm locally.
"""
import ipaddress
import pathlib
import re

import pytest
import yaml

CHART = pathlib.Path(__file__).resolve().parents[1] / "chart"
TEMPLATE = CHART / "templates" / "networkpolicy-worker.yaml"
VALUES = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
NP = VALUES["networkPolicy"]


def test_policy_is_off_by_default():
    assert NP["enabled"] is False
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.startswith("{{- if .Values.networkPolicy.enabled }}")
    assert text.rstrip().endswith("{{- end }}")


def test_policy_selects_only_worker_pods_for_egress():
    text = TEMPLATE.read_text(encoding="utf-8")
    selector = text.split("  podSelector:\n", 1)[1].split("  policyTypes:", 1)[0]
    assert 'include "anticaptcha.selectorLabels"' in selector
    assert "app.kubernetes.io/component: worker" in selector
    types = text.split("  policyTypes:\n", 1)[1].split("  egress:", 1)[0]
    assert re.findall(r"^\s+- (\S+)$", types, flags=re.M) == ["Egress"]


@pytest.mark.parametrize(
    "cidr",
    ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
     "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "224.0.0.0/4", "240.0.0.0/4"],
)
def test_ipv4_defaults_block_internal_ranges(cidr):
    assert NP["ipv4"]["cidr"] == "0.0.0.0/0"
    assert cidr in NP["ipv4"]["except"]


@pytest.mark.parametrize("cidr", ["::1/128", "fc00::/7", "fe80::/10", "::ffff:0:0/96"])
def test_ipv6_defaults_block_internal_ranges(cidr):
    assert NP["ipv6"]["cidr"] == "::/0"
    assert cidr in NP["ipv6"]["except"]


@pytest.mark.parametrize("family,version", [("ipv4", 4), ("ipv6", 6)])
def test_except_entries_are_strict_subnets_of_cidr(family, version):
    # The API server rejects an except entry outside its cidr or of the other
    # address family, which would break the install.
    block = ipaddress.ip_network(NP[family]["cidr"])
    assert block.version == version
    for raw in NP[family]["except"]:
        net = ipaddress.ip_network(raw)
        assert net.version == version, raw
        assert net.subnet_of(block) and net != block, raw
    assert NP[family]["extraExcept"] == []


def test_dns_rule_targets_cluster_dns_on_port_53():
    assert NP["dns"]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "kube-system"}
    assert NP["dns"]["podSelector"]["matchLabels"] == {"k8s-app": "kube-dns"}
    assert sorted((p["protocol"], p["port"]) for p in NP["dns"]["ports"]) == [
        ("TCP", 53), ("UDP", 53)]


def test_extra_egress_is_empty_and_rendered():
    assert NP["extraEgress"] == []
    assert "$np.extraEgress" in TEMPLATE.read_text(encoding="utf-8")
