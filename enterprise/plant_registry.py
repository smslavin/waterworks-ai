"""Locates and loads enterprise.yaml through fieldworks.enterprise (spec Part V).

fieldworks-core owns the schema and its rules: a site missing a required
field is an error, not a site to skip, and site_id is unique across every
region. This module only resolves which file to read (ENTERPRISE_FILE, else
the repo root's enterprise.yaml).

Read fresh on every call rather than cached at import time — it's one small
YAML file, and re-reading means a site added while services are running is
picked up without a restart. The cross-file check (each topology_file's
facility.site_id) opens every topology, so it runs once, in start.sh, via
`fieldworks validate-enterprise`.
"""

import os
from pathlib import Path

from fieldworks.enterprise import EnterpriseConfig, RegisteredSite, load

_DEFAULT_PATH = Path(__file__).parent.parent / "enterprise.yaml"


def enterprise_path(path: str | Path | None = None) -> Path:
    return (
        Path(path) if path else Path(os.environ.get("ENTERPRISE_FILE", _DEFAULT_PATH))
    )


def load_enterprise(path: str | Path | None = None) -> EnterpriseConfig:
    """Raises ValueError if enterprise.yaml breaks a Part V structural rule."""
    return load(enterprise_path(path))


def load_sites(path: str | Path | None = None) -> dict[str, RegisteredSite]:
    return load_enterprise(path).sites()


def get_site(site_id: str, path: str | Path | None = None) -> RegisteredSite | None:
    return load_enterprise(path).get_site(site_id)


def sites_json(path: str | Path | None = None) -> dict[str, dict]:
    """{site_id: {name, region, topology_file, chat_ui_url, aggregator_url}} —
    the /api/sites shape SiteNav reads."""
    return {
        site_id: {
            "name": site.name,
            "region": site.region_name,
            "topology_file": site.topology_file,
            "chat_ui_url": site.chat_ui_url,
            "aggregator_url": site.aggregator_url,
        }
        for site_id, site in load_sites(path).items()
    }
