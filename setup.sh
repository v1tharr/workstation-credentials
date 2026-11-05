#!/usr/bin/env bash
# Создаёт .env с новыми ключами. Если .env уже есть — ничего не делает,
# чтобы случайно не затереть ключи, которыми зашифрована БД.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
    echo ".env уже существует, не трогаю"
    exit 0
fi

secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
fernet=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')

umask 077
sed -e "s|^SECRET_KEY=.*|SECRET_KEY=${secret}|" \
    -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${fernet}|" .env.example > .env

echo "Создан .env. Сохраните копию ENCRYPTION_KEY отдельно от бэкапов БД: без него данные не прочитать."
