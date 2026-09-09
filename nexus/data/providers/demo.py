"""Deterministic synthetic Ethereum activity generator (demo provider).

Design goals:
- Fully deterministic from a fixed seed -> reproducible pipelines and tests.
- Realistic shape: a few "roles" for wallets (exchanges, retail, bots, DEX
  contracts, token contracts, protocols) with distinct temporal signatures.
- Injects several clearly anomalous behavioral patterns (drain patterns,
  wash-trading loops, sudden volume spikes, novel-counterparty bursts) so
  anomaly detection has genuine signal to find - never presented as real
  blockchain data; records are marked demo=True in attributes.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from nexus.core.models import EntityModel, EntityType, EventModel, EventType
from nexus.data.providers.base import DataProvider

SEED = 20260909
START = datetime(2026, 7, 1, tzinfo=timezone.utc)
DAYS = 70  # ~10 weeks of activity
END = START + timedelta(days=DAYS)

N_EXCHANGES = 3
N_RETAIL = 40
N_BOTS = 6
N_DRAINERS = 3
N_WASH = 2
N_TOKENS = 4
N_DEX = 2
N_PROTOCOLS = 2


def _addr(prefix: str, i: int) -> str:
    rng = random.Random(f"{SEED}:{prefix}:{i}")
    return "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))


def _entities() -> list[EntityModel]:
    out: list[EntityModel] = []
    for i in range(N_EXCHANGES):
        out.append(EntityModel(id=_addr("exch", i), type=EntityType.WALLET, label=f"exchange_{i}"))
    for i in range(N_RETAIL):
        out.append(EntityModel(id=_addr("retail", i), type=EntityType.WALLET, label=f"retail_{i}"))
    for i in range(N_BOTS):
        out.append(EntityModel(id=_addr("bot", i), type=EntityType.WALLET, label=f"bot_{i}"))
    for i in range(N_DRAINERS):
        out.append(EntityModel(id=_addr("drainer", i), type=EntityType.WALLET, label=f"drainer_{i}"))
    for i in range(N_WASH):
        out.append(EntityModel(id=_addr("wash", i), type=EntityType.WALLET, label=f"wash_{i}"))
    for i in range(N_TOKENS):
        out.append(
            EntityModel(
                id=_addr("token", i),
                type=EntityType.TOKEN,
                label=f"TOKEN{i}",
                attributes={"symbol": f"TK{i}"},
            )
        )
    for i in range(N_DEX):
        out.append(
            EntityModel(id=_addr("dex", i), type=EntityType.CONTRACT, label=f"dex_router_{i}")
        )
    for i in range(N_PROTOCOLS):
        out.append(
            EntityModel(id=_addr("proto", i), type=EntityType.PROTOCOL, label=f"protocol_{i}")
        )
    return out


class DemoEthereumProvider(DataProvider):
    name = "demo"

    def __init__(self) -> None:
        self._entities = _entities()
        self._by_label = {e.label: e.id for e in self._entities}

    # ------------------------------------------------------------ entities
    def iter_entities(self, batch: int = 500) -> Iterator[EntityModel]:
        for e in self._entities:
            yield e

    # ------------------------------------------------------------ events
    def iter_events(self, batch: int = 500) -> Iterator[EventModel]:
        rng = random.Random(SEED)
        seq = 0
        exch = [self._by_label[f"exchange_{i}"] for i in range(N_EXCHANGES)]
        retail = [self._by_label[f"retail_{i}"] for i in range(N_RETAIL)]
        bots = [self._by_label[f"bot_{i}"] for i in range(N_BOTS)]
        drainers = [self._by_label[f"drainer_{i}"] for i in range(N_DRAINERS)]
        wash = [self._by_label[f"wash_{i}"] for i in range(N_WASH)]
        dex = [self._by_label[f"dex_router_{i}"] for i in range(N_DEX)]
        protos = [self._by_label[f"protocol_{i}"] for i in range(N_PROTOCOLS)]

        def emit(ts, etype, src, dst, value_wei=0, gas=21000, gp=20.0, **attrs):
            nonlocal seq
            seq += 1
            block = int((ts - START).total_seconds() // 12)
            yield EventModel(
                id=f"demo:{seq:08d}",
                type=etype,
                block_number=block,
                tx_hash="0x" + f"{seq:064x}",
                timestamp=ts,
                from_entity=src,
                to_entity=dst,
                value_wei=value_wei,
                gas_used=gas,
                gas_price_gwei=gp + rng.uniform(-5, 5),
                attributes={"demo": True, **attrs},
            )

        # 1. Retail wallets: daily-ish activity, exchange deposits + DEX swaps
        for w in retail:
            base_hour = rng.randrange(24)
            for day in range(DAYS):
                n_tx = 1 + (rng.random() < 0.4) + (rng.random() < 0.15)
                for k in range(n_tx):
                    ts = START + timedelta(
                        days=day,
                        hours=base_hour,
                        minutes=rng.randrange(60),
                        seconds=rng.randrange(60),
                    )
                    r = rng.random()
                    if r < 0.5:
                        yield from emit(
                            ts, EventType.TRANSACTION, w, rng.choice(exch),
                            value_wei=int(rng.lognormvariate(0.5, 1.2) * 1e18),
                        )
                    elif r < 0.85:
                        yield from emit(
                            ts, EventType.CONTRACT_CALL, w, rng.choice(dex),
                            value_wei=int(rng.lognormvariate(0.0, 1.2) * 1e18),
                            gas=120000, attrs_call="swap",
                        )
                    else:
                        yield from emit(
                            ts, EventType.TRANSACTION, w, rng.choice(retail),
                            value_wei=int(rng.lognormvariate(-0.5, 1.0) * 1e18),
                        )

        # 2. Bots: high-frequency tiny transfers, very regular intervals
        for b in bots:
            interval = timedelta(minutes=rng.randrange(8, 20))
            t = START
            while t < END:
                yield from emit(
                    t, EventType.TRANSACTION, b, rng.choice(exch),
                    value_wei=int(rng.lognormvariate(-2.0, 0.3) * 1e18),
                    gas=21000, gp=rng.uniform(15, 40),
                )
                t += interval + timedelta(seconds=rng.randrange(-60, 60))

        # 3. Exchange hot wallets: consolidating inflow, periodic sweeps
        for e in exch:
            t = START + timedelta(hours=6)
            while t < END:
                yield from emit(
                    t, EventType.TRANSACTION, e, rng.choice(exch),
                    value_wei=int(rng.lognormvariate(4.0, 0.5) * 1e18),
                    gas=21000,
                )
                t += timedelta(hours=rng.randrange(20, 30))

        # 4. DEX routers -> protocols (contract-to-protocol edges)
        for d in dex:
            t = START
            while t < END:
                yield from emit(
                    t, EventType.PROTOCOL_INTERACTION, d, rng.choice(protos),
                    gas=300000,
                )
                t += timedelta(hours=rng.randrange(1, 4))

        # 5. ANOMALY TYPE A - drainer wallets: dormant, then a burst of
        #    novel-counterparty high-value transfers in a short window.
        for d in drainers:
            dormant_day = 10 + rng.randrange(40)
            # dormant: nearly silent
            for day in range(dormant_day):
                if rng.random() < 0.05:
                    ts = START + timedelta(days=day, hours=rng.randrange(24))
                    yield from emit(
                        ts, EventType.TRANSACTION, d, rng.choice(exch),
                        value_wei=int(rng.lognormvariate(-1.0, 0.5) * 1e18),
                    )
            # burst: 12h of aggressive activity with fresh counterparties
            burst_start = START + timedelta(days=dormant_day, hours=rng.randrange(12))
            for k in range(25 + rng.randrange(15)):
                ts = burst_start + timedelta(minutes=rng.randrange(0, 720))
                victim = _addr("victim", rng.randrange(10_000))
                yield from emit(
                    ts, EventType.TRANSACTION, victim, d,
                    value_wei=int(rng.lognormvariate(2.0, 1.0) * 1e18),
                    attrs_pattern="drain_in",
                )
                yield from emit(
                    ts + timedelta(seconds=30 + rng.randrange(600)),
                    EventType.TRANSACTION, d, rng.choice(exch),
                    value_wei=int(rng.lognormvariate(2.0, 1.0) * 1e18),
                    attrs_pattern="drain_out",
                )

        # 6. ANOMALY TYPE B - wash-trading pairs: ping-pong transfers,
        #    constant amounts, metronomic timing.
        a, b = wash
        t = START + timedelta(days=20)
        amt = int(5.0 * 1e18)
        i = 0
        while t < END:
            src, dst = (a, b) if i % 2 == 0 else (b, a)
            yield from emit(
                t, EventType.TRANSACTION, src, dst,
                value_wei=amt, gas=21000, attrs_pattern="wash_loop",
            )
            i += 1
            t += timedelta(hours=2, minutes=rng.randrange(-5, 6))

        # 7. ANOMALY TYPE C - retail wallet 0 has a volume spike in the last week
        w = retail[0]
        spike_start = END - timedelta(days=6)
        t = spike_start
        while t < END:
            yield from emit(
                t, EventType.TRANSACTION, w, rng.choice(exch),
                value_wei=int(rng.lognormvariate(6.0, 0.4) * 1e18),  # ~400 ETH vs ~2 usual
            )
            t += timedelta(minutes=rng.randrange(30, 90))
