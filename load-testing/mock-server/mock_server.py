#!/usr/bin/env python3
"""
UgandaConnect mock API: a stand-in for the real backend that implements the
API contract the JMeter plan targets (see ../API_CONTRACT.md).

Use it to dry-run / debug the JMeter plan, and to run the CI smoke test,
before the real backend is deployed. It is NOT a performance target: its
numbers say nothing about the real system.

    python3 mock_server.py --port 8080 [--latency-ms 20-150] [--error-rate 0.0]

Stdlib only, no dependencies.
"""
import argparse
import json
import random
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = "/api/v1"
TOKENS = {}            # token -> user
STORE = {"solar": {}, "appointments": {}, "payments": {}, "issues": {}}
LOCK = threading.Lock()
CFG = {"lat": (20, 150), "err": 0.0}


class ApiError(Exception):
    def __init__(self, status, code, msg):
        super().__init__(msg)
        self.status, self.code, self.msg = status, code, msg


def need(body, *fields):
    missing = [f for f in fields if body.get(f) in (None, "")]
    if missing:
        raise ApiError(400, "VALIDATION_ERROR", f"missing fields: {', '.join(missing)}")


def rid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ---------------------------------------------------------------- handlers --
def login(req):
    b = req["body"]
    need(b, "phone", "password")
    if not re.fullmatch(r"256\d{9}", str(b["phone"])):
        raise ApiError(400, "VALIDATION_ERROR", "phone must be 256XXXXXXXXX")
    tok = uuid.uuid4().hex + uuid.uuid4().hex
    user = {"id": rid("USR"), "phone": b["phone"], "name": "Test Citizen", "district": "Kampala"}
    with LOCK:
        TOKENS[tok] = user
    return 200, {"token": tok, "refreshToken": uuid.uuid4().hex, "expiresIn": 3600, "user": user}


def logout(req):
    with LOCK:
        TOKENS.pop(req["token"], None)
    return 200, {"status": "LOGGED_OUT"}


def home(req):
    return 200, {"user": req["user"],
                 "quickAccess": ["HEALTH", "EDUCATION", "SOLAR", "BILLS"],
                 "recentActivity": [{"type": "UNEB_RESULT", "label": "UCE 2024", "viewedAt": "2026-11-10T09:12:00Z"}],
                 "unreadNotifications": random.randint(0, 9)}


def services(req):
    items = [{"id": "SOLAR", "name": "Solar subsidies", "agency": "REA"},
             {"id": "HEALTH", "name": "Hospital appointments", "agency": "Ministry of Health"},
             {"id": "UNEB", "name": "Exam results", "agency": "UNEB"},
             {"id": "UMEME", "name": "Electricity bills", "agency": "UMEME"},
             {"id": "NWSC", "name": "Water bills", "agency": "NWSC"},
             {"id": "KCCA", "name": "Report an issue", "agency": "KCCA"}]
    cat = req["q"].get("category")
    if cat:
        items = [s for s in items if s["id"] == cat] or items
    return 200, {"services": items, "total": len(items)}


def search(req):
    q = req["q"].get("q", "")
    if not q:
        raise ApiError(400, "VALIDATION_ERROR", "q is required")
    return 200, {"query": q, "results": [{"id": "SOLAR", "name": "Solar subsidies", "score": 0.91}], "total": 1}


def notifications(req):
    return 200, {"items": [{"id": rid("NTF"), "title": "Your application was received", "read": False}],
                 "page": int(req["q"].get("page", 1)), "unread": 1}


def solar_packages(req):
    d = req["q"].get("district")
    if not d:
        raise ApiError(400, "VALIDATION_ERROR", "district is required")
    return 200, {"district": d, "packages": [
        {"id": f"PKG-{w}W", "name": f"Solar Home System {w}W", "capacityWatts": w,
         "price": w * 9000, "subsidyPercent": 60 if w <= 100 else 40} for w in (50, 100, 200, 300)]}


def solar_package(req, pid):
    w = int(re.sub(r"\D", "", pid) or 50)
    return 200, {"id": pid, "name": f"Solar Home System {w}W", "capacityWatts": w, "price": w * 9000,
                 "subsidyPercent": 60 if w <= 100 else 40,
                 "vendors": [{"id": "VND-01", "name": "Approved Vendor A"}]}


def solar_eligibility(req):
    n = req["q"].get("nin", "")
    if len(n) != 14:
        raise ApiError(400, "VALIDATION_ERROR", "nin must be 14 characters")
    ok = random.random() < 0.8
    return 200, {"nin": n, "eligible": ok, "reason": "ELIGIBLE" if ok else "ALREADY_BENEFITED"}


def solar_apply(req):
    b = req["body"]
    need(b, "nin", "packageId", "district", "village", "householdSize", "monthlyIncome", "idempotencyKey")
    app = {"applicationId": rid("SOL"), "referenceNo": rid("REA"), "status": "SUBMITTED",
           "packageId": b["packageId"]}
    with LOCK:
        STORE["solar"][app["applicationId"]] = app
    return 201, app


