import json,sys
L=open(sys.argv[1]).read().splitlines()
d=json.loads(L[-1])
a=d.get('agents')
print(type(a), len(a) if a else 0)
x=a[0] if isinstance(a,list) else a
print(json.dumps(x)[:2500])
