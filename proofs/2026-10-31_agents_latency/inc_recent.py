import json,re,sys
rows=[]
for l in open(sys.argv[1]):
    try: d=json.loads(l)
    except Exception: continue
    tl=d.get('timeline') or []
    nag=None; ags=[]; rs=None; fin=None
    for t in tl:
        m=t.get('msg') or ''
        r=re.match(r'Orchestrator: (\d+) sensor\(s\) to NPU agents',m)
        if r: nag=int(r.group(1))
        r=re.search(r'agent done in ([\d.]+)s \(first token ([\d.]+)s, (\d+) tokens',m)
        if r: ags.append(r.group(1)+'/'+r.group(2)+'/'+r.group(3))
        r=re.match(r'Reasoner v3 report in ([\d.]+)s',m)
        if r: rs=r.group(1)
        r=re.match(r'Finished in ([\d.]+)s',m)
        if r: fin=r.group(1)
    rows.append((d.get('created_wall'),d.get('id'),nag,ags[-3:],rs,fin))
for r in rows[-int(sys.argv[2]):]: print(r)
