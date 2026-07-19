# ─────────────────────────────────────────────────────────────────────────────
# Learning exercise: the SAME AgentCore Runtime the starter toolkit deploys,
# expressed as Terraform. Terraform CANNOT build containers, so this reuses the
# ARM64 image that `agentcore deploy --local-build` already pushed to ECR
# (var.container_uri). It creates a SECOND, parallel runtime (agent_runtime_name
# defaults to "..._tf") so it never collides with the toolkit-managed one.
#
# `terraform apply` here creates a REAL AgentCore Runtime → same billing model as
# the toolkit one (compute only while invoked; tiny idle floor). See CLAUDE.md.
#
# Resource schema per hashicorp/aws docs:
# https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_agent_runtime
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_bedrockagentcore_agent_runtime" "catalog" {
  agent_runtime_name = var.agent_runtime_name
  description        = "Strands catalog agent (Terraform-managed, mirrors the toolkit deploy)."
  role_arn           = var.execution_role_arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.container_uri
    }
  }

  # BedrockAgentCoreApp serves plain HTTP on /invocations (not MCP).
  protocol_configuration {
    server_protocol = "HTTP"
  }

  # Publicly reachable via the AgentCore data-plane (still IAM-authenticated);
  # no VPC wiring needed for this sandbox.
  network_configuration {
    network_mode = "PUBLIC"
  }
}

output "agent_runtime_arn" {
  description = "ARN to invoke (console / boto3 invoke_agent_runtime / agentcore invoke)."
  value       = aws_bedrockagentcore_agent_runtime.catalog.agent_runtime_arn
}
