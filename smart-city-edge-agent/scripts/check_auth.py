import inspect
import qai_hub_models.models.llama_v3_2_3b_instruct.model as llama_model

print("HF_REPO_NAME:", llama_model.HF_REPO_NAME)
print("from_pretrained signature:", inspect.signature(llama_model.Llama3_2_3B.from_pretrained))
print("from_pretrained defaults:", llama_model.Llama3_2_3B.from_pretrained.__defaults__)
print("__init__ signature:", inspect.signature(llama_model.Llama3_2_3B.__init__))
