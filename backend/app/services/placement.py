import bisect
import hashlib
from dataclasses import dataclass

@dataclass(frozen=True)
class RingPoint:
    value: int
    node_id: str

class ConsistentHashRing:
    def __init__(self, node_ids: list[str], virtual_nodes: int = 64):
        if virtual_nodes < 1:
            raise ValueError('virtual_nodes must be >= 1')
        self.virtual_nodes = virtual_nodes
        self._points: list[RingPoint] = []
        for node_id in sorted(set(node_ids)):
            for vnode in range(virtual_nodes):
                value = self._hash(f'{node_id}#{vnode}')
                self._points.append(RingPoint(value, node_id))
        self._points.sort(key=lambda p: p.value)
        self._values = [p.value for p in self._points]

    @staticmethod
    def _hash(value: str) -> int:
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big')

    def replicas(self, key: str, count: int) -> list[str]:
        if not self._points or count <= 0:
            return []
        count = min(count, len({p.node_id for p in self._points}))
        idx = bisect.bisect_left(self._values, self._hash(key))
        chosen: list[str] = []
        seen: set[str] = set()
        for offset in range(len(self._points)):
            p = self._points[(idx + offset) % len(self._points)]
            if p.node_id not in seen:
                chosen.append(p.node_id)
                seen.add(p.node_id)
                if len(chosen) == count:
                    break
        return chosen
