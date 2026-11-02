#!/usr/bin/env bash
# 给网站接上一个域名（80 端口，按域名区分，不影响服务器上原有的网站），再用 Let's Encrypt 免费证书开 HTTPS。
# 先在域名解析里把这个域名的 A 记录指向服务器公网 IP，再运行：
#   sudo bash /var/www/beyond-horizons/deploy/domain.sh map.howardleong.work
set -euo pipefail
D=${1:?用法：sudo bash domain.sh 域名}
SRC=/etc/nginx/sites-available/beyond-horizons
[ -f "$SRC" ] || { echo "先运行 deploy/install.sh"; exit 1; }
sed -e 's/listen [0-9]*;/listen 80;/' -e 's/listen \[::\]:[0-9]*;/listen [::]:80;/' -e "s/server_name _;/server_name $D;/" "$SRC" > "/etc/nginx/sites-available/beyond-horizons-$D"
ln -sf "/etc/nginx/sites-available/beyond-horizons-$D" /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "==> http://$D 已接上，申请 HTTPS 证书"
apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
certbot --nginx -d "$D" --redirect --agree-tos --register-unsafely-without-email -n
echo "完成： https://$D （证书会自动续期）"
