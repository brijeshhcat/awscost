#!/bin/bash
# ---------------------------------------------------------------
#  AWS Cost Optimizer – EC2 Deployment Script (Amazon Linux 2023)
#  Run this on a fresh EC2 instance with an IAM role attached.
# ---------------------------------------------------------------
set -euo pipefail

APP_DIR="/home/ec2-user/awscost"

echo "==> Updating system packages..."
sudo yum update -y

echo "==> Installing Python 3.12 & pip..."
sudo yum install -y python3.12 python3.12-pip git

echo "==> Setting up application directory..."
cd "$APP_DIR"

echo "==> Creating virtual environment..."
python3.12 -m venv venv
source venv/bin/activate

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

echo "==> Installing systemd service..."
sudo cp awscost.service /etc/systemd/system/awscost.service
sudo systemctl daemon-reload
sudo systemctl enable awscost
sudo systemctl start awscost

echo "==> Checking service status..."
sudo systemctl status awscost --no-pager

PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<your-public-ip>")
echo ""
echo "============================================="
echo "  Deployment complete!"
echo "  Access the app at: http://${PUBLIC_IP}:5000"
echo "============================================="
