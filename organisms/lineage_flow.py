from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LineageRecord:
    org_id: str
    species: str
    born_turn: int
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    generation: int = 0
    mutations: List[str] = field(default_factory=list)
    genes: Dict[str, float] = field(default_factory=dict)
    died_turn: Optional[int] = None
    cause_of_death: Optional[str] = None
    meals: int = 0


class LineageAndFlowTracker:
    """Tracks family trees, gene mutations, and energy flow across roles."""

    FLOW_LINKS: Tuple[Tuple[str, str], ...] = (
        ("environment", "producer"),
        ("producer", "herbivore"),
        ("herbivore", "predator"),
        ("producer", "decomposer"),
        ("herbivore", "decomposer"),
        ("predator", "decomposer"),
        ("decomposer", "environment"),
    )

    def __init__(self) -> None:
        self.records: Dict[str, LineageRecord] = {}
        self.energy_flows: Dict[Tuple[str, str], float] = defaultdict(float)
        self.turn_flows: Dict[Tuple[str, str], float] = defaultdict(float)

    def reset(self) -> None:
        self.records.clear()
        self.energy_flows.clear()
        self.turn_flows.clear()

    def begin_turn(self) -> None:
        self.turn_flows.clear()

    @staticmethod
    def _is_alive(org: Any) -> bool:
        status = getattr(org, "status", None)
        if status is not None:
            return status == "Alive"
        return bool(getattr(org, "alive", True))

    @staticmethod
    def _org_key(org: Any) -> str:
        for attr in ("uid", "id", "name"):
            val = getattr(org, attr, None)
            if val is not None:
                return str(val)
        return str(id(org))

    @staticmethod
    def classify_role(org: Any) -> str:
        species = str(getattr(org, "species", getattr(org, "name", ""))).lower()
        try:
            from data.species import SPECIES
            sp_name = getattr(org, "species", getattr(org, "name", ""))
            if sp_name in SPECIES:
                sp_type = str(SPECIES[sp_name].get("type", "")).lower()
                if sp_type == "producer":
                    return "producer"
                if sp_type in ("decomposer", "scavenger", "recycler"):
                    return "decomposer"
                if sp_type == "predator":
                    return "predator"
                if sp_type == "consumer":
                    return "herbivore"
        except Exception:
            pass

        diet = str(getattr(org, "diet", getattr(org, "role", ""))).lower()
        if "photo" in diet or "plant" in diet or "prod" in diet or species in ("flora", "moss", "crystalis", "verdant"):
            return "producer"
        if "decomp" in diet or "detrit" in diet or "scav" in diet or species in ("mycel", "nullborn"):
            return "decomposer"
        if "carn" in diet or "pred" in diet or "hunt" in diet or species in ("ravager", "skyrender"):
            return "predator"
        return "herbivore"

    @staticmethod
    def extract_genes(org: Any) -> Dict[str, float]:
        raw = getattr(org, "genes", None)
        if isinstance(raw, dict):
            return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
        out: Dict[str, float] = {}
        for attr in ("speed_gene", "sense_gene", "metabolism_gene", "size_gene"):
            val = getattr(org, attr, None)
            if isinstance(val, (int, float)):
                out[attr.replace("_gene", "")] = float(val)
        return out

    def register_birth(
        self,
        org: Any,
        turn: int,
        parents: Optional[List[Any]] = None,
        mutations: Optional[List[str]] = None,
    ) -> LineageRecord:
        org_id = self._org_key(org)
        species = str(getattr(org, "species", getattr(org, "name", "Unknown")))
        genes = self.extract_genes(org)
        parent_ids: List[str] = []
        max_gen = -1

        for p in parents or []:
            pid = self._org_key(p)
            parent_ids.append(pid)
            if pid in self.records:
                max_gen = max(max_gen, self.records[pid].generation)
                if org_id not in self.records[pid].child_ids:
                    self.records[pid].child_ids.append(org_id)

        mut_list = list(mutations or [])
        if not mut_list and parents:
            p_genes = self.extract_genes(parents[0])
            for g_name, g_val in genes.items():
                if g_name in p_genes and abs(g_val - p_genes[g_name]) > 1e-4:
                    mut_list.append(f"{g_name}: {p_genes[g_name]:.2f} -> {g_val:.2f}")

        if org_id in self.records:
            rec = self.records[org_id]
            rec.genes = genes
            return rec

        rec = LineageRecord(
            org_id=org_id,
            species=species,
            born_turn=turn,
            parent_ids=parent_ids,
            generation=max_gen + 1 if max_gen >= 0 else 0,
            mutations=mut_list,
            genes=genes,
        )
        self.records[org_id] = rec
        return rec

    def record_meal(self, eater: Any, amount: float = 1.0, source_role: Optional[str] = None) -> None:
        org_id = self._org_key(eater)
        if org_id not in self.records:
            self.register_birth(eater, turn=0)
        self.records[org_id].meals += 1
        dst = self.classify_role(eater)
        src = source_role or {
            "herbivore": "producer",
            "predator": "herbivore",
            "decomposer": "herbivore",
            "producer": "environment",
        }.get(dst, "environment")
        self.record_energy(src, dst, max(0.0, float(amount)))

    def record_death(self, org: Any, turn: int, cause: str = "starvation") -> None:
        org_id = self._org_key(org)
        if org_id not in self.records:
            self.register_birth(org, turn=turn)
        rec = self.records[org_id]
        if rec.died_turn is None:
            rec.died_turn = turn
            rec.cause_of_death = cause
            role = self.classify_role(org)
            energy = float(getattr(org, "energy", 5.0) or 5.0)
            if role != "decomposer":
                self.record_energy(role, "decomposer", max(1.0, energy * 0.5))

    def record_energy(self, src: str, dst: str, amount: float) -> None:
        amt = max(0.0, float(amount))
        if amt <= 0.0:
            return
        key = (src, dst)
        self.energy_flows[key] += amt
        self.turn_flows[key] += amt

    def sync_from_world(self, world: Any, turn: int) -> None:
        """Best-effort sync when the simulation already maintains organisms/events."""
        orgs = getattr(world, "organisms", None)
        if isinstance(orgs, (list, tuple)):
            for org in orgs:
                if self._is_alive(org):
                    oid = self._org_key(org)
                    if oid not in self.records:
                        self.register_birth(org, turn=turn)
                    else:
                        self.records[oid].genes = self.extract_genes(org)

    def get_lineage_summary(self, org: Any) -> Dict[str, Any]:
        org_id = self._org_key(org)
        rec = self.records.get(org_id)
        if not rec:
            rec = self.register_birth(org, turn=0)
        parents = [self.records[pid] for pid in rec.parent_ids if pid in self.records]
        children = [self.records[cid] for cid in rec.child_ids if cid in self.records]
        return {
            "record": rec,
            "parents": parents,
            "children": children,
        }

    def get_flow_totals(self, cumulative: bool = True) -> Dict[Tuple[str, str], float]:
        source = self.energy_flows if cumulative else self.turn_flows
        return {link: float(source.get(link, 0.0)) for link in self.FLOW_LINKS}
