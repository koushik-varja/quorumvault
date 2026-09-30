import hashlib

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class StreamingSHA256:
    def __init__(self): self._h = hashlib.sha256()
    def update(self, data: bytes): self._h.update(data)
    def hexdigest(self) -> str: return self._h.hexdigest()
