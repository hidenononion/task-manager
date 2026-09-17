#!/bin/bash
# Deploy script for VPS (Ubuntu/Debian)
# Chay voi quyen root: sudo bash deploy.sh

set -e

APP_DIR="/var/www/taskmanager"
REPO_URL="https://github.com/YOUR_USERNAME/task-manager.git"
DOMAIN="dtnlamkhe.com"

echo "=========================================="
echo "  Deploy Task Manager to VPS"
echo "=========================================="

# 1. Install dependencies
echo "[1/6] Installing system packages..."
apt update
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 2. Create app directory
echo "[2/6] Setting up app directory..."
mkdir -p $APP_DIR
cd $APP_DIR

# 3. Clone or update repo
if [ -d ".git" ]; then
    echo "Pulling latest changes..."
    git pull
else
    echo "Cloning repository..."
    git clone $REPO_URL .
fi

# 4. Setup Python virtual environment
echo "[3/6] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Setup Gunicorn service
echo "[4/6] Creating systemd service..."
cat > /etc/systemd/system/taskmanager.service <<EOF
[Unit]
Description=Task Manager Gunicorn
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/gunicorn wsgi:app --workers 3 --bind unix:taskmanager.sock
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start taskmanager
systemctl enable taskmanager

# 6. Setup Nginx
echo "[5/6] Configuring Nginx..."
cat > /etc/nginx/sites-available/taskmanager <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        include proxy_params;
        proxy_pass http://unix:$APP_DIR/taskmanager.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static {
        alias $APP_DIR/static;
        expires 30d;
    }
}
EOF

ln -sf /etc/nginx/sites-available/taskmanager /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

# 7. Setup SSL with Certbot
echo "[6/6] Setting up SSL..."
certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN

echo ""
echo "=========================================="
echo "  Deploy thanh cong!"
echo "  https://$DOMAIN"
echo "=========================================="
