import json
from datetime import datetime, timezone

class JSONLogger:
    def __init__(self, identifier):
        self.identifier = identifier

    def log(self, **kwargs):
        label = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        entry = {"label": label}
        entry.update(kwargs)
        out = json.dumps(entry)
        print(out, flush=True)

logger = JSONLogger("runner")
