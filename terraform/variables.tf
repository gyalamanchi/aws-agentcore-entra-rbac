variable "region" {
  description = "AWS region (must match where the ECR image + model access live)."
  type        = string
  default     = "us-east-1"
}

variable "execution_role_arn" {
  description = "ARN of the admin-created AgentCore execution role (see iam/agentcore-execution-role.json). The training user only PASSES this role."
  type        = string
}

variable "container_uri" {
  description = "Full ECR image URI (with tag) of the ARM64 agent image that `agentcore deploy --local-build` already built and pushed. Find it with: aws ecr describe-images ... or from `agentcore status`."
  type        = string
}

variable "agent_runtime_name" {
  description = "Name for the Terraform-managed runtime. Kept distinct from the toolkit's so the two don't collide."
  type        = string
  default     = "catalog_agent_tf"
}
