p='build/check_big.py'; L=open(p,encoding='utf-8').read().split('\n')
L[123]='    if re.search(r"\bco2\b[^.\d\n:]{0,14}\d+(?:\.\d+)?(?!\d)(?!\s*ppm)", re.sub(r"(?i)co2[^.]*?(building|sensor)[^.]*", "", fin)) and not re.search(r"ppm", fin):'
open(p,'w',encoding='utf-8').write('\n'.join(L))
