p='build/build_big.py'; s=open(p,encoding='utf-8').read()
old='    nd = [r for r in new if not r.get("dup_of")]'
new='''    gold = []   # existing gold fog chat rows (tools_v4 fog_* names / test_fog format; online, offline, timeout): non-empty final, a fog tool called
    for fn in ("train_new.jsonl", "replay.jsonl"):
        for r in jl(D2 + "/" + fn):
            if r.get("tools") in ("chat_r5", "chat") and (r["messages"][-1].get("content") or "").strip() and any(
                    tc["function"]["name"].startswith("fog_") for m in r["messages"] for tc in (m.get("tool_calls") or [])):
                gold.append(dict(r, id="fg-" + r["id"], kind="fog_gold", big="C", block="bigC_fog_gold", fog_gold=True))
    new = new + gold
    nd = [r for r in new if not r.get("dup_of")]'''
assert old in s; s=s.replace(old,new,1)
s=s.replace('Ct = [r for r in Cs if r["kind"].startswith(TOOL_PREFIX)]','Cf = [r for r in Cs if r["kind"].startswith("fog")]; Cs = [r for r in Cs if not r["kind"].startswith("fog")]\n    Ct = [r for r in Cs if r["kind"].startswith(TOOL_PREFIX)]')
s=s.replace('''sel = (bal(Bs, int(NEW_N * .30), lambda r: r["block"]) + bal(Ct, int(NEW_N * .27), lambda r: r["kind"]) + bal(Co, int(NEW_N * .08), lambda r: r["kind"])
           + bal(Ds, NEW_N - int(NEW_N * .30) - int(NEW_N * .27) - int(NEW_N * .08), lambda r: r.get("family", "").split(":")[-1][:12]))''','''sel = (bal(Bs, int(NEW_N * .27), lambda r: r["block"]) + bal(Ct, int(NEW_N * .22), lambda r: r["kind"]) + bal(Cf, int(NEW_N * .14), lambda r: r["kind"])
           + bal(Co, int(NEW_N * .06), lambda r: r["kind"]) + bal(Ds, NEW_N - int(NEW_N * .69), lambda r: r.get("family", "").split(":")[-1][:12]))''')
open(p,'w',encoding='utf-8').write(s)
