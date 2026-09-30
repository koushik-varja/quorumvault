import hashlib
import pytest
from app.storage import ChunkStore

def test_put_read_check_and_deduplicate(tmp_path):
    store=ChunkStore(str(tmp_path));data=b'hello distributed storage';h=hashlib.sha256(data).hexdigest()
    first=store.put(h,data);second=store.put(h,data)
    assert first['stored'] is True and second['deduplicated'] is True
    assert store.get(h)==data and store.check(h)['valid'] is True

def test_rejects_wrong_content_address(tmp_path):
    store=ChunkStore(str(tmp_path))
    with pytest.raises(ValueError):store.put('0'*64,b'wrong')

def test_corruption_is_detected_and_never_returned(tmp_path):
    store=ChunkStore(str(tmp_path));data=b'important';h=hashlib.sha256(data).hexdigest();store.put(h,data);store.corrupt(h)
    assert store.check(h)['valid'] is False
    with pytest.raises(ValueError):store.get(h)

def test_delete_is_idempotent(tmp_path):
    store=ChunkStore(str(tmp_path));data=b'x';h=hashlib.sha256(data).hexdigest();store.put(h,data)
    assert store.delete(h) is True and store.delete(h) is False
