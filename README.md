# screen-share-live · 屏幕共享 + 双向通话

一个纯自建的「微信点开链接就能看你电脑实时屏幕 + 互相说话」系统。
无第三方服务、无登录，音视频走浏览器间 P2P 直连，服务器只做信令，几乎不占带宽。

- 线上地址（2026-09-18 上线）：`https://zhibo.jack-sun.com/`
  - 主播端：`https://zhibo.jack-sun.com/host.html`
  - 观众端：`https://zhibo.jack-sun.com/viewer.html?r=<房间token>`（由主播页自动生成）

## 用法

**主播（孙哥，电脑上）：**
1. Chrome/Edge 打开 `https://zhibo.jack-sun.com/host.html`
2. 首次输入主播密钥（见服务器 `/home/ubuntu/screen-share-live/config.json` 的 `hostSecret`），页面记住
3. 点「开始共享」→ 在 Chrome 弹窗里选要共享的屏幕（主屏/副屏/任意窗口都行）→ 允许麦克风
4. 复制「观众链接」发给对方（微信里直接点开）
5. 点「结束共享」即挂断，链接立刻失效（下次开播是新 token）

**观众（对方，手机即可）：**
1. 微信里点开链接 → 点「加入观看」→ 允许麦克风
2. 看屏幕，直接说话就是通话；底部有闭麦 / 全屏 / 挂断
3. 如果微信内嵌浏览器不配合，右上角菜单「用浏览器打开」再试

## 架构

```
Mac 主播页 ─┐                          ┌─ 观众手机
            ├─ WebRTC P2P 直连（音视频）─┤
            └── WSS 信令 ── nginx ── node(8018) ──┘
                     打洞失败时走 coturn 中继(3478/UDP)
```

- `server.js`：信令 + 静态页托管（Node，`ws` 单依赖）
- `web/host.html`：主播页（采集、编码 H.264 优先、限码率 2.5Mbps/15 帧、状态与码率面板）
- `web/viewer.html`：观众页（看屏 + 回传麦克风）
- `config.json`：端口、主播密钥、ICE 列表（STUN + TURN）
- `test/e2e.py`：端到端自动化测试（见下）

安全设计：观众 token 随机 128bit、一次直播一个、挂断即销毁；主播密钥才可建房；
主播断线 90 秒内可恢复房间，超时自动销毁。

## 功能（2026-09-18）

- 容量：mesh 架构，上限 **8 观众**（满员服务器拒绝并提示「观众已满」）；不占服务器带宽，瓶颈在主播上行（每路约 1-2.5Mbps）
- 观众管理：主播可对单个观众 🔇 静音（不听 TA）/ 踢出（移出直播间，对方看到「你已被主播移出」）
- 文字聊天：双向；主播可发「全体观众」或指定某观众；手机端底栏「聊天」按钮弹面板，未读带数字提示；观众发言限频 0.8 秒/条、单条 500 字
- 主播控制台：我的麦克风电平条 + 闭麦；对方电平条；喇叭音量 + 静音对方；码率/RTT/直连-中继显示
- 防缓存：HTML 全站 no-cache + 构建号（页脚可见），`./deploy.sh` 一键部署自动注入构建时间

