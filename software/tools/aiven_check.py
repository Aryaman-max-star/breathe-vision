"""Check the Aiven connection from your laptop or the board:

    python tools/aiven_check.py
Reads AIVEN_PG_URI from python/config/.env and ca.pem from python/config/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
from breathe import config, store  # noqa: E402

cfg = config.load()
s = store.Store(cfg, start_sync=False)
if not s.enabled:
    sys.exit("Not configured: " + str(s.last_error))
with s.connect() as conn:
    s._ensure_schema(conn)
    print("connected:", conn.execute("SELECT version()").fetchone()[0])
    print("TLS:", conn.execute("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()").fetchone())
    print("tables:", [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")])
print("AIVEN OK")
