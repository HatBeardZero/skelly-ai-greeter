import json, sys
a = {d["address"] for d in json.load(open(sys.argv[1]))["devices"]}
for d in json.load(open(sys.argv[2]))["devices"]:
    if d["address"] not in a:
        print(d)
