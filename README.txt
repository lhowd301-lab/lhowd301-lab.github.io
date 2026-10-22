Beyond Horizons · 静态网站

这个文件夹就是完整的网站，不需要后端，放到任何静态网站托管上都能用：
  · GitHub Pages：把整个文件夹的内容推到仓库，在 Settings → Pages 里选分支即可
  · Vercel / Netlify / Cloudflare Pages：把文件夹拖进去部署
  · 自己的服务器：当作普通静态文件放到网站目录

本地预览：
  直接双击 index.html 打不开地图（浏览器禁止本地文件读取数据），要用一个本地服务器：
    在这个文件夹里打开终端，运行  python3 -m http.server 8000
    然后浏览器打开  http://localhost:8000

地图引擎、星空计算库和等宽字体都已经放在 vendor/ 里，不依赖国外 CDN；只有天气数据来自 Open-Meteo（连不上时天气那一栏不显示，其余照常）。

目录：
  index.html   网页本体（数据都写在里面的 SITE 对象里）
  map/         地图标注、地形、星空数据、地标和桥梁的 3D 模型
  tilepack/    广州的矢量地图瓦片
  bridgepack/  3D 桥面瓦片
  photos/      扫街照片和地标头图
  icons/       社交图标
  music/       背景音乐
  vendor/      地图引擎、星空计算库、字体
