"""Loads enterprise.yaml and maps site_id -> plant metadata (chat_ui_url, etc.).

Read fresh on every call rather than cached at import time — enterprise.yaml
is a small, infrequently-read file, and re-reading it means a site added
while services are running is picked up without a restart.
"""

import os
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent / "enterprise.yaml"


def _resolve_path(path: str | Path | None = None) -> Path:
    return (
        Path(path) if path else Path(os.environ.get("ENTERPRISE_FILE", _DEFAULT_PATH))
    )


def load_sites(path: str | Path | None = None) -> dict[str, dict]:
    """Return {site_id: {name, region, topology_file, chat_ui_url}}, flattened
    across every region in enterprise.yaml. Sites without a chat_ui_url (e.g.
    a region listed with no sites yet) are skipped."""
    with open(_resolve_path(path)) as f:
        data = yaml.safe_load(f) or {}

    sites: dict[str, dict] = {}
    for region in data.get("regions", []) or []:
        for site in region.get("sites", []) or []:
            site_id = site.get("site_id")
            chat_ui_url = site.get("chat_ui_url")
            if not site_id or not chat_ui_url:
                continue
            sites[site_id] = {
                "name": site.get("name", site_id),
                "region": region.get("name", region.get("id", "")),
                "topology_file": site.get("topology_file"),
                "chat_ui_url": chat_ui_url,
            }
    return sites


def get_site(site_id: str, path: str | Path | None = None) -> dict | None:
    return load_sites(path).get(site_id)
