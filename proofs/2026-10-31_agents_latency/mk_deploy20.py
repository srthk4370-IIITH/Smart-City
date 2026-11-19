import re
p='/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/deploy20.sh'
s=open(p).read()
lines=s.split('\n')
hdr='''#!/usr/bin/env bash
# 2026-10-31 deploy20: htpd_v9e = v9d + agent draft index (HTPD_AGENT_NGMAX=8: n-gram orders 8..1; HTPD_AGENT_RECENT_MAX=500:
# hashed index of the last 500 agent outputs instead of a linear scan of 64; HTPD_AGENT_CORPUS: seeded at start from
# agent_corpus.txt = the app's 1134 past agent outputs (token ids), every new agent output appended). Drafts are verified
# and rows per step are unchanged, so agent outputs are unchanged. Reasoner settings = deploy19 (kept from the profile).
# Lab: proofs/2026-10-31_agents_latency/VERDICT.md. Rollback = deploy20/known_good (live deploy19 profile + APK from the board).
# Check: chaos 2 + fastcheck x2 + chat check; any chaos/fastcheck failure -> previous APK + profile. Never reboots.
# usage (WSL): bash deploy20.sh'''
# replace header comment block (lines until 'M=')
i=[k for k,l in enumerate(lines) if l.startswith('M=')][0]
lines=hdr.split('\n')+lines[i:]
s='\n'.join(lines)
s=s.replace('C=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_latency/corpus/corpus_real_all.jsonl; CMD5=93daf8775c671eea37193bce599ba0e9',
            'C=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-31_agents_latency/agent_corpus_all.txt; CMD5=a136e22adca3a23d01ba78cad943dd19')
s=s.replace('pidof htpd_v9d htpd_v9c','pidof htpd_v9e htpd_v9d htpd_v9c')
s=s.replace('echo "# Deploy 19 (htpd_v9d: live draft corpus + corpus with the app\'s reports; XENV [$XENV])','echo "# Deploy 20 (htpd_v9e: agent draft index + agent corpus)')
s=s.replace('for f in $BIN/htpd_v9d /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf','for f in $BIN/htpd_v9e /data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf')
s=s.replace('[ "$(sh_ "md5sum $BIN/htpd_v9d" | cut -c1-32)" = 73ae89e2e8d2ac8bc67a6b9839950f94 ] || { st "- ABORT: htpd_v9d md5"; exit 1; }',
            '[ "$(sh_ "md5sum $BIN/htpd_v9e" | cut -c1-32)" = 0080ce237487c898b7fe2d4fe71303af ] || { st "- ABORT: htpd_v9e md5"; exit 1; }')
s=s.replace('setp $I/profile.new bin $BIN/htpd_v9d','setp $I/profile.new bin $BIN/htpd_v9e')
# env: keep the live env, drop any agent-draft keys, add ours
s=re.sub(r'^e=\$\(grep "\^env=".*$', 'e=$(grep "^env=" $I/profile.new | sed "s/^env=//; s/ *HTPD_AGENT_NGMAX=[^ ]*//; s/ *HTPD_AGENT_RECENT_MAX=[^ ]*//; s/ *HTPD_AGENT_CORPUS=[^ ]*//")', s, flags=re.M)
s=re.sub(r'^setp \$I/profile.new env .*$', 'setp $I/profile.new env "$e HTPD_AGENT_NGMAX=8 HTPD_AGENT_RECENT_MAX=500 HTPD_AGENT_CORPUS=$W/agent_corpus.txt"', s, flags=re.M)
s=s.replace('$W/reason_corpus_v2.jsonl.part','$W/agent_corpus.txt.part').replace('mv -f $W/agent_corpus.txt.part $W/reason_corpus_v2.jsonl','mv -f $W/agent_corpus.txt.part $W/agent_corpus.txt')
s=s.replace('sh_ "mv -f $W/reason_corpus_v2.jsonl.part $W/reason_corpus_v2.jsonl"','sh_ "mv -f $W/agent_corpus.txt.part $W/agent_corpus.txt"')
s=s.replace('# second fastcheck: the same incident again (the live corpus now holds the first one\'s report)','# second fastcheck: the same incident again')
s=s.replace('st "- DEPLOYED: bin htpd_v9d (live corpus) + reason_corpus_v2 + lib_rp29, APK unchanged;','st "- DEPLOYED: bin htpd_v9e (agent draft index + agent_corpus.txt), reasoner env as deploy19, APK unchanged;')
s=s.replace("grep -E 'split-spec|live corpus|load phases|step profile|reason 3 streams'","grep -E 'v9e agent|draft steps|split-spec|load phases|reasoner loaded in'")
s=s.replace('=== deploy20 done','=== deploy20 done')
open(p,'w').write(s)
