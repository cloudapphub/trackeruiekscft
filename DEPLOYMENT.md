# Swift GPI Tracker — Deployment Guide

> **Stack:** Streamlit · Docker · ECR · EKS 1.35 · ALB · DynamoDB · CloudFormation · us-east-1

---

## Prerequisites

| Tool | Min Version | Install |
|---|---|---|
| AWS CLI | v2.x | `brew install awscli` |
| kubectl | v1.29+ | `brew install kubectl` |
| helm | v3.14+ | `brew install helm` |
| docker | v24+ | [docker.com](https://docker.com) |
| git | any | `brew install git` |

```bash
# Verify tools
aws --version && kubectl version --client && helm version --short && docker --version

# Set AWS credentials
export AWS_PROFILE=your-profile          # or use AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
export AWS_REGION=us-east-1
export PROJECT_NAME=gpi-tracker
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account: $ACCOUNT_ID"
```

---

## Step 1 — Deploy CloudFormation Stacks

Deploy stacks **in order**. Each stack exports values used by the next.

### 1.1 VPC Stack
```bash
aws cloudformation deploy \
  --template-file cfn/01-vpc.yaml \
  --stack-name ${PROJECT_NAME}-vpc \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```
**Creates:** VPC `192.168.0.0/23`, 2 public subnets, 2 private subnets, IGW, NAT GW (AZ1), 3 Security Groups.

### 1.2 IAM Stack
```bash
aws cloudformation deploy \
  --template-file cfn/02-iam.yaml \
  --stack-name ${PROJECT_NAME}-iam \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ${AWS_REGION}
```
**Creates:** EKS Cluster Role, Node Role, Pod Identity Role (DynamoDB), ALB Controller Role, Fluentd CW policy.

### 1.3 ECR Stack
```bash
aws cloudformation deploy \
  --template-file cfn/03-ecr.yaml \
  --stack-name ${PROJECT_NAME}-ecr \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --region ${AWS_REGION}
```
**Creates:** ECR repository `gpi-tracker/ui` with scan-on-push and lifecycle policy.

### 1.4 EKS Cluster Stack ⏱️ ~15 min
```bash
aws cloudformation deploy \
  --template-file cfn/04-eks-cluster.yaml \
  --stack-name ${PROJECT_NAME}-eks-cluster \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```
**Creates:** EKS 1.35 cluster, add-ons (VPC CNI, CoreDNS, kube-proxy, **eks-pod-identity-agent**, EBS CSI), Pod Identity Associations for app + ALB controller.

### 1.5 Node Group Stack ⏱️ ~5 min
```bash
aws cloudformation deploy \
  --template-file cfn/05-eks-nodegroup.yaml \
  --stack-name ${PROJECT_NAME}-nodegroup \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```
**Creates:** Managed node group with 3× t3.medium in private subnets. IMDSv2 enforced, 50GB gp3 encrypted EBS.

### 1.6 DynamoDB Stack
```bash
aws cloudformation deploy \
  --template-file cfn/06-dynamodb.yaml \
  --stack-name ${PROJECT_NAME}-dynamodb \
  --parameter-overrides ProjectName=${PROJECT_NAME} \
  --region ${AWS_REGION}
```
**Creates:** `GpiTrackerRequests` table (PAY_PER_REQUEST, KMS encryption, PITR, TTL, status GSI).

### 1.7 CloudWatch Logs Stack
```bash
aws cloudformation deploy \
  --template-file cfn/08-cloudwatch-logs.yaml \
  --stack-name ${PROJECT_NAME}-cloudwatch \
  --parameter-overrides ProjectName=${PROJECT_NAME} LogRetentionDays=30 \
  --region ${AWS_REGION}
```
**Creates:** Log groups: `/eks/gpi-tracker/application`, `/system`, `/dataplane`, `/host`.

---

## Step 2 — Build & Push Docker Image

```bash
chmod +x scripts/build-push.sh
./scripts/build-push.sh latest
```

This script:
1. Authenticates Docker to ECR
2. Builds a `linux/amd64` image from `app/Dockerfile`
3. Tags with `latest` and git SHA
4. Pushes to ECR
5. Auto-updates `k8s/deployment.yaml` with the correct image URI

**Manual equivalent:**
```bash
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/ui"
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin \
  "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker build --platform linux/amd64 -t ${ECR_URI}:latest -f app/Dockerfile app/
docker push ${ECR_URI}:latest
```

---

## Step 3 — Deploy Kubernetes Resources

```bash
chmod +x scripts/deploy-k8s.sh
./scripts/deploy-k8s.sh
```

This script:
1. Configures `kubectl` via `aws eks update-kubeconfig`
2. Installs **AWS Load Balancer Controller** via Helm
3. Applies `namespace.yaml`, `serviceaccount.yaml`
4. Deploys **Fluentd DaemonSet** (→ CloudWatch)
5. Applies `deployment.yaml` (3 replicas), `service.yaml`, `ingress.yaml`
6. Waits for rollout and prints the ALB URL

**Manual steps if preferred:**
```bash
# Configure kubectl
aws eks update-kubeconfig --region ${AWS_REGION} --name ${PROJECT_NAME}-cluster

# Install AWS Load Balancer Controller
VPC_ID=$(aws cloudformation list-exports \
  --query "Exports[?Name=='${PROJECT_NAME}-VpcId'].Value" --output text)

helm repo add eks https://aws.github.io/eks-charts && helm repo update

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=${PROJECT_NAME}-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=${AWS_REGION} \
  --set vpcId=${VPC_ID} \
  --wait

# Apply all manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/fluentd-daemonset.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

---

## Step 4 — Verify Deployment

```bash
# Check pods (expect 3 Running)
kubectl get pods -n gpi-tracker -o wide

# Check deployment
kubectl get deployment gpi-tracker -n gpi-tracker

# Check ALB Ingress (wait ~2 min for DNS)
kubectl get ingress gpi-tracker-ingress -n gpi-tracker

# Check Fluentd
kubectl get daemonset fluentd -n kube-system

# Check DynamoDB table
aws dynamodb describe-table \
  --table-name GpiTrackerRequests \
  --query 'Table.{Status:TableStatus,Items:ItemCount}' \
  --output table

# Check CloudWatch log groups
aws logs describe-log-groups \
  --log-group-name-prefix /eks/gpi-tracker \
  --query 'logGroups[].logGroupName'
```

---

## Step 5 — Access the Application

```bash
# Get ALB URL
ALB_URL=$(kubectl get ingress gpi-tracker-ingress \
  -n gpi-tracker \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

echo "Open: http://${ALB_URL}"
```

Navigate to the URL in your browser. You should see:
- **Dashboard** — Payment statistics and recent payments table
- **Track Payment** — Enter any UUID as UETR to simulate a payment journey
- **New Payment** — Submit a new payment (stored to DynamoDB)

---

## Architecture Overview

```
Internet
   │
   ▼
[ALB - internet-facing]          ← public subnets (192.168.0.0/25, .0.128/25)
   │
   ▼
[K8s Ingress / LBC]
   │
   ▼
[gpi-tracker Service (NodePort)]
   │
   ├──▶ [Pod 1: Streamlit]  ─┐
   ├──▶ [Pod 2: Streamlit]  ─┼──▶ [DynamoDB: GpiTrackerRequests]
   └──▶ [Pod 3: Streamlit]  ─┘          (via EKS Pod Identity)
         (private subnets: 192.168.1.0/25, .1.128/25)

[Fluentd DaemonSet] ──▶ [CloudWatch Logs: /eks/gpi-tracker/*]

[NAT GW] ──▶ Internet (for ECR pulls, AWS APIs)
```

**Networking:**
| Subnet | CIDR | AZ |
|---|---|---|
| Public 1 | 192.168.0.0/25 | us-east-1a |
| Public 2 | 192.168.0.128/25 | us-east-1b |
| Private 1 | 192.168.1.0/25 | us-east-1a |
| Private 2 | 192.168.1.128/25 | us-east-1b |

---

## EKS Pod Identity

This project uses **EKS Pod Identity** (not IRSA). No OIDC provider needed.

The `gpi-tracker-sa` ServiceAccount in the `gpi-tracker` namespace automatically receives temporary AWS credentials via the `eks-pod-identity-agent` DaemonSet. These credentials grant the pod permission to read/write DynamoDB.

Trust policy on `gpi-tracker-pod-role`:
```json
{
  "Principal": { "Service": "pods.eks.amazonaws.com" },
  "Action": ["sts:AssumeRole", "sts:TagSession"]
}
```

The binding is defined in CFN stack `04-eks-cluster.yaml` as `AWS::EKS::PodIdentityAssociation`.

---

## Teardown

```bash
# Remove K8s resources first (releases ALB)
kubectl delete -f k8s/
helm uninstall aws-load-balancer-controller -n kube-system

# Wait ~2 min for ALB to terminate, then delete stacks in reverse order
for STACK in nodegroup eks-cluster dynamodb cloudwatch ecr iam vpc; do
  aws cloudformation delete-stack \
    --stack-name ${PROJECT_NAME}-${STACK} \
    --region ${AWS_REGION}
  aws cloudformation wait stack-delete-complete \
    --stack-name ${PROJECT_NAME}-${STACK} \
    --region ${AWS_REGION}
  echo "✓ Deleted: ${PROJECT_NAME}-${STACK}"
done
```

> **Note:** DynamoDB table has `DeletionProtectionEnabled: true`. Disable it manually before teardown if you want the table deleted.
