"""Sawti 3.0 entry point.  python app.py [--simulate]"""
import os
import socket
import sys

if "--simulate" in sys.argv:
    os.environ["SAWTI_SIMULATE"] = "1"

from sawti import VERSION  # noqa: E402
from sawti.server import PORT, create_app  # noqa: E402
from sawti.studio import Studio  # noqa: E402


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    if port_busy(PORT):
        print(f"Sawti is already running: http://127.0.0.1:{PORT}")
        return 0
    studio = Studio()
    studio.lifecycle.install_handlers()
    app = create_app(studio)
    print(f"Sawti {VERSION}{' (simulation)' if studio.audio.simulated else ''}: http://127.0.0.1:{PORT}", flush=True)
    try:
        app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)
    finally:
        studio.power_off()
    return 0


if __name__ == "__main__":
    sys.exit(main())
