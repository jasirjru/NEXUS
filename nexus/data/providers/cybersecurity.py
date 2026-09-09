"""Cybersecurity domain adapter: maps network security entities/events to NEXUS.

Entities: IP addresses, hosts, services, user accounts
Events: network flows, login attempts, alerts, file access
Relationships: IP→IP (connections), user→host (access), IP→service (scans)

Demonstrates domain-independence: the same intelligence pipeline (features,
anomaly detection, risk scoring, investigation) works on network security data.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from nexus.core.models import EntityModel, EntityType, EventModel, EventType
from nexus.data.providers.base import DataProvider


class CybersecurityProvider(DataProvider):
    """Demo cybersecurity provider generating synthetic network flows.

    In production, this would connect to SIEM APIs (Splunk, Elastic),
    firewall logs, or network flow collectors (NetFlow/IPFIX).
    """

    name = "cybersecurity"

    def __init__(self, n_hosts: int = 40, n_events: int = 600, seed: int = 42) -> None:
        self.n_hosts = n_hosts
        self.n_events = n_events
        self.rng = np.random.RandomState(seed)
        self.services = ["ssh", "http", "https", "dns", "smtp", "rdp", "ftp", "mysql"]

    def _gen_ip(self, idx: int) -> str:
        """Generate a deterministic IP address."""
        return f"10.{(idx // 256) % 256}.{idx % 256}.{(idx * 7 + 3) % 256}"

    def iter_entities(self, batch: int = 500) -> Iterator[EntityModel]:
        for i in range(self.n_hosts):
            ip = self._gen_ip(i)
            is_server = i < 10
            yield EntityModel(
                id=f"host:{ip}",
                type=EntityType.WALLET,  # reuse wallet type for hosts
                label=f"{'server' if is_server else 'workstation'}-{i:03d}",
                attributes={
                    "domain": "cybersecurity",
                    "ip": ip,
                    "role": "server" if is_server else "workstation",
                    "os": self.rng.choice(["linux", "windows", "macos"]),
                },
            )
        for svc in self.services:
            yield EntityModel(
                id=f"service:{svc}",
                type=EntityType.PROTOCOL,  # reuse protocol type for services
                label=svc.upper(),
                attributes={"domain": "cybersecurity", "port": {"ssh": 22, "http": 80, "https": 443,
                             "dns": 53, "smtp": 25, "rdp": 3389, "ftp": 21, "mysql": 3306}.get(svc, 0)},
            )

    def iter_events(self, batch: int = 500) -> Iterator[EventModel]:
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        hosts = [f"host:{self._gen_ip(i)}" for i in range(self.n_hosts)]
        n_attack = max(3, self.n_hosts // 10)  # a few compromised hosts

        for seq in range(self.n_events):
            src = self.rng.choice(hosts)
            dst = self.rng.choice(hosts)
            while dst == src:
                dst = self.rng.choice(hosts)

            ts = base_time + timedelta(minutes=seq * 2 + self.rng.uniform(0, 2))
            bytes_transferred = int(self.rng.lognormal(10, 2))
            event_id = hashlib.md5(f"cyber:{seq}:{src}".encode()).hexdigest()[:16]

            # Inject attack patterns for some hosts
            src_idx = hosts.index(src) if src in hosts else -1
            is_attack = src_idx < n_attack and self.rng.random() < 0.3
            attrs: dict[str, Any] = {
                "domain": "cybersecurity",
                "protocol": self.rng.choice(self.services),
                "bytes": bytes_transferred,
                "source": "cyber_demo",
            }
            if is_attack:
                attrs["pattern"] = self.rng.choice(["port_scan", "brute_force", "data_exfil"])
                attrs["severity"] = self.rng.choice(["medium", "high", "critical"])

            yield EventModel(
                id=f"cyber:{event_id}",
                type=EventType.TRANSACTION,
                timestamp=ts,
                from_entity=src,
                to_entity=dst,
                value_wei=bytes_transferred,  # reuse value_wei for bytes
                attributes=attrs,
            )

    def close(self) -> None:
        pass
