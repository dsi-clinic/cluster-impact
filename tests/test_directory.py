"""Directory source: LDAP search-base resolution.

python-ldap is an optional dependency (`pip install .[ldap]`) and is absent in
the offline suite, so these tests substitute a fake `ldap` module. Only the
search bases and the row counts matter here — no usernames or DNs are asserted
on, because none ever leave the module.
"""

from unittest.mock import MagicMock

import pytest

from collector.sources import directory as directory_module
from collector.sources.directory import DirectorySource

USER_BASE = "dc=uchicago,dc=edu"
GROUP_BASE = "ou=group,dc=cs,dc=uchicago,dc=edu"


@pytest.fixture
def fake_ldap(monkeypatch):
    """Install a fake python-ldap whose search_s records the base it was given."""
    conn = MagicMock()
    # Two users, one group — distinct counts so a swapped base is obvious.
    conn.search_s.side_effect = lambda base, *_: (
        [("uid=a", {}), ("uid=b", {})] if "uid" in str(_[-1]) else [("cn=g", {})]
    )
    fake = MagicMock()
    fake.SCOPE_SUBTREE = 2
    fake.initialize.return_value = conn
    monkeypatch.setattr(directory_module, "ldap", fake)
    return fake, conn


def _search_bases(conn):
    return [call.args[0] for call in conn.search_s.call_args_list]


def test_specific_bases_resolve_independently():
    source = DirectorySource(
        {
            "ldap_uri": "ldaps://ldap.example.edu",
            "user_base_dn": USER_BASE,
            "group_base_dn": GROUP_BASE,
        }
    )
    assert source.user_base_dn == USER_BASE
    assert source.group_base_dn == GROUP_BASE


def test_both_bases_fall_back_to_base_dn():
    source = DirectorySource({"ldap_uri": "ldaps://ldap.example.edu", "base_dn": USER_BASE})
    assert source.user_base_dn == USER_BASE
    assert source.group_base_dn == USER_BASE


def test_specific_base_wins_over_base_dn():
    source = DirectorySource({"base_dn": USER_BASE, "group_base_dn": GROUP_BASE})
    assert source.user_base_dn == USER_BASE
    assert source.group_base_dn == GROUP_BASE


def test_not_configured_without_any_base(fake_ldap):
    source = DirectorySource({"ldap_uri": "ldaps://ldap.example.edu"})
    assert source.ldap_configured is False
    doc, warnings = source.fetch_account_counts()
    assert doc["available"] is False
    assert any("not configured" in w for w in warnings)


def test_not_configured_when_only_one_specific_base_is_set(fake_ldap):
    # user_base_dn alone leaves the group search with nowhere to look, and
    # there is no base_dn to fall back to.
    source = DirectorySource({"ldap_uri": "ldaps://ldap.example.edu", "user_base_dn": USER_BASE})
    assert source.ldap_configured is False


def test_configured_with_base_dn_only(fake_ldap):
    source = DirectorySource({"ldap_uri": "ldaps://ldap.example.edu", "base_dn": USER_BASE})
    assert source.ldap_configured is True


def test_each_search_uses_its_own_base(fake_ldap):
    _, conn = fake_ldap
    source = DirectorySource(
        {
            "ldap_uri": "ldaps://ldap.example.edu",
            "user_base_dn": USER_BASE,
            "group_base_dn": GROUP_BASE,
        }
    )
    doc, warnings = source.fetch_account_counts()

    assert _search_bases(conn) == [USER_BASE, GROUP_BASE]
    assert doc == {"available": True, "accounts_total": 2, "groups_total": 1}
    assert not warnings


def test_fallback_path_sends_base_dn_to_both_searches(fake_ldap):
    _, conn = fake_ldap
    source = DirectorySource({"ldap_uri": "ldaps://ldap.example.edu", "base_dn": USER_BASE})
    doc, warnings = source.fetch_account_counts()

    assert _search_bases(conn) == [USER_BASE, USER_BASE]
    assert doc["available"] is True
    assert not warnings


def test_ldap_failure_degrades_to_unavailable(fake_ldap):
    _, conn = fake_ldap
    conn.search_s.side_effect = RuntimeError("boom")
    source = DirectorySource(
        {
            "ldap_uri": "ldaps://ldap.example.edu",
            "user_base_dn": USER_BASE,
            "group_base_dn": GROUP_BASE,
        }
    )
    doc, warnings = source.fetch_account_counts()

    assert doc == {"available": False}
    assert any("LDAP query failed" in w for w in warnings)
