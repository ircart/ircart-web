#!/bin/sh
# IRCart - Developed by acidvegas in Python (https://git.supernets.org/ircart)
# setup.sh

# Clones the art repository, creates .env on first run & builds/starts the container.
# Run as the user that owns this directory (uid 1001 / supernets on super-svc).

set -e

cd "$(dirname "$0")"

ART_REPO='https://git.supernets.org/ircart/ircart.git'

command -v docker >/dev/null || { echo 'missing docker'; exit 1; }

if [ ! -d art/.git ]; then
	git clone -q "$ART_REPO" art
	echo "cloned $ART_REPO into art/"
fi

if [ ! -f .env ]; then
	umask 077
	ADMIN_PASS="$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20)"
	SECRET_KEY="$(tr -dc 'a-f0-9' < /dev/urandom | head -c 64)"
	cat > .env <<EOF
ADMIN_USER=acidvegas
ADMIN_PASS=$ADMIN_PASS
SECRET_KEY=$SECRET_KEY
SITE_URL=https://ircart.supernets.org
SECURE_COOKIES=1
EOF
	echo "created .env, admin login is acidvegas / $ADMIN_PASS"
fi

mkdir -p data

docker compose up -d --build
echo 'ircart is running on 127.0.0.1:9009'
