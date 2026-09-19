"""`python -m app` starts the server and prints the addresses to hand out."""
from __future__ import annotations

import uvicorn

from .config import load_settings
from .main import lan_ip


def main() -> None:
    s = load_settings()
    print(f"Artificer's Manual  ->  http://localhost:{s.port}   (this machine)")
    print(f"                        http://{lan_ip()}:{s.port}   (others on your network)")
    if not s.table_password:
        print("no table_password set: anyone who can reach this address can open every sheet")
    if not s.dm_password:
        print("no dm_password set: only this machine is the DM")
    uvicorn.run("app.main:create_app", factory=True, host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
