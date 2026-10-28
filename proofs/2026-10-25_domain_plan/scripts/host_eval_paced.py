"""host_eval3e.py run with a 2 s pause before every completion request (owner thermal rule 2026-10-27)."""
import sys, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e")
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post")
import host_eval_v2 as HV
_p = HV._post
def _paced(url, body, *a, **k):
    if url.endswith("/completion"):
        time.sleep(2)
    return _p(url, body, *a, **k)
HV._post = _paced
import host_eval3e as M
sys.argv[0] = "host_eval3e.py"
M.main()
