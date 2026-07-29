"""Account directory: LDAP for people, Foreman for hardware.

This answers "how many active accounts exist", which is a different and more
honest number than "how many accounts ran a job" — the site shows both, and
the gap between them is itself interesting.

Only COUNTS ever leave this module. Usernames and DNs are read and discarded.
Credentials come from the environment, never from config.
"""

from __future__ import annotations

import os
from typing import Any

try:
    import ldap  # type: ignore
except ImportError:  # pragma: no cover
    ldap = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class DirectorySource:
    def __init__(self, settings: dict):
        self.settings = settings or {}

    # -- LDAP -------------------------------------------------------------

    # People and groups live under different subtrees here, so each search
    # carries its own base (mirroring the cluster's sssd.conf). The group base
    # is a descendant of the user base, so a single shared base still returns
    # complete results — it just makes every group lookup walk the whole
    # university subtree. `base_dn` remains the fallback for both so older
    # configs keep working unchanged.

    @property
    def user_base_dn(self) -> str | None:
        return self.settings.get("user_base_dn") or self.settings.get("base_dn")

    @property
    def group_base_dn(self) -> str | None:
        return self.settings.get("group_base_dn") or self.settings.get("base_dn")

    @property
    def ldap_configured(self) -> bool:
        return (
            bool(self.settings.get("ldap_uri") and self.user_base_dn and self.group_base_dn)
            and ldap is not None
        )

    def fetch_account_counts(self) -> tuple[dict[str, Any], list[str]]:
        if not self.ldap_configured:
            return {"available": False}, ["directory: LDAP not configured"]

        uri = self.settings["ldap_uri"]
        user_base_dn = self.user_base_dn
        group_base_dn = self.group_base_dn
        bind_dn = os.environ.get("CLUSTER_IMPACT_LDAP_BIND_DN")
        bind_pw = os.environ.get("CLUSTER_IMPACT_LDAP_BIND_PW")

        try:
            conn = ldap.initialize(uri)
            conn.set_option(ldap.OPT_REFERRALS, 0)
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 30)
            if bind_dn and bind_pw:
                conn.simple_bind_s(bind_dn, bind_pw)
            else:
                conn.simple_bind_s()

            users = conn.search_s(
                user_base_dn,
                ldap.SCOPE_SUBTREE,
                self.settings.get("user_filter", "(objectClass=posixAccount)"),
                # Ask for one cheap attribute; we only ever count the rows.
                ["uid"],
            )
            groups = conn.search_s(
                group_base_dn,
                ldap.SCOPE_SUBTREE,
                self.settings.get("group_filter", "(objectClass=posixGroup)"),
                ["cn"],
            )
            conn.unbind_s()
        except Exception as exc:  # noqa: BLE001
            return {"available": False}, [f"directory: LDAP query failed ({type(exc).__name__})"]

        return (
            {
                "available": True,
                "accounts_total": len(users),
                "groups_total": len(groups),
            },
            [],
        )

    # -- Foreman ----------------------------------------------------------

    @property
    def foreman_configured(self) -> bool:
        return bool(self.settings.get("foreman_url")) and httpx is not None

    def fetch_host_inventory(self) -> tuple[dict[str, Any], list[str]]:
        if not self.foreman_configured:
            return {"available": False}, ["directory: Foreman not configured"]

        user = os.environ.get("CLUSTER_IMPACT_FOREMAN_USER")
        token = os.environ.get("CLUSTER_IMPACT_FOREMAN_TOKEN")
        if not (user and token):
            return {"available": False}, ["directory: Foreman credentials not in environment"]

        url = self.settings["foreman_url"].rstrip("/")
        try:
            response = httpx.get(
                f"{url}/api/v2/hosts",
                params={"per_page": 1, "search": "managed = true"},
                auth=(user, token),
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            return {"available": False}, [f"directory: Foreman query failed ({type(exc).__name__})"]

        return {"available": True, "managed_hosts": int(payload.get("subtotal", 0))}, []
