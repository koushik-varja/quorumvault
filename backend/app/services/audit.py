from sqlalchemy.orm import Session
from ..models import AuditEvent
from ..logging_config import correlation_id_var
def record(db:Session,event_type:str,message:str,actor_id:str|None=None,correlation_id:str|None=None)->None:
    db.add(AuditEvent(actor_id=actor_id,event_type=event_type,message=message,correlation_id=correlation_id or correlation_id_var.get()))
