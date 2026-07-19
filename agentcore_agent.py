"""Minimal Strands agent, wrapped for Bedrock AgentCore Runtime.

Same idea as strands_agent.py, but wrapped in a BedrockAgentCoreApp so it can be deployed to the
managed AgentCore Runtime and invoked from the console / SDK. The agent "selects" from a small
in-memory CATALOG via two tools and answers in natural language.

Run it locally first (no deploy, but does call Bedrock for nova = a few tokens):
    export AWS_PROFILE=training
    python agentcore_agent.py            # serves an HTTP endpoint on :8080
    # in another shell:
    curl -X POST localhost:8080/invocations -H 'Content-Type: application/json' \
         -d '{"prompt":"How much is a banana and is it in stock?"}'

Deploy + invoke: see README.md section 6.

Model: amazon.nova-micro-v1:0 — cheap, and (unlike Anthropic models) needs no "use case details"
form. To use Claude instead, enable it in Bedrock -> Model access, submit the Anthropic form, and
use an inference-profile id (e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0). See CLAUDE.md.
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

# The "list/dict of items" the agent selects through.
CATALOG = {
    "apple":  {"price": 0.50, "stock": 120},
    "banana": {"price": 0.25, "stock": 8},
    "cherry": {"price": 2.00, "stock": 0},
    "date":   {"price": 3.50, "stock": 42},
}


@tool
def list_items() -> list:
    """List the names of every item available in the catalog."""
    return list(CATALOG)


@tool
def lookup_item(name: str) -> dict:
    """Look up one catalog item's price and stock by name (case-insensitive)."""
    return CATALOG.get(name.lower().strip(), {"error": f"'{name}' is not in the catalog"})


app = BedrockAgentCoreApp()

agent = Agent(
    model=BedrockModel(model_id="amazon.nova-micro-v1:0"),
    tools=[list_items, lookup_item],
    system_prompt=(
        "You are a catalog assistant. Use the tools to look things up rather than guessing. "
        "Be concise. If an item is out of stock (stock 0), say so explicitly."
    ),
)


@app.entrypoint
def invoke(payload):
    """AgentCore entrypoint. `payload` is the JSON body sent to the runtime."""
    prompt = payload.get("prompt", "What items are available?")
    result = agent(prompt)
    # result.message is the assistant's structured message; return it as JSON.
    return {"result": result.message}


if __name__ == "__main__":
    app.run()
