from fastapi.testclient import TestClient
from sqlalchemy import select
from app import models
from app.db import Base,SessionLocal,engine
from app.main import app
from app.models import LogicalFile,User

def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

def register(client,email):
    r=client.post('/api/auth/register',json={'email':email,'password':'very-strong-password'});assert r.status_code==200;return r.json()['access_token']

def test_file_ownership_hides_another_users_file():
    with TestClient(app) as c:
        token_a=register(c,'a@example.com');token_b=register(c,'b@example.com')
        with SessionLocal() as db:
            a=db.scalar(select(User).where(User.email=='a@example.com'));f=LogicalFile(owner_id=a.id,name='secret.bin');db.add(f);db.commit();fid=f.id
        assert c.get(f'/api/files/{fid}',headers={'Authorization':f'Bearer {token_a}'}).status_code==200
        assert c.get(f'/api/files/{fid}',headers={'Authorization':f'Bearer {token_b}'}).status_code==404

def test_upload_session_status_is_resumable():
    with TestClient(app) as c:
        token=register(c,'continue@example.com');headers={'Authorization':f'Bearer {token}'}
        payload={'file_name':'continue.bin','expected_size':3,'content_type':'application/octet-stream','chunks':[{'index':0,'hash':'a'*64,'size':3}]}
        r=c.post('/api/uploads/sessions',headers=headers,json=payload);assert r.status_code==200;sid=r.json()['session_id'];assert r.json()['missing_chunks']==[0]
        status=c.get(f'/api/uploads/sessions/{sid}',headers=headers);assert status.status_code==200 and status.json()['missing_chunks']==[0]
