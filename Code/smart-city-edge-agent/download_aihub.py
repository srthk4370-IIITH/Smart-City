import qai_hub as hub
import sys

print("Getting model...")
model = hub.get_model("llama-v3-2-3b-instruct")

print("Getting target model...")
target_model = model.get_target_model("qualcomm_snapdragon_8gen3")

print("Downloading bundle for QAIRT 2.50.40...")
# Qualcomm AI Hub usually defaults to the latest version, which might be 2.30 or 2.34 now.
# But wait, if I can just download the default and it works?
# Let's try downloading with a specific qairt_version if the API supports it.
# Actually, the AI hub web interface allows downloading bundles.
import inspect
print(inspect.signature(target_model.download))
