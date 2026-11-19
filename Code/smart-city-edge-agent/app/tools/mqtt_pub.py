#!/usr/bin/env python3
"""Publish test readings to an MQTT broker for the edge-agent MQTT bridge (backend/prod_mqtt.go). Stdlib only.

Examples
  # one reading, payload carries node/metric/ts (the documented schema)
  python3 mqtt_pub.py --host 192.168.1.10 --node SR-AQ-KH03-03 --metric co2 --value 850
  # a ramp: 12 readings, one every 5 s, value 600 -> 1700, device time = now
  python3 mqtt_pub.py --host 127.0.0.1 --node SR-AQ-KH03-03 --metric co2 --value 600 --step 100 --count 12 --every 5
  # a backlog batch of 12 readings 5 min apart ending now (a gateway reconnecting)
  python3 mqtt_pub.py --host 127.0.0.1 --node SR-AQ-KH03-03 --metric co2 --value 600 --count 12 --batch
  # a bare number on .../<node>/<metric> (node and metric from the topic)
  python3 mqtt_pub.py --host 127.0.0.1 --topic sce/SR-AQ-KH03-03/co2 --raw 900

Options --user/--password for brokers with auth, --qos 0|1, --quality good|uncertain|bad, --unit, --firmware.
"""
import argparse
import json
import socket
import struct
import sys
import time


def _str(s):
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def _rem(n):
    out = bytearray()
    while True:
        c = n % 128
        n //= 128
        if n:
            c |= 128
        out.append(c)
        if not n:
            return bytes(out)


def _packet(h, body):
    return bytes([h]) + _rem(len(body)) + body


def _read(sock):
    h = sock.recv(1)
    if not h:
        raise ConnectionError("broker closed the connection")
    n, mul = 0, 1
    while True:
        c = sock.recv(1)[0]
        n += (c & 127) * mul
        if not c & 128:
            break
        mul *= 128
    body = b""
    while len(body) < n:
        chunk = sock.recv(n - len(body))
        if not chunk:
            raise ConnectionError("short packet")
        body += chunk
    return h[0], body


def connect(host, port, client_id, user, password, timeout=10):
    s = socket.create_connection((host, port), timeout=timeout)
    flags = 0x02
    tail = _str(client_id)
    if user:
        flags |= 0x80
        tail += _str(user)
        if password:
            flags |= 0x40
            tail += _str(password)
    s.sendall(_packet(0x10, _str("MQTT") + bytes([4, flags]) + struct.pack("!H", 30) + tail))
    h, body = _read(s)
    if h >> 4 != 2 or len(body) < 2 or body[1] != 0:
        raise ConnectionError("CONNACK refused (code %s)" % (body[1] if len(body) > 1 else "?"))
    return s


def publish(s, topic, payload, qos, pid):
    body = _str(topic) + (struct.pack("!H", pid) if qos else b"") + payload
    s.sendall(_packet(0x30 | (qos << 1), body))
    if qos:
        while True:
            h, b = _read(s)
            if h >> 4 == 4 and struct.unpack("!H", b[:2])[0] == pid:
                return


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--client-id", default="sce-test-pub")
    ap.add_argument("--qos", type=int, choices=[0, 1], default=1)
    ap.add_argument("--topic", default="")
    ap.add_argument("--node", default="SR-AQ-KH03-03")
    ap.add_argument("--metric", default="co2")
    ap.add_argument("--value", type=float, default=850)
    ap.add_argument("--step", type=float, default=0, help="added to the value for each next reading")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--every", type=float, default=0, help="seconds between messages")
    ap.add_argument("--batch", action="store_true", help="one {'readings':[...]} message, 5 min apart, ending now")
    ap.add_argument("--quality", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--firmware", default="")
    ap.add_argument("--ts", type=float, default=0, help="device time of the first reading (default: now)")
    ap.add_argument("--raw", default=None, help="publish this exact payload (e.g. a bare number)")
    a = ap.parse_args()
    topic = a.topic or "sce/%s/%s" % (a.node, a.metric)
    s = connect(a.host, a.port, a.client_id, a.user, a.password)
    pid = 0

    def reading(i, ts):
        r = {"node": a.node, "metric": a.metric, "value": round(a.value + i * a.step, 3), "ts": int(ts)}
        for k in ("quality", "unit", "firmware"):
            if getattr(a, k):
                r[k] = getattr(a, k)
        return r

    msgs = []
    if a.raw is not None:
        msgs = [a.raw.encode()]
    elif a.batch:
        end = a.ts or time.time()
        msgs = [json.dumps({"readings": [reading(i, end - (a.count - 1 - i) * 300) for i in range(a.count)]}).encode()]
    for i in range(len(msgs) if msgs else a.count):
        payload = msgs[i] if msgs else json.dumps(reading(i, (a.ts + i * 300) if a.ts else time.time())).encode()
        pid = pid % 65535 + 1
        publish(s, topic, payload, a.qos, pid)
        print("published %s %s" % (topic, payload.decode()[:200]))
        if a.every and i + 1 < a.count:
            time.sleep(a.every)
    s.sendall(b"\xe0\x00")  # DISCONNECT
    s.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ConnectionError) as e:
        print("mqtt_pub: %s" % e, file=sys.stderr)
        sys.exit(1)
