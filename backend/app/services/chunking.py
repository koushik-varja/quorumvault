from collections.abc import Iterator
from typing import BinaryIO

def iter_chunks(stream: BinaryIO, chunk_size: int) -> Iterator[tuple[int, bytes]]:
    if chunk_size <= 0:
        raise ValueError('chunk_size must be positive')
    index = 0
    while True:
        data = stream.read(chunk_size)
        if not data:
            break
        yield index, data
        index += 1
