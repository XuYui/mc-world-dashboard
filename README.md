# mc-world-dashboard

给小型 Minecraft 服务器（Paper + [squaremap](https://github.com/jpenilla/squaremap)）配的存档网页：不进游戏也能看到地图、谁在线、大家玩到了哪一步、每次联机发生了什么，以及每个人的玩法风格。

它挂在 squaremap 自带的网页服务器上，不用另开端口；数据由一个只读脚本每分钟从存档和服务器日志里算出来，不改游戏本身。另附一个可选的小插件，把每一次死亡记成地图上的墓碑。

*A web dashboard for small Paper servers running squaremap: live map, who is online, team progress, a log of every play session, and per-player play-style radar charts and titles. It is served by squaremap's own web server, built from a read-only script over the save and server logs, plus an optional plugin that pins every death on the map as a gravestone. UI text is Chinese (names and messages come from the game's own language files, so other languages are possible).*

## 功能

- **地图**：嵌入 squaremap，可切换主世界 / 下界 / 末地；点在线玩家的头像就跟随他，缩放和拖动都不会丢失跟随，过传送门自动切维度。
- **状态栏**：服务器是否在线、谁在线（所在维度、血量、饱食度、在线时长）、游戏内第几天、昼夜和天气。
- **主线**：从挖石头到击败末影龙的 10 个关键成就，显示全队最早完成的时间；可展开全部成就。
- **联机日志**：按上下线时间自动切分每次游玩（断线 15 分钟内算同一次），列出参与者、时长、新成就（标出全队首次）、死亡记录；装了插件后每次死亡都能一键跳到地图上的位置。
- **玩家**：战斗 / 挖矿 / 建造 / 探索 / 生存 / 农业厨艺六维雷达图（可切换「每小时」看风格或「总量」看贡献），以及约 55 种自动称号（伐木工、铁匠、钻石大亨、拆弹专家、船长……），每个称号写明依据。
- **墓碑插件（DeathMarkers）**：记录每次死亡的时间、坐标和死亡消息，在 squaremap 上以墓碑图层显示。
- **导出地图**：在浏览器里把当前视野或整个已探索区域拼成 PNG（可选比例、可加存档名和坐标说明）；原清晰度的完整地图太大，由服务器每天凌晨用 libvips 拼好，面板里直接下载。
- **服务器负载（DashboardHealth）**：状态栏显示 TPS 和每刻耗时，点开有内存、CPU、区块、实体和最近一小时曲线。
- 方块材质风格的界面，标题和数字用游戏同款像素字体；手机、平板可用。

## 要求

- Paper 26.1.x 服务器（测试于 26.1.2），装有 squaremap 并开启其内置网页服务器
- 服务器上有 Python 3.9+ 和 systemd；插件需要 JDK 25 来编译；原清晰度地图需要 `vips` 命令（`apt install --no-install-recommends libvips-tools`，可选）
- 一台装有同版本 Minecraft 客户端的电脑，用来生成游戏资源（见下）
- 正版或离线模式均可；离线模式下头像使用游戏按 UUID 分配的默认皮肤

## 关于游戏资源（重要）

方块贴图、默认皮肤、语言文件和位图字体属于 Mojang，**本仓库不包含任何游戏资源**。请用你自己的客户端生成：

```bash
pip install pillow fonttools brotli
python tools/build_assets.py --minecraft "C:/Users/你/AppData/Roaming/.minecraft" --version 26.1.2
```

它会生成 `dashboard/defs.json`、`dashboard/static/{tex,skins,heads}/`、`dashboard/static/mcpixel.woff2` 和 `plugins/build/lang.json`（都已在 `.gitignore` 中）。像素字体的中文部分来自游戏附带的 GNU Unifont（SIL OFL 1.1）。

## 安装

1. 生成游戏资源（上一节）。
2. `cp deploy/config.example deploy/config`，填好 SSH 地址、服务器目录和运行服务器的用户。
3. 部署网页：`./deploy/deploy.sh`；连同插件：`./deploy/deploy.sh --plugin`（插件在下次重启服务器后加载）。
4. 在服务器上把 `/opt/mc-dashboard/dashboard.env.example` 复制为 `dashboard.env`，至少设置 `DASH_WORLD`（存档文件夹名），然后 `systemctl start mc-dashboard.service`。各项设置见 [dashboard/dashboard.env.example](dashboard/dashboard.env.example)。
5. 可选：把 squaremap `config.yml` 里的 `heads-url` 改成 `dashboard/heads/{uuid}.png`，地图上的玩家头像就和网页一致（重启后生效）。

完成后打开 `http://服务器:8123/` 即是网页，squaremap 原来的页面在 `/map.html`。squaremap 每次启动会覆盖首页，脚本会在一分钟内自动换回来。

需要域名和 HTTPS 时，可以用 nginx 反向代理到 `127.0.0.1:8123`，见 [dashboard/nginx/mc-dashboard.conf.example](dashboard/nginx/mc-dashboard.conf.example)。

## 工作方式

```
存档 (stats / advancements / playerdata / level)  ─┐
服务器日志 (上下线、死亡、启动)                     ├─ gen.py（每分钟，只读）─→ squaremap/web/dashboard/data.json
DeathMarkers 的 deaths.json                       ─┘                             │
squaremap 实时 players.json ───────────────────────────────── 网页（同源）←──────┘
```

- `dashboard/fullmap.py`：每天 04:50（`mc-fullmap.timer`）把每个维度的原清晰度图块拼成一张 PNG；libvips 按条带流式处理，内存占用很小。
- `dashboard/gen.py`：数据生成脚本，只用 Python 标准库。服务器日志会被复制一份到 `state/logs/`，以免服务器清理旧日志后联机记录丢失。
- `dashboard/static/`：网页（无框架、无构建步骤）。`maphook.js` 被注入 squaremap 页面，用来拿到它的 Leaflet 地图以实现跟随。
- `plugins/`：两个可选插件。DeathMarkers 记录死亡并画墓碑；DashboardHealth 每 5 秒把 TPS、每刻耗时、内存和 CPU 写进 `dashboard/health.json`，状态栏会显示。`build.sh` 直接用服务器自带的库编译，不需要 Gradle。
- `tools/`：从客户端生成游戏资源和像素字体。

## 隐私

服务器日志里有玩家 IP，AuthMe 等插件也会存 IP；脚本只取解析后的事件（上下线、死亡、成就），从不把原始日志或 IP 放进网页数据。网页本身没有登录，知道地址的人都能看到地图、坐标和每个人的上线时间，请按需自行加访问控制。

## License

MIT, see [LICENSE](LICENSE). Minecraft is a trademark of Mojang AB; this project is not affiliated with Mojang or Microsoft.
