#!/usr/bin/env bash
# Beyond Horizons：在 Ubuntu 服务器上用 nginx 把这个网站发布出去，并且每 15 分钟自动从 GitHub 同步最新版本。
# 在服务器上运行（一行，复制粘贴进终端）：
#   sudo apt-get install -y git && sudo git clone --depth 1 https://github.com/lhowd301-lab/lhowd301-lab.github.io.git /var/www/beyond-horizons && sudo bash /var/www/beyond-horizons/deploy/install.sh
# 重复运行也没关系。
set -euo pipefail
ROOT=/var/www/beyond-horizons
REPO=https://github.com/lhowd301-lab/lhowd301-lab.github.io.git
[ "$(id -u)" = 0 ] || { echo "请在命令前加 sudo 再运行"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> 安装 nginx 和 git"
apt-get update -qq
apt-get install -y -qq nginx git >/dev/null

if [ ! -d "$ROOT/.git" ] && [ ! -f "$ROOT/index.html" ]; then
  echo "==> 从 GitHub 下载网站（约 220 MB，视网络需要几分钟）"
  git clone --depth 1 "$REPO" "$ROOT"
fi
[ -f "$ROOT/index.html" ] || { echo "在 $ROOT 里没找到网站文件"; exit 1; }
git config --system --add safe.directory "$ROOT" 2>/dev/null || true

echo "==> 给文本文件生成压缩副本（访客下载量少一半左右）"
install -m 755 "$ROOT/deploy/update.sh" /usr/local/bin/bh-update
/usr/local/bin/bh-update --compress-only

echo "==> 配置 nginx"
install -m 644 "$ROOT/deploy/nginx.conf" /etc/nginx/sites-available/beyond-horizons
ln -sf /etc/nginx/sites-available/beyond-horizons /etc/nginx/sites-enabled/beyond-horizons
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null 2>&1 || true
systemctl restart nginx
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 80/tcp >/dev/null; fi

if [ -d "$ROOT/.git" ]; then
  echo "==> 每 15 分钟自动同步 GitHub 上的新版本"
  echo "*/15 * * * * root /usr/local/bin/bh-update >> /var/log/bh-update.log 2>&1" > /etc/cron.d/beyond-horizons
  chmod 644 /etc/cron.d/beyond-horizons
else
  echo "（网站是手动上传的，不是 git 下载的，所以不会自动同步更新）"
fi

IP=$(curl -s --max-time 3 http://metadata.tencentyun.com/latest/meta-data/public-ipv4 || true)
echo
echo "完成！在浏览器里打开： http://${IP:-你的服务器公网IP}"
echo "打不开的话，到腾讯云控制台这台服务器的「防火墙」里确认放通了 TCP 80 端口。"
