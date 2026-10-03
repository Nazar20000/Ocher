#!/bin/sh
set -eu

CERT="/etc/letsencrypt/live/ocher.hikmatullo.site/fullchain.pem"
TEMPLATE_DIR="/etc/nginx/site-templates"

pick_config() {
    if [ -f "$CERT" ]; then
        cp "$TEMPLATE_DIR/ssl.conf" /etc/nginx/conf.d/default.conf
    else
        cp "$TEMPLATE_DIR/http.conf" /etc/nginx/conf.d/default.conf
    fi
}

pick_config

(
    mode=http
    [ -f "$CERT" ] && mode=ssl
    while true; do
        sleep 15
        next=http
        [ -f "$CERT" ] && next=ssl
        if [ "$next" != "$mode" ]; then
            pick_config
            nginx -s reload || true
            mode=$next
        fi
    done
) &

exec nginx -g "daemon off;"
