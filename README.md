# mc-world-dashboard

[English](README.en.md)

给小型 Minecraft 服务器（Paper）配的存档网页：不进游戏也能看到地图、谁在线、大家玩到了哪一步、每次联机发生了什么，以及每个人的玩法风格。

它是一个独立的小网站：一个 Paper 插件实时上报事件和状态，一个只用 Python 标准库的后端把它们和存档、日志一起整理成网页。地图图块沿用 [squaremap](https://github.com/jpenilla/squaremap) 渲染的图片，网页和地图界面是自己的；任何按同样目录格式输出图块的渲染器都可以替换 squaremap。

## 功能

- **地图**：自己的 Leaflet 地图，可切换主世界 / 下界 / 末地；在线玩家实时显示，点头像跟随（缩放、拖动后不丢失，过传送门自动切维度）；鼠标处显示坐标。
- **死亡墓碑**：「最近死亡」（每人最近一次，附可点击列表）和「历史死亡」两个互斥图层，悬停可看死亡消息和时间。
- **导出地图**：把当前视野或整个已探索区域拼成 PNG（可选比例和说明文字）；原清晰度的完整地图由服务器每天用 libvips 拼好，直接下载。
- **状态栏**：服务器是否在线、谁在线（维度、血量、饱食度、在线时长）、游戏内第几天、昼夜和天气、TPS；点开有内存、CPU、区块、实体和最近一小时曲线。
- **主线**：从挖石头到击败末影龙的 10 个关键成就（全队最早完成时间），可展开全部成就。
- **联机日志**：自动切分每次游玩，列出参与者、时长、新成就（标出全队首次）、死亡（可跳到地图位置），分页加载。
- **玩家**：六维雷达图（按累计总量）、约 55 种自动称号（每个写明依据）、上次死亡点和重生点。
- 方块材质风格界面，标题和数字用游戏同款像素字体；手机、平板可用。网站自带健康检查，后台或插件出问题会在页面顶部提示。

## 结构

```
Paper 服务器
 ├─ plugin/  WorldDashboard 插件：events.jsonl（上下线、死亡带坐标、启停）
 │                              live.json  （在线玩家、TPS、内存、CPU，每 2 秒）
 └─ squaremap（只用来渲染图块：tiles/<世界>/<缩放>/<x>_<z>.png）
                 │
server/mcdash  后端（Python 标准库 + SQLite）
 ├─ 事件入库：插件事件；装插件之前的历史从服务器日志导入
 ├─ 读取存档：统计、成就、玩家数据、时间天气（按文件修改时间缓存）
 ├─ /api/summary  /api/sessions  /api/live  /api/graves  /api/tiles
 ├─ /tiles/…  /heads/<uuid>.png  /fullmap/<世界>.png  以及网页本身
 └─ fullmap.py：每天把原清晰度图块拼成整张 PNG（需要 vips）
                 │
web/  网页（无框架、无构建步骤；Leaflet 1.9.4 已随附，BSD-2）
```

后端每 30 秒刷新一次，响应带 ETag 和 gzip，内容没变时浏览器只收到 304。Minecraft 停机时网站照常可以打开。

## 要求

- Paper 26.1.x（测试于 26.1.2）和 squaremap（只用来出图块，可关闭它自带的网页服务）
- 服务器：Linux + systemd、Python 3.9+；编译插件需要 JDK 25；原清晰度地图需要 `vips` 命令（`apt install --no-install-recommends libvips-tools`，可选）
- 一台装有同版本 Minecraft 客户端的电脑，用来生成游戏资源（见下）
- 正版或离线模式均可；离线模式下头像使用游戏按 UUID 分配的默认皮肤

## 关于游戏资源（重要）

方块贴图、默认皮肤、语言文件和位图字体属于 Mojang，**本仓库不包含任何游戏资源**。请用你自己的客户端生成：

```bash
pip install pillow fonttools brotli
python tools/build_assets.py --minecraft "C:/Users/你/AppData/Roaming/.minecraft" --version 26.1.2
```

会生成 `server/defs.json`、`web/assets/`（贴图、头像、像素字体）和 `plugin/build/lang.json`，都已在 `.gitignore` 中。像素字体的中文部分来自游戏附带的 GNU Unifont（SIL OFL 1.1）。

## 安装

1. 生成游戏资源（上一节）。
2. `cp deploy/config.example deploy/config`，填好 SSH 地址、安装目录、服务器目录和运行服务器的用户。
3. `./deploy/deploy.sh --plugin`：上传后端和网页、安装 systemd 服务 `mc-dashboard-web` 和每日的 `mc-fullmap.timer`，并在服务器上编译安装插件。插件在下次重启 Minecraft 后加载。
4. 编辑服务器上的 `/opt/mc-dashboard/dashboard.env`（从 [server/dashboard.env.example](server/dashboard.env.example) 复制而来），至少设置 `DASH_WORLD`（存档文件夹名），然后 `systemctl restart mc-dashboard-web`。
5. 默认网站监听 8123 端口。如果 squaremap 自带的网页服务也在用 8123，把它的 `config.yml` 里 `internal-webserver.enabled` 改成 `false`（图块照常渲染）。

以后更新只需要 `./deploy/deploy.sh`，不用重启 Minecraft。需要域名和 HTTPS 时，可以用 nginx 反向代理，见 [deploy/nginx.conf.example](deploy/nginx.conf.example)。

## 开发

- 后端测试：`cd server && python -m unittest discover -s tests`
- 插件编译：`SERVER_DIR=/opt/minecraft ./plugin/build.sh`（直接用服务器自带的库，不需要 Gradle）
- 编译好的插件 jar 也会发布在 [Releases](../../releases)。

## 隐私

服务器日志里有玩家 IP，AuthMe 等插件也会存 IP；后端只取解析后的事件（上下线、死亡），从不把原始日志或 IP 放进网页数据。网页本身没有登录，知道地址的人都能看到地图、坐标和每个人的上线时间，请按需自行加访问控制。

## License

MIT, see [LICENSE](LICENSE). Leaflet is BSD-2-Clause (`web/vendor/leaflet/LICENSE`). Minecraft is a trademark of Mojang AB; this project is not affiliated with Mojang or Microsoft.
