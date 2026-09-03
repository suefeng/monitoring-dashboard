#!/usr/bin/env python3
"""
Local Dev Server Dashboard
---------------------------
Runs a tiny web server on your machine that shows the live status of your
local dev servers (Angular, Tomcat, React, Spring Boot, databases, etc.)
by parsing `lsof` for everything currently listening locally, then matching
known ports/names and also listing anything else it finds.

Usage:
    python3 dashboard.py [--port 5055]

Then open http://localhost:5055/ in your browser.

Customize the SERVICES list below to match what you actually run.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import psutil  # optional, used as a fallback if `lsof` isn't available
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ---------------------------------------------------------------------------
# Known servers to call out by name. A service can list multiple candidate
# ports (e.g. if you've moved it off its default). Edit freely.
# ---------------------------------------------------------------------------
SERVICES = [
    {"name": "Angular App1 Name",   "host": "localhost", "ports": [3000]},
    {"name": "Angular App2 Name",   "host": "localhost", "ports": [3002]},
    {"name": "Angular App3 Name",   "host": "localhost", "ports": [4200]},
    {"name": "Tomcat App1 Name",    "host": "localhost", "ports": [8080]},
    {"name": "Tomcat App2 Name",    "host": "localhost", "ports": [8081]},
    {"name": "Tomcat App3 Name",    "host": "localhost", "ports": [8083]},
    {"name": "MySQL",               "host": "localhost", "ports": [3306]},
    {"name": "MariaDB",             "host": "localhost", "ports": [3307]},
    {"name": "PostgreSQL",          "host": "localhost", "ports": [5432]},
]

# Anything listening on these ports is filtered out of "All listening ports"
# below, since it's noise (editor language servers, Wolfram kernel, etc.)
# rather than something you'd call a "server". Remove entries to see them.
IGNORE_PROCESS_NAMES = {"ControlCe", "ARDAgent"}

# Ports to probe for running webapps via the Tomcat manager API.
TOMCAT_PORTS = {8080, 8081, 8083, 9000}

def full_process_names(pids):
    """Look up untruncated command names for a set of PIDs via `ps`.

    `lsof`'s COMMAND column is capped at ~9 characters, so anything with a
    longer name (e.g. "Code Helper (Renderer)") comes back chopped. `ps -o
    comm=` returns the full path/name for each PID in one shot.
    """
    pids = [p for p in pids if p]
    if not pids or not shutil.which("ps"):
        return {}
    try:
        out = subprocess.run(
            ["ps", "-o", "pid=,comm=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return {}

    names = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        pid_str, comm = parts
        try:
            names[int(pid_str)] = os.path.basename(comm.strip())
        except ValueError:
            continue
    return names

def tomcat_running_webapps(port):
    """Parse `curl -u admin:password http://localhost:${port}/manager/text/list`."""
    if not shutil.which("curl"):
        return None
    url = f"http://localhost:{port}/manager/text/list"
    try:
        # set your username and password here for Tomcat manager
        out = subprocess.run(
            ["curl", "-s", "-u", "admin:password", url],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return None

    #OK - Listed applications for virtual host localhost
    #/:running:0:ROOT
    #/AccountAPI:running:0:AccountAPI
    results = {}
    for line in out.splitlines()[1:]:  # skip "OK - Listed applications..." line
        parts = line.split(":")
        if len(parts) < 4:
            continue
        webapp, status = parts[3], parts[1]
        if webapp != "ROOT" and webapp != "manager":
            results[webapp] = {"webapp": webapp, "status": status}
        if webapp == "webengine":
            storeAPIsStatus = erp_store_apis_running()
            results["StoreAPIs"] = {"webapp": "StoreAPIs", "status": storeAPIsStatus}
    return list(results.values())

def erp_store_apis_running():
    """Parse `curl http://localhost:9000/webengine/active/StoreAPIs`."""
    status = "not running"
    if not shutil.which("curl"):
        return None
    url = f"http://localhost:9000/webengine/active/StoreAPIs"
    try:
        out = subprocess.run(
            ["curl", "-s", url],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return None

    for line in out.splitlines():  # skip "OK - Listed applications..." line
        parts = line.split("</li>")
        if len(parts) < 41:
            status = "not running"
        else:
            status = "running"

    return status

def listening_ports_lsof():
    """Parse `lsof -iTCP -sTCP:LISTEN -P -n` into a list of listeners."""
    if not shutil.which("lsof"):
        return None
    try:
        out = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return None

    results = {}
    for line in out.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 9:
            continue
        proc, pid, addr = parts[0], parts[1], parts[8]
        m = re.search(r":(\d+)$", addr)
        if not m:
            continue
        port = int(m.group(1))
        key = (pid, port)
        proc = proc.replace("\\x20", " ")
        tomcat_webapps = None
        if port in TOMCAT_PORTS:
            tomcat_webapps = tomcat_running_webapps(port)

        results[key] = {"process": proc, "pid": int(pid), "port": port, "tomcat_webapps": tomcat_webapps}

    full_names = full_process_names({r["pid"] for r in results.values()})
    for r in results.values():
        r["process"] = full_names.get(r["pid"], r["process"])

    return list(results.values())


def listening_ports_psutil():
    if not HAS_PSUTIL:
        return None
    results = {}
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                pid = conn.pid
                name = None
                if pid:
                    try:
                        name = psutil.Process(pid).name()
                    except psutil.Error:
                        pass
                results[(pid, conn.laddr.port)] = {
                    "process": name, "pid": pid, "port": conn.laddr.port,
                }
    except (psutil.Error, PermissionError):
        return None
    return list(results.values())


def all_listening_ports():
    listeners = listening_ports_lsof()
    if listeners is None:
        listeners = listening_ports_psutil() or []
    listeners = [l for l in listeners if l["process"] not in IGNORE_PROCESS_NAMES]
    listeners.sort(key=lambda l: l["port"])
    return listeners


def build_status():
    listeners = all_listening_ports()
    by_port = {}
    for l in listeners:
        by_port.setdefault(l["port"], l)

    known = []
    matched_ports = set()
    for svc in SERVICES:
        hit = next((p for p in svc["ports"] if p in by_port), None)
        up = hit is not None
        if up:
            matched_ports.add(hit)
        proc = by_port.get(hit) if hit else None
        known.append({
            "name": svc["name"],
            "port": hit if hit else "/".join(str(p) for p in svc["ports"]),
            "up": up,
            "pid": proc["pid"] if proc else None,
            "process": proc["process"] if proc else None,
            "tomcat_webapps": proc["tomcat_webapps"] if proc else None,
        })

    other = [l for l in listeners if l["port"] not in matched_ports]
    return {"known": known, "other": other}


STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/dashboard.js": ("dashboard.js", "application/javascript"),
    "/styles.css": ("styles.css", "text/css"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _send(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(build_status()).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[self.path]
            try:
                with open(os.path.join(STATIC_DIR, filename), "rb") as f:
                    body = f.read()
                self._send(200, content_type, body)
            except OSError:
                self._send(404, "text/plain", b"Not found")
        else:
            self._send(404, "text/plain", b"Not found")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5055, help="Port to serve the dashboard on")
    args = parser.parse_args()

    if not shutil.which("lsof") and not HAS_PSUTIL:
        print("Warning: neither `lsof` nor `psutil` is available — port detection won't work.")
        print("Install psutil with: pip install psutil")

    server = HTTPServer(("localhost", args.port), Handler)
    print(f"Dashboard running at http://localhost:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
