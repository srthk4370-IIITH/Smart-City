import json,sys
for l in open(sys.argv[1]):
  r=json.loads(l)
  if len(sys.argv)>2 and r['i']<int(sys.argv[2]): continue
  print('#%d [%s] %s ms=%s wall=%s q=%s T=%s busy=%s err=%s'%(r['i'],r['group'],r.get('temp_c'),r.get('ms'),r.get('wall_s'),r['q'],r.get('sim_time'),r.get('busy'),r.get('error')))
  for t in r.get('tools',[]): print('   TOOL',t['name'],t['args'],'=>',t['result'][:400])
  print('   A:',r.get('text',r.get('raw')))
