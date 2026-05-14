#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-push.sh — Build Docker image and push to ECR
# Usage: ./scripts/build-push.sh [IMAGE_TAG]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-gpi-tracker}"
IMAGE_TAG="${1:-latest}"

# Derive ECR URI from AWS account
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/ui"

echo "========================================================"
echo "  Swift GPI Tracker — Docker Build & ECR Push"
echo "========================================================"
echo "  Region      : ${AWS_REGION}"
echo "  Account     : ${ACCOUNT_ID}"
echo "  ECR URI     : ${ECR_URI}"
echo "  Image Tag   : ${IMAGE_TAG}"
echo "========================================================"

# ── Authenticate Docker to ECR ────────────────────────────────────────────────
echo ""
echo "[1/4] Authenticating Docker to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# ── Build Docker image ────────────────────────────────────────────────────────
echo ""
echo "[2/4] Building Docker image..."
docker build \
  --platform linux/amd64 \
  --tag "${ECR_URI}:${IMAGE_TAG}" \
  --tag "${ECR_URI}:$(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')" \
  --file app/Dockerfile \
  app/

# ── Push to ECR ───────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Pushing image to ECR..."
docker push "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:$(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')" 2>/dev/null || true

# ── Update deployment image ───────────────────────────────────────────────────
echo ""
echo "[4/4] Updating k8s/deployment.yaml image reference..."
sed -i "s|ACCOUNT_ID\.dkr\.ecr\..*\.amazonaws\.com/gpi-tracker/ui:.*|${ECR_URI}:${IMAGE_TAG}|g" \
  k8s/deployment.yaml

echo ""
echo "✅ Done! Image pushed to: ${ECR_URI}:${IMAGE_TAG}"
echo ""
echo "Next step: Run ./scripts/deploy-k8s.sh to apply Kubernetes manifests."
