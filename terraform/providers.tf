# AWS provider pinned to the dedicated `training` profile (NEVER the production default).
# See CLAUDE.md golden rule #1.
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0" # aws_bedrockagentcore_agent_runtime is new; needs a recent provider
    }
  }
}

provider "aws" {
  region  = var.region
  profile = "training"
}
