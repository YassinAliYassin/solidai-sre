# SolidAI SRE — AWS Deployment Guide

## Prerequisites

✅ AWS account linked to GitHub identity (YassinAliYassin)
✅ AWS CLI installed (v2.34.50)
✅ SolidAI SRE repo cloned

## Quick Start

### Option 1: EKS (Kubernetes) — Production

```bash
# 1. Complete AWS SSO login (interactive — requires browser)
aws sso login --profile solidai-sre

# 2. Create EKS cluster (if not exists)
aws eks create-cluster \
  --name solidai-sre-cluster \
  --region us-east-1 \
  --role-arn arn:aws:iam::ACCOUNT_ID:role/eks-cluster-role \
  --resources-vpc-config '{"subnetIds": ["subnet-xxx"], "securityGroupIds": ["sg-xxx"]}'

# 3. Wait for cluster to be ACTIVE, then deploy
./deploy-eks.sh solidai-sre-cluster us-east-1

# 4. Access services
kubectl port-forward -n solidai-sre svc/web-ui 3002:3000 &
kubectl port-forward -n solidai-sre svc/sre-agent 8001:8000 &
open http://localhost:3002
```

### Option 2: EC2 (Docker Compose) — Simple

```bash
# 1. Launch EC2 instance (Ubuntu 22.04, t3.medium+)
# 2. SSH into instance
ssh ubuntu@ec2-xxx.compute.amazonaws.com

# 3. Run deployment script
git clone https://github.com/YassinAliYassin/solidai-sre.git
cd solidai-sre
./deploy-ec2.sh

# 4. Access (replace with EC2 public IP)
http://ec2-xxx.compute.amazonaws.com:3002
```

### Option 3: GitHub Actions CI/CD (Automated)

1. **Set up AWS OIDC:**
   - Go to AWS IAM → Identity providers → Add provider
   - Provider: `token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
   
2. **Create IAM role:**
   - Use `aws-iam-trust-policy.json` (in repo root)
   - Attach `AdministratorAccess` policy (or scoped down)

3. **Add GitHub secret:**
   - Repo Settings → Secrets → Actions
   - Name: `AWS_ROLE_ARN`
   - Value: `arn:aws:iam::ACCOUNT_ID:role/solidai-sre-github-role`

4. **Push to main** — GitHub Actions will auto-deploy!

## Ports (Docker Compose)

| Service | Internal | External |
|---------|-----------|----------|
| Web UI | 3000 | 3002 |
| SRE Agent | 8000 | 8001 |
| Config Service | 8080 | 8081 |
| LiteLLM | 4000 | 4001 |
| PostgreSQL | 5432 | 5433 |
| Neo4j HTTP | 7474 | 7475 |
| Neo4j Bolt | 7687 | 7688 |

## Verify Deployment

```bash
# Check pods (EKS)
kubectl get pods -n solidai-sre

# Check containers (Docker)
docker compose ps

# Test health endpoints
curl http://localhost:8001/health
curl http://localhost:8081/health
```

## Troubleshooting

**AWS SSO login issues:**
```bash
aws sso login --profile solidai-sre
# Follow browser prompt
```

**Docker not starting:**
```bash
sudo systemctl start docker
sudo usermod -aG docker $USER
# Logout/login or run: newgrp docker
```

**OpenRouter API key missing:**
```bash
# Edit .env file
nano /home/yassin/solidai-sre/.env
# Add: OPENROUTER_API_KEY=sk-or-v1-xxx
```

---

**Powered by SolidAI — Building the Future of African Tech** 🚀
