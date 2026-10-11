#!/usr/bin/env python3
"""Render only this module's nginx site; never modify nginx's default site."""
import argparse
import ipaddress
from pathlib import Path

MARKER = "# Managed by NoteLite OMR gateway deployment v1"


def render(ip: str, stage: str) -> str:
    address = ipaddress.ip_address(ip)
    if address.version != 4:
        raise ValueError("This deployment targets an IPv4 Lighthouse instance")
    ip = str(address)
    http = f"""{MARKER}
server {{
    listen 80;
    server_name {ip};
    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/notelite-acme;
        default_type text/plain;
        try_files $uri =404;
    }}
    location / {{ return 308 https://{ip}$request_uri; }}
}}
"""
    if stage == "bootstrap":
        return http
    if stage != "https":
        raise ValueError("unknown deployment stage")
    return http + f"""
server {{
    listen 443 ssl;
    server_name {ip};
    if ($host != {ip}) {{ return 444; }}
    ssl_certificate /etc/letsencrypt/live/{ip}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{ip}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:NoteLiteTLS:5m;
    ssl_session_timeout 1h;
    root /var/www/notelite-ui;
    index index.html;
    client_max_body_size 32m;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header Permissions-Policy "microphone=(self), camera=()" always;
    location ^~ /api/ {{
        proxy_pass http://127.0.0.1:8770;
        proxy_http_version 1.1;
        proxy_set_header Host {ip};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection "";
        proxy_request_buffering on;
        proxy_connect_timeout 5s;
        proxy_read_timeout 190s;
        proxy_send_timeout 190s;
        proxy_buffering off;
        add_header Cache-Control no-store always;
    }}
    location = /index.html {{ add_header Cache-Control no-store always; }}
    location ^~ /assets/ {{
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }}
    location / {{ try_files $uri $uri/ /index.html; }}
}}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="124.221.211.156")
    parser.add_argument("--stage", choices=("bootstrap", "https"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = render(args.ip, args.stage)
    if args.output:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
