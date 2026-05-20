#!/usr/bin/env bash
set -euo pipefail

# SolidAI SRE — EKS Full Deployment Script
# Usage: ./deploy-eks.sh <cluster-name> <region>

CLUSTER_NAME=${1:-solidai-sre-cluster}
REGION=${2:-us-east-1}
NAMESPACE=solidai-sre

echo "🚀 SolidAI SRE — EKS Deployment"
echo "  Cluster: $CLUSTER_NAME"
echo "  Region:  $REGION"
echo ""

# 1. Login to AWS SSO
echo "[1/6] AWS SSO Login..."
aws sso login --profile solidai-sre

# 2. Update kubeconfig
echo "[2/6] Updating kubeconfig..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --profile solidai-sre

# 3. Create namespace
echo "[3/6] Creating namespace: $NAMESPACE"
kubectl create namespace "$NAMESPACE" 2>/dev/null || echo "  Namespace exists"

# 4. Create secrets from .env
echo "[4/6] Creating Kubernetes secrets..."
kubectl create secret generic solidai-sre-secrets \
  --from-env-file=/home/yassin/solidai-sre/.env \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

# 5. Deploy with Helm or kubectl
echo "[5/6] Deploying SolidAI SRE stack..."
cd /home/yassin/solidai-sre

# Deploy PostgreSQL
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: $NAMESPACE
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        env:
        - name: POSTGRES_USER
          value: "solidai"
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: solidai-sre-secrets
              key: POSTGRES_PASSWORD
        - name: POSTGRES_DB
          value: "solidai-sre"
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-pvc
EOF

# 6. Deploy LiteLLM
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: litellm
  template:
    metadata:
      labels:
        app: litellm
    spec:
      containers:
      - name: litellm
        image: ghcr.io/berriai/litellm:main-latest
        ports:
        - containerPort: 4000
        env:
        - name: OPENROUTER_API_KEY
          valueFrom:
            secretKeyRef:
              name: solidai-sre-secrets
              key: OPENROUTER_API_KEY
        command: ["--config", "/app/config.yaml", "--port", "4000"]
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: litellm_config.yaml
      volumes:
      - name: config
        configMap:
          name: litellm-config
---
apiVersion: v1
kind: Service
metadata:
  name: litellm
  namespace: $NAMESPACE
spec:
  selector:
    app: litellm
  ports:
  - port: 4000
    targetPort: 4000
EOF

# 7. Deploy SRE Agent
kubectl apply -f /home/yassin/solidai-sre/sre-agent/k8s/sandbox-template.yaml -n "$NAMESPACE"

# 8. Deploy Web UI
echo "[6/6] Deploying Web UI..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-ui
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: web-ui
  template:
    metadata:
      labels:
        app: web-ui
    spec:
      containers:
      - name: web-ui
        image: node:18-alpine
        ports:
        - containerPort: 3000
        command: ["npm", "run", "start"]
        workingDir: /app
        env:
        - name: CONFIG_SERVICE_URL
          value: "http://config-service:8080"
        - name: AGENT_SERVICE_URL
          value: "http://sre-agent:8000"
        volumeMounts:
        - name: app
          mountPath: /app
      volumes:
      - name: app
        hostPath:
          path: /home/yassin/solidai-sre/web_ui
EOF

echo ""
echo "✅ Deployment complete!"
echo "   Web UI: kubectl port-forward -n $NAMESPACE svc/web-ui 3002:3000 &"
echo "   SRE Agent: kubectl port-forward -n $NAMESPACE svc/sre-agent 8001:8000 &"
echo "   Config: kubectl port-forward -n $NAMESPACE svc/config-service 8081:8080 &"
