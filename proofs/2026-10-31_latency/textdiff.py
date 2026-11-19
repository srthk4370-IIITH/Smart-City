import json,sys
def get(f):
    for l in open(f):
        if l.startswith('{"outputs"'): return json.loads(json.loads(l)['outputs'][0]['text'])
for a,b in [('cur_q102_3','real_q102_3'),('cur_q105_6','real_q105_6'),('cur_q102_3','reallive_q102_3'),('cur_q100_1','reallive_q100_1')]:
    A,B=get(a+'.json'),get(b+'.json')
    print(a,b,[k for k in A if A.get(k)!=B.get(k)])
    for k in A:
        if A.get(k)!=B.get(k): print('  ',k,'|',json.dumps(A[k])[:200],'\n   ->',json.dumps(B.get(k))[:200]); break
