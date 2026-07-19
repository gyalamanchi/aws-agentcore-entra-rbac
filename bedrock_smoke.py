"""Bedrock smoke test — proves your `training` profile + Bedrock access work.

    AWS_PROFILE=training python bedrock_smoke.py

Step 1 just LISTS the models your account can see (needs only bedrock:ListFoundationModels — a good
first check). Step 2 does a real inference via the Converse API — uncomment once you've enabled model
access in the console (Bedrock → Model access) and picked a model id from the list.
"""
import boto3

# region comes from the profile (aws configure set it); override with AWS_REGION if you want.
bedrock = boto3.client("bedrock")               # control plane: list/describe models
runtime = boto3.client("bedrock-runtime")       # data plane: invoke/converse

# --- Step 1: which models can this account/region see? (and which are enabled) ---
models = bedrock.list_foundation_models().get("modelSummaries", [])
print(f"visible foundation models: {len(models)}")
for m in models:
    if "claude" in m["modelId"].lower():        # just show the Claude ones to keep it short
        print(f"  {m['modelId']:55} in={m.get('inputModalities')} out={m.get('outputModalities')}")

# --- Step 2: a real inference (uncomment after enabling model access) ---
# MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"   # <-- replace with a model you ENABLED
# resp = runtime.converse(
#     modelId=MODEL_ID,
#     messages=[{"role": "user", "content": [{"text": "Reply with a one-sentence hello."}]}],
#     inferenceConfig={"maxTokens": 100, "temperature": 0.5},
# )
# print("\nmodel says:", resp["output"]["message"]["content"][0]["text"])