## 2026-10-19 新增（观众互通 + 一批体验功能）
- **观众之间互相通话**：主播页做 mix-minus 混音转发——每位观众多收一条「其他观众混音」专线（sendonly 音轨，排在主播麦克风/系统声音之后），不含 TA 自己的声音所以没有回声；观众之间不建连接，不增加中继流量。主播底栏「观众互通」总开关 + 音频台「观众互通」推子（0-200%）。观众端显示「🎙 某某 正在说话」，开关变化/有人进出都有提示。
- **观众之间文字群聊**：观众发的消息除了主播，其他观众也能看到（带称呼）。
- **被移出更客气**：随机趣味文案（「先去喝杯茶吧 🍵」等 7 条）+ 60 秒休息倒计时，到点出现「我回来啦」按钮。服务器按设备 ID 记休息期，刷新也进不来。顺带修复老 bug：被踢的人以前会被自动重连带回直播间。
- **换屏幕不断流**：底栏「换屏幕」重新选屏幕/窗口，replaceTrack 替换所有观众的视频轨，链接不变、无人掉线；录制中会自动分段保存后接着录。
- **二维码**：顶栏「二维码」，身边的人微信扫一扫直接进（库 `web/assets/qrcode.js`，qrcode-generator 1.4.4，MIT，自托管）。
- **全员静音 / 全员解除** + **提示音**（有人进出、切到别的窗口时来消息，只在主播本机响，可关）。
- **观众端**：双指缩放 / 双击放大到 2.5× / 放大后单指拖动 / 电脑滚轮缩放；屏幕常亮（Wake Lock）；首次在手机上看提示可放大。
- **没填称呼自动认机型**：iPhone 按屏幕尺寸+像素密度推算机型档位；安卓先用 Client Hints 拿真实型号，再按 vivo/OPPO/小米/华为/三星编码规律补品牌；同款重名自动加「2号」。
- **服务器健壮性**：/dl/ 下载跳转前的 CDN 探测加了单次 3 秒超时 + 总 12 秒上限（之前连接挂住会让下载永远转圈）。

测试：`node test/party_test.js`（本机，端口 8019）/ `node test/party_test.js https://zhibo.jack-sun.com`（线上），1 主播 + 2 观众 23 项断言。
本机 8018 被别的服务占用时：`SSL_PORT=8019 python3 test/e2e.py`。

## 本机开发与测试

```bash
cd ~/Documents/screen-share-live
npm install
python3 test/e2e.py                       # 本机模式：起服务 + 两个 headless 浏览器跑全链路
python3 test/e2e.py https://zhibo.jack-sun.com   # 打线上跑全链路
```

e2e 原理：页面 `?fake=1` 时用 canvas 假画面 + 假音频代替真实采集（绕开屏幕选择器 UI），
两个 headless Edge 实例分别当主播和观众，轮询 `document.title` 判定
（`H:live:v1` = 有观众，`V:playing` = 视频字节持续增长）。真实屏幕选择器需手动验证。

## 服务器部署（腾讯云 jacksun-tencent）

| 组件 | 位置 |
|---|---|
| 代码 | `/home/ubuntu/screen-share-live/` |
| 信令服务 | systemd: `screen-share-signaling.service`（node24，开机自启） |
| nginx | 宝塔：`/www/server/panel/vhost/nginx/zhibo.jack-sun.com.conf`（443 + WS 反代 8018） |
| TURN | `/etc/turnserver.conf`（3478/UDP，中继端口 49160-49200/UDP），systemd: `coturn` |

代码更新流程：本机改完 → `rsync`（排除 config.json/node_modules/test）→ `sudo systemctl restart screen-share-signaling`。
页面是静态文件，改完即生效无需重启。

**TURN 状态**（2026-09-18 深夜修通）：UDP/TCP 双通道中继均实测 0 丢包，浏览器强制中继（`iceTransportPolicy: 'relay'`）e2e PASS。
踩过的坑（详见记忆库 turn-deploy-silent-failure-chain）：heredoc `\$` 转义吞掉密码变量、sudo 写配置 umask 600 导致 turnserver 用户读不了配置静默裸奔。
验收命令：无凭证 Allocate 应 401；`python3 test/e2e.py https://zhibo.jack-sun.com relay` 强制中继全绿。

**安全组要求**（腾讯云控制台）：3478/UDP+TCP 与 49160-49200/UDP 放行 = TURN 中继可用；
未放行时系统照常工作（P2P 打洞不经安全组），只是打洞失败的场景没有兜底。服务器本机 ufw 也需同步放行。

## 里程碑

- 2026-09-17：想法提出，方案论证（WebRTC + H.264 + 微信兼容）
- 2026-09-18：v0.1 上线——信令/主播页/观众页/coturn 部署完成，本机与线上 e2e 全绿

## 后续可做

- 专门的 `live.jack-sun.com` 子域（需孙哥在 DNSPod 加 A 记录，其余现成）
- Electron 小工具：ScreenCaptureKit 屏+系统声一步到位、菜单栏常驻一键开播（第二版需求，含共享电脑声音）
- 多房间 / 观众数量展示优化 / 画质自适应
