import json, time, urllib.request
from skelly_ultra_pkg import commands as c

frame = c.query_volume().hex()

def post(path, body):
    req = urllib.request.Request("http://localhost:8765" + path,
        json.dumps(body).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=15).read().decode()

while True:
    try:
        print(time.strftime("%T"), post("/ble/send_command", {"command": frame}))
    except Exception as e:
        print(time.strftime("%T"), "failed:", e)
    time.sleep(20)