def solar_status(req, aid):
    app = STORE["solar"].get(aid)
    if not app:
        raise ApiError(404, "NOT_FOUND", "application not found")
    return 200, {**app, "status": random.choice(["SUBMITTED", "UNDER_REVIEW"])}


def facilities(req):
    d = req["q"].get("district")
    if not d:
        raise ApiError(400, "VALIDATION_ERROR", "district is required")
    return 200, {"district": d, "specialty": req["q"].get("specialty"), "facilities": [
        {"id": f"HF-{random.randint(1000, 9999)}", "name": f"{d} Health Centre {lvl}", "level": lvl, "district": d}
        for lvl in ("IV", "III", "II")]}


def facility(req, fid):
    return 200, {"id": fid, "name": "Health Centre IV", "level": "IV",
                 "services": ["GENERAL", "MATERNITY", "PAEDIATRICS"], "openHours": "08:00-17:00"}


def slots(req, fid):
    date = req["q"].get("date")
    if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ApiError(400, "VALIDATION_ERROR", "date must be yyyy-MM-dd")
    return 200, {"facilityId": fid, "date": date, "slots": [
        {"slotId": f"SLT-{uuid.uuid4().hex[:8]}", "time": f"{h:02d}:00", "available": True} for h in (8, 9, 10, 11, 14, 15)]}


def book(req):
    b = req["body"]
    need(b, "facilityId", "slotId", "patientNin", "reason", "idempotencyKey")
    appt = {"appointmentId": rid("APT"), "ticketNo": rid("MOH"), "status": "CONFIRMED", "facilityId": b["facilityId"]}
    with LOCK:
        STORE["appointments"][appt["appointmentId"]] = appt
    return 201, appt


def my_appointments(req):
    return 200, {"appointments": list(STORE["appointments"].values())[-3:], "total": 3}


def exams(req):
    return 200, {"exams": [{"code": "PLE", "name": "Primary Leaving Examination"},
                           {"code": "UCE", "name": "Uganda Certificate of Education"},
                           {"code": "UACE", "name": "Uganda Advanced Certificate of Education"}]}


def results(req):
    q = req["q"]
    for f in ("indexNumber", "year", "level"):
        if not q.get(f):
            raise ApiError(400, "VALIDATION_ERROR", f"{f} is required")
    if not re.fullmatch(r"U\d{4}/\d{3}", q["indexNumber"]):
        raise ApiError(400, "VALIDATION_ERROR", "bad index number")
    subj = {"PLE": ["ENG", "MTC", "SST", "SCI"], "UCE": ["ENG", "MTC", "BIO", "CHE", "PHY", "HIS", "GEO", "CRE"],
            "UACE": ["GP", "MATH", "PHY", "CHEM"]}[q["level"]]
    return 200, {"indexNumber": q["indexNumber"], "year": int(q["year"]), "level": q["level"],
                 "candidateName": "TEST CANDIDATE", "division": random.choice(["1", "2", "3", "4"]),
                 "subjects": [{"code": s, "grade": random.choice(["D1", "D2", "C3", "C4", "C5", "C6"])} for s in subj]}


def slip_request(req):
    b = req["body"]
    need(b, "indexNumber", "year", "level", "deliveryMsisdn", "idempotencyKey")
    return 201, {"requestId": rid("SLP"), "status": "QUEUED", "indexNumber": b["indexNumber"]}


def providers(req):
    return 200, {"providers": [{"code": "UMEME", "name": "UMEME Yaka / Postpaid"},
                               {"code": "NWSC", "name": "National Water & Sewerage"}]}


def validate_account(req):
    b = req["body"]
    need(b, "provider", "accountNumber")
    if b["provider"] not in ("UMEME", "NWSC"):
        raise ApiError(400, "VALIDATION_ERROR", "unknown provider")
    return 200, {"valid": True, "provider": b["provider"], "accountNumber": b["accountNumber"],
                 "accountName": "TEST CUSTOMER", "outstandingBalance": random.randrange(0, 400_000, 500)}


def pay(req):
    b = req["body"]
    need(b, "provider", "accountNumber", "amount", "msisdn", "channel", "idempotencyKey")
    if int(b["amount"]) <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "amount must be positive")
    p = {"paymentId": rid("PAY"), "status": "PENDING", "provider": b["provider"], "amount": int(b["amount"])}
    with LOCK:
        STORE["payments"][p["paymentId"]] = p
    return 202, p


def payment_status(req, pid):
    p = STORE["payments"].get(pid)
    if not p:
        raise ApiError(404, "NOT_FOUND", "payment not found")
    st = random.choices(["SUCCESS", "PENDING", "FAILED"], [0.85, 0.13, 0.02])[0]
    out = {**p, "status": st}
    if st == "SUCCESS" and p["provider"] == "UMEME":
        out["token"] = "-".join(f"{random.randint(0, 9999):04d}" for _ in range(5))
    return 200, out


def payment_history(req):
    return 200, {"payments": list(STORE["payments"].values())[-5:], "page": int(req["q"].get("page", 1))}


