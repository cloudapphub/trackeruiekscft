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
echo "[1/8] Configuring kubectl context for EKS..."
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"
echo "✓ kubectl configured for cluster: ${CLUSTER_NAME}"

# ── Step 2: Apply namespace & service accounts ─────────────────────────────────
# Must come BEFORE Helm LBC install since serviceAccount.create=false
echo ""
echo "[2/8] Applying namespace and service accounts..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
echo "✓ Namespace and ServiceAccounts created"

# ── Step 3: Install AWS Load Balancer Controller via Helm ─────────────────────
echo ""
echo "[3/8] Installing AWS Load Balancer Controller (Helm)..."

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
  --timeout=10m
echo "✓ AWS Load Balancer Controller installed"

# ── Step 4: Check EBS CSI Driver health ──────────────────────────────────────
echo ""
echo "[4/8] Checking EBS CSI Driver health..."
EBS_STATUS=$(aws eks describe-addon \
  --cluster-name "${CLUSTER_NAME}" \
  --addon-name aws-ebs-csi-driver \
  --query 'addon.status' --output text \
  --region "${AWS_REGION}" 2>/dev/null || echo "NOT_FOUND")

echo "  EBS CSI Driver status: ${EBS_STATUS}"
if [ "${EBS_STATUS}" = "DEGRADED" ]; then
  echo "  Restarting EBS CSI controller..."
  kubectl rollout restart deployment ebs-csi-controller -n kube-system
  sleep 30
  echo "  ✓ EBS CSI controller restarted"
else
  echo "  ✓ EBS CSI Driver is healthy — no action needed"
fi

# ── Step 5: Deploy Fluentd DaemonSet ─────────────────────────────────────────
echo ""
echo "[5/8] Deploying Fluentd DaemonSet..."
kubectl apply -f k8s/fluentd-daemonset.yaml
echo "✓ Fluentd DaemonSet deployed"

# ── Step 6: Deploy application ────────────────────────────────────────────────
echo ""
echo "[6/8] Deploying GPI Tracker application..."
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
echo "✓ Application manifests applied"

# ── Step 7: Wait for rollout ──────────────────────────────────────────────────
echo ""
echo "[7/8] Waiting for deployment rollout (2 replicas)..."
kubectl rollout status deployment/gpi-tracker \
  --namespace gpi-tracker \
  --timeout=10m
echo "✓ Deployment rollout complete"

# ── Step 8: Print status & ALB URL ───────────────────────────────────────────
echo ""
echo "[8/8] Deployment status:"
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
