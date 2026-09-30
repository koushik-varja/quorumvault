import contextvars,json,logging
from datetime import datetime,timezone
correlation_id_var=contextvars.ContextVar('correlation_id',default=None)
class JsonFormatter(logging.Formatter):
    def format(self,record):
        payload={'timestamp':datetime.now(timezone.utc).isoformat(),'level':record.levelname,'logger':record.name,'message':record.getMessage()}
        cid=correlation_id_var.get()
        if cid:payload['correlation_id']=cid
        for key in ('method','path','status_code','duration_ms'):
            if hasattr(record,key):payload[key]=getattr(record,key)
        return json.dumps(payload,separators=(',',':'))
def configure_logging()->None:
    root=logging.getLogger();root.setLevel(logging.INFO);root.handlers.clear();h=logging.StreamHandler();h.setFormatter(JsonFormatter());root.addHandler(h)
