"""Tiny TCP relay (laptop): 127.0.0.1:LPORT -> HOST:RPORT. With `adb reverse tcp:9999 tcp:9999` the board reaches the campus API over USB."""
import socket, sys, threading
L, H, R = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
def pipe(a, b, done):
    # half-close (shutdown WR) instead of close: on Windows a full close with unread data sends RST and drops the
    # tail of the response (board saw 30,660 of 31,657 bytes of /nodes). Close both only after both directions end.
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except OSError: pass
    try: b.shutdown(socket.SHUT_WR)
    except OSError: pass
    if done.acquire(blocking=False) is False:
        for s in (a, b):
            try: s.close()
            except OSError: pass
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", L)); srv.listen(32)
while True:
    c, _ = srv.accept()
    try: u = socket.create_connection((H, R), timeout=10)
    except OSError: c.close(); continue
    done = threading.Lock()
    for x, y in ((c, u), (u, c)): threading.Thread(target=pipe, args=(x, y, done), daemon=True).start()
