#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy-k8s.sh — Configure kubectl and deploy all Kubernetes manifests
# Usage: ./scripts/deploy-k8s.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-gpi-tracker}"
CLUSTER_NAME="${PROJECT_NAME}-cluster"

echo "========================================================"
echo "  Swift GPI Tracker — Kubernetes Deployment"
echo "========================================================"
echo "  Cluster : ${CLUSTER_NAME}"
echo "  Region  : ${AWS_REGION}"
echo "========================================================"

# ── Step 1: Configure kubectl ─────────────────────────────────────────────────
echo ""
echo "[1/7] Configuring kubectl context for EKS..."
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"
echo "✓ kubectl configured for cluster: ${CLUSTER_NAME}"

# ── Step 2: Install AWS Load Balancer Controller via Helm ─────────────────────
echo ""
echo "[2/7] Installing AWS Load Balancer Controller (Helm)..."

# Get VPC ID from CFN export
VPC_ID=$(aws cloudformation list-exports \
  --query "Exports[?Name=='${PROJECT_NAME}-VpcId'].Value" \
  --output text)

helm repo add eks https://aws.github.io/eks-charts 2>/dev/null || true
helm repo update

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --set clusterName="${CLUSTER_NAME}" \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region="${AWS_REGION}" \
  --set vpcId="${VPC_ID}" \
  --wait \
  --timeout=5m
echo "✓ AWS Load Balancer Controller installed"

# ── Step 3: Apply namespace & service accounts ─────────────────────────────────
echo ""
echo "[3/7] Applying namespace and service accounts..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
echo "✓ Namespace and ServiceAccounts created"

# ── Step 4: Deploy Fluentd DaemonSet ─────────────────────────────────────────
echo ""
echo "[4/7] Deploying Fluentd DaemonSet..."
kubectl apply -f k8s/fluentd-daemonset.yaml
echo "✓ Fluentd DaemonSet deployed"

# ── Step 5: Deploy application ────────────────────────────────────────────────
echo ""
echo "[5/7] Deploying GPI Tracker application..."
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
echo "✓ Application manifests applied"

# ── Step 6: Wait for rollout ──────────────────────────────────────────────────
echo ""
echo "[6/7] Waiting for deployment rollout (3 replicas)..."
kubectl rollout status deployment/gpi-tracker \
  --namespace gpi-tracker \
  --timeout=10m
echo "✓ Deployment rollout complete"

# ── Step 7: Print status & ALB URL ───────────────────────────────────────────
echo ""
echo "[7/7] Deployment status:"
echo ""
kubectl get pods -n gpi-tracker -o wide
echo ""
kubectl get svc -n gpi-tracker
echo ""

echo "Waiting for ALB DNS (up to 5 minutes)..."
for i in $(seq 1 30); do
  ALB_DNS=$(kubectl get ingress gpi-tracker-ingress \
    -n gpi-tracker \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  if [[ -n "${ALB_DNS}" ]]; then
    break
  fi
  echo "  ... waiting ($((i * 10))s)"
  sleep 10
done

echo ""
echo "========================================================"
echo "  ✅ DEPLOYMENT COMPLETE"
echo "========================================================"
echo ""
if [[ -n "${ALB_DNS:-}" ]]; then
  echo "  🌐 Application URL: http://${ALB_DNS}"
else
  echo "  ⚠️  ALB DNS not yet available. Run:"
  echo "     kubectl get ingress gpi-tracker-ingress -n gpi-tracker"
fi
echo ""
echo "  📊 DynamoDB Table: GpiTrackerRequests"
echo "  📋 CloudWatch Logs: /eks/gpi-tracker/application"
echo "========================================================"
