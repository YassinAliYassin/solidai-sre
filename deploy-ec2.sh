#!/usr/bin/env bash
set -euo pipefail

# SolidAI SRE — EC2 Deployment Script
# Deploys to EC2 instance (similar to VPS setup)

echo "🚀 SolidAI SRE — EC2 Deployment"
echo ""

# 1. Check if running on EC2 or local
if [ -f /sys/hypervisor/uuid ] && grep -q "ec2" /sys/hypervisor/uuid 2>/dev/null; then
    echo "[1/5] Running on EC2 instance"
    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
    echo "  Instance: $INSTANCE_ID"
else
    echo "[1/5] Not on EC2 — preparing for EC2 deployment"
fi

# 2. Install Docker if not present
if ! command -v docker &>/dev/null; then
    echo "[2/5] Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    sudo usermod -aG docker $USER
    echo "  Docker installed. You may need to logout/login."
else
    echo "[2/5] Docker already installed"
fi

# 3. Install docker-compose if not present
if ! command -v docker compose &>/dev/null; then
    echo "[3/5] Installing docker-compose..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
else
    echo "[3/5] docker-compose already available"
fi

# 4. Clone/update repo
echo "[4/5] Setting up SolidAI SRE..."
if [ -d /home/yassin/solidai-sre ]; then
    cd /home/yassin/solidai-sre && git pull origin main
else
    cd /home/yassin && git clone https://github.com/YassinAliYassin/solidai-sre.git
    cd solidai-sre
fi

# 5. Start services
echo "[5/5] Starting SolidAI SRE stack..."
cd /home/yassin/solidai-sre

# Ensure .env has all required vars
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Edit .env with your OpenRouter API key!"
fi

# Start all services
docker compose up -d

echo ""
echo "✅ SolidAI SRE deployed!"
echo ""
echo "Access points:"
echo "  Web UI:      http://$(curl -s ifconfig.me):3002"
echo "  SRE Agent:   http://$(curl -s ifconfig.me):8001"
echo "  Config Svc:  http://$(curl -s ifconfig.me):8081"
echo "  LiteLLM:     http://$(curl -s ifconfig.me):4001"
echo ""
echo "Check status: docker compose ps"
echo "View logs:   docker compose logs -f"
