"""Minimal Strands agent on Bedrock — a tool-using agent in ~15 lines.

    AWS_PROFILE=training python strands_agent.py

Strands reads your AWS profile for the Bedrock backend (no extra creds). Set the model_id to one you
enabled in Bedrock → Model access. APIs evolve — check https://strandsagents.com for the current
signatures if anything here drifts.
"""
from strands import Agent, tool
from strands.models import BedrockModel


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


# BedrockModel uses your AWS_PROFILE + region. Swap model_id for one you enabled.
# Claude 4.5+ models require an inference-profile id (not the bare on-demand model id) —
# find yours with: aws bedrock list-inference-profiles --region us-east-1
#model = BedrockModel(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
model = BedrockModel(model_id="amazon.nova-micro-v1:0")

agent = Agent(
    model=model,
    tools=[multiply],
    system_prompt="You are a concise assistant. Use tools when useful.",
)

if __name__ == "__main__":
    result = agent("What is 23 times 19? Use the tool, then state the answer in one sentence.")
    print("\n---\n", result)
