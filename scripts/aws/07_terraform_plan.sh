#!/usr/bin/env sh
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform"

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform is required"
  exit 1
fi

if [ ! -d "$TF_DIR" ]; then
  echo "Terraform directory not found: $TF_DIR"
  exit 1
fi

cd "$TF_DIR"

# Prevent flaky provider startup timeouts on slower local environments.
: "${TF_PLUGIN_TIMEOUT:=120s}"
export TF_PLUGIN_TIMEOUT

# On local machines without explicit AWS credentials/profile, skip IMDS lookup
# to avoid long fallback waits and confusing provider startup timeouts.
if [ -z "${AWS_ACCESS_KEY_ID:-}" ] && [ -z "${AWS_PROFILE:-}" ]; then
  : "${AWS_EC2_METADATA_DISABLED:=true}"
  export AWS_EC2_METADATA_DISABLED
fi

if [ ! -f terraform.tfvars ] && [ -f terraform.tfvars.example ]; then
  cp terraform.tfvars.example terraform.tfvars
  echo "Created terraform.tfvars from example. Review it before apply."
fi

terraform init
terraform validate

if command -v conftest >/dev/null 2>&1; then
  "$ROOT_DIR/scripts/iac/01_conftest_check.sh"
else
  echo "conftest not found; skipping policy gate"
fi

terraform plan
