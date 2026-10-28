import json, sys, random, statistics as st
from transformers import AutoTokenizer
root, model = sys.argv[1], sys.argv[2]
tok = AutoTokenizer.from_pretrained(model)
tools = json.load(open(root + '/pipeline/tools_v3.json'))
rows = [json.loads(l) for l in open(root + '/data/train_mix.jsonl', encoding='utf-8')]
inc = [r for r in rows if r.get('tools') == 'incident']
random.seed(0); inc = random.sample(inc, min(400, len(inc)))
kw = dict(tools=tools['incident'], tokenize=False, enable_thinking=False)
def pre(msgs, **k):
    a = tok(tok.apply_chat_template(msgs + [{'role':'user','content':'zzqx'}], **k))['input_ids']
    b = tok(tok.apply_chat_template(msgs + [{'role':'user','content':'Q'}], **k))['input_ids']
    i = 0
    while a[i] == b[i]: i += 1
    return i
n_static = pre(inc[0]['messages'][:1], **kw)
n_sys_notools = pre(inc[0]['messages'][:1], tokenize=False, enable_thinking=False)
U, A, T, NC, FIN = [], [], [], [], []
for r in inc:
    m = r['messages']
    full = len(tok(tok.apply_chat_template(m, **kw))['input_ids'])
    first = len(tok(tok.apply_chat_template(m[:2], add_generation_prompt=True, **kw))['input_ids'])
    U.append(first - n_static)
    asst = [x for x in m if x['role'] == 'assistant']
    NC.append(sum(len(x.get('tool_calls') or []) for x in asst))
    fin = asst[-1].get('content') or ''
    FIN.append(len(tok(fin)['input_ids']))
    T.append(full)
q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
print(json.dumps(dict(n=len(inc), static_system_plus_tools=n_static, system_without_tools=n_sys_notools,
  user_p50=q(U, .5), user_p90=q(U, .9), final_json_p50=q(FIN, .5), final_json_p90=q(FIN, .9),
  total_p50=q(T, .5), total_p90=q(T, .9), calls_mean=st.mean(NC), zero_call_frac=sum(c == 0 for c in NC) / len(NC))))
