import io
from app.services.hashing import sha256_bytes
from app.services.chunking import iter_chunks
from app.services.placement import ConsistentHashRing
from app.auth import hash_password,verify_password

def test_sha256_is_content_address():
    assert sha256_bytes(b'abc')=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert sha256_bytes(b'same')==sha256_bytes(b'same')

def test_chunking_preserves_order_and_reconstructs():
    data=b'abcdefghijklmnopqrstuvwxyz'
    chunks=list(iter_chunks(io.BytesIO(data),5))
    assert [i for i,_ in chunks]==list(range(6))
    assert b''.join(c for _,c in chunks)==data
    assert [len(c) for _,c in chunks]==[5,5,5,5,5,1]

def test_consistent_hash_is_deterministic_and_distinct():
    nodes=['node-1','node-2','node-3','node-4']
    a=ConsistentHashRing(nodes,virtual_nodes=32)
    b=ConsistentHashRing(list(reversed(nodes)),virtual_nodes=32)
    r1=a.replicas('a'*64,3);r2=b.replicas('a'*64,3)
    assert r1==r2
    assert len(r1)==3 and len(set(r1))==3

def test_consistent_hash_limits_replica_count_to_nodes():
    assert len(ConsistentHashRing(['n1','n2']).replicas('x',5))==2

def test_password_hashing_is_salted_and_verifiable():
    a=hash_password('correct horse battery staple')
    b=hash_password('correct horse battery staple')
    assert a!=b
    assert verify_password('correct horse battery staple',a)
    assert not verify_password('wrong',a)
