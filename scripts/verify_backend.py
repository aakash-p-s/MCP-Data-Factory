"""Step 0 backend verification — token, /servers, /audit, /ask"""
import urllib.request, urllib.error, json, sys

KC = "http://localhost:8080/realms/patient-risk/protocol/openid-connect/token"
AGENT = "http://localhost:8500/ask"
REGISTRY = "http://localhost:8600"

# --- token ---
req = urllib.request.Request(
    KC,
    data=b"client_id=patient-risk-agent&client_secret=agent-secret-change-in-prod"
        b"&username=doctor-test&password=test123&grant_type=password&scope=openid",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
try:
    t = json.loads(urllib.request.urlopen(req, timeout=10).read())["access_token"]
    print("TOKEN : OK")
except Exception as e:
    sys.exit(f"TOKEN FAILED: {e}")

def call(url, method="GET", body=None, ct=None):
    hdrs = {"Authorization": f"Bearer {t}"}
    if ct:
        hdrs["Content-Type"] = ct
    r = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=90).read())
    except urllib.error.HTTPError as e:
        return {"HTTP_ERROR": e.code, "body": e.read().decode()[:400]}
    except Exception as e:
        return {"ERROR": str(e)}

# --- 0b /servers ---
servers = call(f"{REGISTRY}/servers")
if isinstance(servers, list):
    print(f"\n0b /servers : {len(servers)} rows")
    for s in servers:
        print(f"  {s['server_name']:<35} status={s['status']}  port={s['port']}")
else:
    print(f"\n0b /servers ERROR: {servers}")

# --- 0c /audit ---
audit = call(f"{REGISTRY}/audit")
if isinstance(audit, list):
    print(f"\n0c /audit   : {len(audit)} rows")
    if audit:
        print(json.dumps(audit[0], indent=2))
    else:
        print("  (empty — run /ask first to generate events)")
else:
    print(f"\n0c /audit ERROR: {audit}")

# --- 0a /ask ---
body = json.dumps({
    "question": "Summarize risk for demo-patient-1",
    "patient_id": "demo-patient-1",
    "purpose_of_access": "routine_review",
}).encode()
print("\n0a /ask     : calling (may take ~15s) ...")
ask = call(AGENT, method="POST", body=body, ct="application/json")
if "answer" in ask:
    print(f"  answer    : {ask['answer'][:300]}")
    print(f"  servers   : {ask.get('servers_called')}")
else:
    print(f"  RESULT    : {ask}")

# --- re-check audit after /ask ---
audit2 = call(f"{REGISTRY}/audit")
if isinstance(audit2, list):
    print(f"\n0c /audit (after /ask): {len(audit2)} rows")
    if audit2:
        print(json.dumps(audit2[0], indent=2))
