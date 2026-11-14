#!/usr/bin/env bash
# 装好网站后台（访问统计、写日记、管理吃饭地图的店和扫街照片）。在服务器上运行（只需一次）：
#   sudo bash /var/www/beyond-horizons/deploy/admin-setup.sh
# 它会：让你设一个后台密码（输入时不显示，只存哈希）→ 装好后台服务（本机 127.0.0.1:8788，开机自启）
#      → 在网站的 nginx 配置里加上 /api/stat、/api/diary、/api/admin、/api/u 转发（检查不通过就还原）。
# 之后打开 你的网址/admin/ 用这个密码登录。改密码：sudo bash …/admin-setup.sh --password
# 网站更新后只更新后台程序（不用重设密码）：sudo bash …/admin-setup.sh --update
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "请在命令前加 sudo 再运行"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
ENVF=/etc/beyond-horizons/admin.env
command -v python3 >/dev/null || { apt-get update -qq; apt-get install -y -qq python3 >/dev/null; }

echo "==> 安装后台程序"
install -d -m 755 /opt/beyond-horizons /opt/beyond-horizons/ip2region
install -m 644 "$HERE/bh_admin.py" /opt/beyond-horizons/bh_admin.py
install -m 644 "$HERE/ip2region_v4.xdb" /opt/beyond-horizons/ip2region_v4.xdb
install -m 644 "$HERE"/ip2region/*.py "$HERE/ip2region/LICENSE" /opt/beyond-horizons/ip2region/
install -m 644 "$HERE/bh-admin.service" /etc/systemd/system/bh-admin.service

if [ "${1:-}" = "--password" ] || [ ! -f "$ENVF" ] || ! grep -q '^ADMIN_PASS=' "$ENVF"; then
  echo
  P1=""; P2="x"
  while [ "$P1" != "$P2" ] || [ ${#P1} -lt 8 ]; do
    read -rsp "设一个后台密码（至少 8 位，输入时屏幕上不显示）: " P1; echo
    read -rsp "再输一次: " P2; echo
    if [ ${#P1} -lt 8 ]; then echo "太短了，至少 8 位"; elif [ "$P1" != "$P2" ]; then echo "两次不一样，再来"; fi
  done
  HASH=$(printf '%s' "$P1" | python3 -c 'import hashlib,os,sys; s=os.urandom(16); p=sys.stdin.read().encode(); print("pbkdf2_sha256:260000:%s:%s" % (s.hex(), hashlib.pbkdf2_hmac("sha256", p, s, 260000).hex()))')
  unset P1 P2
  SECRET=$(grep -s '^ADMIN_SECRET=' "$ENVF" | cut -d= -f2- || true)
  [ -n "$SECRET" ] || SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  install -d -m 700 /etc/beyond-horizons
  ( umask 077; printf 'ADMIN_PASS=%s\nADMIN_SECRET=%s\n' "$HASH" "$SECRET" > "$ENVF" )
  chmod 600 "$ENVF"
  echo "==> 密码已设好（只存了哈希，在 $ENVF，只有 root 能读）"
fi

echo "==> 启动后台服务"
systemctl daemon-reload
systemctl enable bh-admin >/dev/null 2>&1
systemctl restart bh-admin
sleep 1.5
systemctl is-active --quiet bh-admin || { echo "后台服务没起来，看看报错："; journalctl -u bh-admin -n 20 --no-pager; exit 1; }

echo "==> 在网站的 nginx 配置里加上后台的转发"
NGX=$( [ -x /www/server/nginx/sbin/nginx ] && echo /www/server/nginx/sbin/nginx || command -v nginx || true )
changed=()
for f in /etc/nginx/sites-available/beyond-horizons* /etc/nginx/conf.d/beyond-horizons*.conf /www/server/panel/vhost/nginx/beyond-horizons*.conf; do
  [ -f "$f" ] || continue
  case "$f" in *.bak-admin|*.bak-pet) continue ;; esac
  grep -q '/api/stat' "$f" && continue
  grep -q 'try_files' "$f" || continue
  cp "$f" "$f.bak-admin"
  python3 - "$f" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
block = ('    # 网站后台（deploy/bh_admin.py）：访问统计、日记、照片\n'
         '    location ~ ^/api/(stat|diary|admin|u)(/|$) { proxy_pass http://127.0.0.1:8788; proxy_http_version 1.1; proxy_set_header Host $host; '
         'proxy_set_header X-Real-IP $remote_addr; proxy_read_timeout 30s; client_max_body_size 10m; }')
out = []
for line in s.split('\n'):
    if line.strip().startswith('location / {') and 'try_files' in line:   # 每个网站的 server { } 里都加一份
        out.append(block)
    out.append(line)
open(p, 'w', encoding='utf-8').write('\n'.join(out))
PY
  changed+=("$f")
done
if [ ${#changed[@]} -gt 0 ]; then
  if [ -n "$NGX" ] && "$NGX" -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || "$NGX" -s reload
    for f in "${changed[@]}"; do rm -f "$f.bak-admin"; echo "    已加到 $f"; done
  else
    for f in "${changed[@]}"; do mv -f "$f.bak-admin" "$f"; done
    echo "    nginx 配置检查没通过，已经还原，没有改动。把这段报错截图发给我："; "$NGX" -t || true; exit 1
  fi
else
  echo "    （已经加过了）"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' http://127.0.0.1:8788/api/diary || true)
echo
if [ "$code" = 200 ]; then echo "完成！打开 你的网址/admin/ （比如 https://www.howardleong.work/admin/），用刚才的密码登录。"
else echo "后台服务装好了，但测试没通过（$code），把这段截图发给我"; fi
