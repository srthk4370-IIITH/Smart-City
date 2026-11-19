import json,collections,datetime,sys
d=json.load(open(sys.argv[1]))
real=[x for x in d if not x['injected']]
print(len(d),'real',len(real))
print(collections.Counter(x['roles'][0] if x['roles'] else '-' for x in real))
print(collections.Counter(x['severity'] for x in real))
print(collections.Counter(x['approval'] for x in real), collections.Counter(x['workflow'] for x in real), collections.Counter(x['state'] for x in real))
s=sorted(real,key=lambda x:x['created_sim'])
for x in s[-10:]: print(x['id'],x['created_sim_ist'],datetime.datetime.utcfromtimestamp(x['created_sim']+19800),x['severity'],x['approval'],x['workflow'],x['roles'],x['title'])