def categories(req):
    return 200, {"categories": [{"id": c, "name": c.replace("_", " ").title()} for c in
                                ("ROADS", "DRAINAGE", "STREET_LIGHTING", "GARBAGE", "WALKWAYS", "OTHER")]}


def nearby(req):
    q = req["q"]
    for f in ("lat", "lng"):
        if not q.get(f):
            raise ApiError(400, "VALIDATION_ERROR", f"{f} is required")
    return 200, {"issues": [{"id": rid("ISS"), "title": "Pothole", "status": random.choice(["OPEN", "IN_PROGRESS"]),
                             "upvotes": random.randint(0, 40)} for _ in range(5)]}


def issue(req, iid):
    return 200, {"id": iid, "title": "Pothole", "status": "OPEN", "category": "ROADS",
                 "updates": [{"at": "2026-11-09T10:00:00Z", "note": "Assigned to Nakawa works team"}]}


def report_issue(req):
    b = req["body"]
    need(b, "categoryId", "title", "description", "lat", "lng", "division", "idempotencyKey")
    iss = {"issueId": rid("ISS"), "trackingNo": rid("KCCA"), "status": "OPEN"}
    with LOCK:
        STORE["issues"][iss["issueId"]] = iss
    return 201, iss


ROUTES = [  # (method, regex, handler, auth_required)
    ("GET", r"/status", lambda r: (200, {"status": "UP", "version": "mock"}), False),
    ("POST", r"/auth/login", login, False),
    ("POST", r"/auth/logout", logout, True),
    ("GET", r"/home", home, True),
    ("GET", r"/services", services, True),
    ("GET", r"/services/search", search, True),
    ("GET", r"/notifications", notifications, True),
    ("GET", r"/solar/packages", solar_packages, True),
    ("GET", r"/solar/packages/([\w-]+)", solar_package, True),
    ("GET", r"/solar/eligibility", solar_eligibility, True),
    ("POST", r"/solar/applications", solar_apply, True),
    ("GET", r"/solar/applications/([\w-]+)", solar_status, True),
    ("GET", r"/health/facilities", facilities, True),
    ("GET", r"/health/facilities/([\w-]+)", facility, True),
    ("GET", r"/health/facilities/([\w-]+)/slots", slots, True),
    ("POST", r"/health/appointments", book, True),
    ("GET", r"/health/appointments", my_appointments, True),
    ("GET", r"/uneb/exams", exams, True),
    ("GET", r"/uneb/results", results, True),
    ("POST", r"/uneb/result-slips", slip_request, True),
    ("GET", r"/bills/providers", providers, True),
    ("POST", r"/bills/accounts/validate", validate_account, True),
    ("POST", r"/bills/payments", pay, True),
    ("GET", r"/bills/payments", payment_history, True),
    ("GET", r"/bills/payments/([\w-]+)", payment_status, True),
    ("GET", r"/issues/categories", categories, True),
    ("GET", r"/issues/nearby", nearby, True),
    ("GET", r"/issues/([\w-]+)", issue, True),
    ("POST", r"/issues", report_issue, True),
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # keep the console quiet under load
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("X-Request-ID"):
            self.send_header("X-Request-ID", self.headers["X-Request-ID"])
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        u = urlparse(self.path)
        path = u.path[len(BASE):] if u.path.startswith(BASE) else None
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        time.sleep(random.uniform(*CFG["lat"]) / 1000)
        try:
            if path is None:
                raise ApiError(404, "NOT_FOUND", "unknown base path")
            for m, rx, fn, auth in ROUTES:
                mt = re.fullmatch(rx, path)
                if not mt or m != method:
                    continue
                if CFG["err"] and random.random() < CFG["err"]:
                    raise ApiError(503, "UPSTREAM_UNAVAILABLE", "injected failure")
                req = {"q": {k: v[0] for k, v in parse_qs(u.query).items()}, "body": {}}
                if raw:
                    if "application/json" not in (self.headers.get("Content-Type") or ""):
                        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "send application/json")
                    try:
                        req["body"] = json.loads(raw)
                    except json.JSONDecodeError:
                        raise ApiError(400, "BAD_JSON", "body is not valid JSON")
                if auth:
                    h = self.headers.get("Authorization", "")
                    tok = h[7:] if h.startswith("Bearer ") else ""
                    if tok not in TOKENS:
                        raise ApiError(401, "UNAUTHORIZED", "missing or invalid token")
                    req["token"], req["user"] = tok, TOKENS[tok]
                status, payload = fn(req, *mt.groups())
                return self._send(status, payload)
            raise ApiError(404, "NOT_FOUND", f"no route {method} {path}")
        except ApiError as e:
            self._send(e.status, {"error": {"code": e.code, "message": e.msg}})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--latency-ms", default="20-150")
    ap.add_argument("--error-rate", type=float, default=0.0)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.latency_ms.split("-"))
    CFG.update(lat=(lo, hi), err=a.error_rate)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    srv.daemon_threads = True
    print(f"UgandaConnect mock API on http://localhost:{a.port}{BASE}  latency={lo}-{hi}ms error_rate={a.error_rate}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
