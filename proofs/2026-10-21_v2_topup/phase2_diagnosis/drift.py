from safetensors.torch import load_file
import os
R=os.path.expanduser("~/smartcity_runs")
a=load_file(R+"/agents_v2_topup2/checkpoints/checkpoint-500/adapter_model.safetensors")
v2=load_file(R+"/agents_v2/adapter/adapter_model.safetensors")
def D(b): return sum(float(((b[k].float()-a[k].float())**2).sum()) for k in a)
print("v2->p1", D(v2), "params", sum(t.numel() for t in a.values()))
for s in (25,50,100,150):
    print(s, D(load_file(R+f"/agents_v2_topup3/checkpoints/checkpoint-{s}/adapter_model.safetensors")))
