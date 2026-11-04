"""Rotating proxy pool: every call to next() hands out a different exit IP."""
from __future__ import annotations

import itertools
import os
import secrets
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from .config import PROXY_PRESETS


class ProxyConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyEndpoint:
    server: str                 # scheme://host:port
    username: str = ""
    password: str = ""

    def for_playwright(self) -> dict[str, str]:
        cfg = {"server": self.server}
        if self.username:
            cfg["username"] = self.username
            cfg["password"] = self.password
        return cfg

    def for_http(self) -> str:
        """URL form for aiohttp: http://user:pass@host:port"""
        if not self.username:
            return self.server
        parts = urlsplit(self.server)
        auth = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}"
        return f"{parts.scheme}://{auth}@{parts.netloc}"

    def masked(self) -> str:
        return urlsplit(self.server).netloc  # never log credentials


def _parse_proxy_url(raw: str) -> tuple[str, str, str]:
    raw = raw.strip()
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    if not parts.hostname or not parts.port:
        raise ProxyConfigError(f"Proxy needs host and port: {parts.netloc or raw!r}")
    server = f"{parts.scheme}://{parts.hostname}:{parts.port}"
    return server, parts.username or "", parts.password or ""


class ProxyPool:
    """Round-robin over endpoints. A "{session}" placeholder in a username becomes a fresh
    random id on every call, which residential gateways treat as a new IP."""

    def __init__(self, templates: list[tuple[str, str, str]]):
        self._templates = templates
        self._cycle = itertools.cycle(templates) if templates else None

    @property
    def enabled(self) -> bool:
        return self._cycle is not None

    def next(self) -> ProxyEndpoint | None:
        if self._cycle is None:
            return None
        server, user, password = next(self._cycle)
        if "{session}" in user:
            user = user.replace("{session}", secrets.token_hex(6))
        return ProxyEndpoint(server, user, password)

    @classmethod
    def from_env(cls, provider: str | None = None) -> "ProxyPool":
        provider = (provider or os.getenv("OA_PROXY_PROVIDER", "none")).strip().lower()
        if provider in ("", "none", "off"):
            return cls([])

        if provider == "custom":
            lines: list[str] = []
            if os.getenv("OA_PROXY_LIST"):
                lines += os.environ["OA_PROXY_LIST"].split(",")
            if os.getenv("OA_PROXY_FILE"):
                with open(os.environ["OA_PROXY_FILE"], encoding="utf-8") as fh:
                    lines += fh.read().splitlines()
            lines = [ln for ln in (ln.strip() for ln in lines) if ln and not ln.startswith("#")]
            if not lines:
                raise ProxyConfigError("OA_PROXY_PROVIDER=custom needs OA_PROXY_LIST or OA_PROXY_FILE")
            return cls([_parse_proxy_url(ln) for ln in lines])

        preset = PROXY_PRESETS.get(provider)
        if preset is None:
            raise ProxyConfigError(f"Unknown proxy provider {provider!r}; use one of "
                                   f"{', '.join([*PROXY_PRESETS, 'custom', 'none'])}")

        def env(name_key: str) -> str:
            name = preset.get(name_key)
            if not name:
                return ""
            value = os.getenv(name, "")
            if not value:
                raise ProxyConfigError(f"{provider} proxy needs the {name} environment variable")
            return value

        password = env("password_env")
        username = preset.get("username") or env("username_env")
        template = preset.get("username_template")
        if template:
            username = template.format(username=username, session="{session}")
        return cls([(preset["server"], username, password)])
