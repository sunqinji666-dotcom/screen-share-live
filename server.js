#!/usr/bin/env node
/**
 * screen-share-live 信令服务
 *
 * 职责：
 *  - 房间管理（1 主播 + N 观众），token 鉴权，挂断即销毁
 *  - WebRTC 信令转发（SDP offer/answer、ICE candidate）
 *  - 托管 web/ 静态页面（线上由 nginx 反代到本服务，本机直接跑也能用）
 *
 * 音视频数据本身走浏览器间 P2P 直连，不经过本服务。
 */
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { WebSocketServer, WebSocket } = require('ws');

const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
const PORT = cfg.port || 8018;
const HOST_SECRET = cfg.hostSecret || '';
const ICE_SERVERS = cfg.iceServers || [];
// 管理后台登录（要改账号在这里改）
const ADMIN_USER = 'jacksun';
const ADMIN_PASS = 'jacksun1234';

// ---------------- 管理后台登录 ----------------
// 用户名+密码登录，连续错 5 次锁 10 分钟（防爆破）；会话令牌 24h，断线重连凭 token 秒恢复
// （2026-09-27 按孙哥要求移除图形验证码：验证码影响登录成功率，防爆破交由失败锁定）
let adminFails = 0, adminLockUntil = 0;
// 会话令牌：验证码登录成功一次后发放，之后断线重连凭 token 秒恢复（免验证码），24h 有效
const adminSessions = new Map(); // token -> 签发时间
const ADMIN_SESSION_TTL = 24 * 60 * 60 * 1000;
function newAdminSession() {
  for (const [k, ts] of adminSessions) if (Date.now() - ts > ADMIN_SESSION_TTL) adminSessions.delete(k);
  const token = crypto.randomBytes(24).toString('hex');
  adminSessions.set(token, Date.now());
  return token;
}
function checkAdminSession(token) {
  if (typeof token !== 'string' || !token) return false;
  const ts = adminSessions.get(token);
  return !!ts && Date.now() - ts <= ADMIN_SESSION_TTL;
}

function adminFail(ws) {
  adminFails++;
  if (adminFails >= 5) { adminLockUntil = Date.now() + 10 * 60 * 1000; adminFails = 0; }
  send(ws, { t: 'err', msg: 'bad-admin-credential' });
}

// ---------------- 访客码（多租户） ----------------
// 孙哥在后台生成访客码发给别人，对方拿码即可开播；guests.json 持久化，重启不丢
const GUESTS_FILE = path.join(__dirname, 'guests.json');
let guests = {};
try { guests = JSON.parse(fs.readFileSync(GUESTS_FILE, 'utf8')); } catch (_) { guests = {}; }
const saveGuests = () => {
  try { fs.writeFileSync(GUESTS_FILE, JSON.stringify(guests, null, 2)); }
  catch (e) { console.error('guests.json 写入失败:', e.message); }
};
const listGuests = () => Object.entries(guests).map(([code, g]) => ({
  code, name: g.name || '', createdAt: g.createdAt || 0, lastUsed: g.lastUsed || 0, disabled: !!g.disabled,
}));
// 8 位大写码，去掉易混字符（0O1I5S）
const genGuestCode = () => {
  const alphabet = 'ABCDEFGHJKLMNPQRTUVWXYZ23456789';
  let code;
  do { code = Array.from({ length: 8 }, () => alphabet[crypto.randomInt(alphabet.length)]).join(''); }
  while (code === HOST_SECRET || guests[code]);
  return code;
};
// 主播密钥鉴权：hostSecret → 管理员；guests.json 里未禁用的码 → 访客
function checkAuth(secret) {
  if (typeof secret !== 'string' || !secret) return null;
  if (secret === HOST_SECRET) return { type: 'admin' };
  const g = guests[secret];
  if (g && !g.disabled) return { type: 'guest', code: secret, name: g.name || '' };
  return null;
}
const WEB_DIR = path.join(__dirname, 'web');

// ---------------- 七牛直传（通话中发文件） ----------------
// 文件流浏览器↔七牛点对点，服务器只发上传凭证 + 下载时 302 跳转，不碰文件内容
const QN = cfg.qiniu || null; // { ak, sk, bucket, domain, upHost }
const QN_MAX_SIZE = 500 * 1024 * 1024; // 单文件上限 500MB（putPolicy 里同样限制）
const QN_KEY_PREFIX = 'zhibo';
// 七牛的 urlsafe base64 只替换 +/ 为 -_，保留 padding(=)——去 padding 会导致 BadToken
const urlsafeB64 = (buf) => Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_');

// 上传凭证：scope 限定到具体 key，过期 1 小时，大小上限在策略里
function qiniuUploadToken(key) {
  const putPolicy = JSON.stringify({
    scope: `${QN.bucket}:${key}`,
    deadline: Math.floor(Date.now() / 1000) + 3600,
    fsizeLimit: QN_MAX_SIZE,
  });
  const enc = urlsafeB64(putPolicy);
  const sign = crypto.createHmac('sha1', QN.sk).update(enc).digest();
  return `${QN.ak}:${urlsafeB64(sign)}:${enc}`;
}

// 下载 URL：该 bucket 为公开空间（实测裸 URL 200），且 CDN 域名配了时间戳防盗链——
// 带七牛私签参数（e&token）反而触发 403 forbidden，裸 URL 直接放行
function qiniuDownloadUrl(key) {
  return `${QN.domain}/${encodeURI(key)}`;
}

// 文件登记：fileId -> 七牛 key（持久化，重启不丢；只留最近 500 条）
const REGISTRY_FILE = path.join(__dirname, 'file-registry.json');
let fileRegistry = {};
try { fileRegistry = JSON.parse(fs.readFileSync(REGISTRY_FILE, 'utf8')); } catch (_) { fileRegistry = {}; }
const saveRegistry = () => {
  try {
    const entries = Object.entries(fileRegistry).sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0)).slice(-500);
    fileRegistry = Object.fromEntries(entries);
    fs.writeFileSync(REGISTRY_FILE, JSON.stringify(fileRegistry, null, 2));
  } catch (e) { console.error('file-registry.json 写入失败:', e.message); }
};
const pendingUploads = new Map(); // fileId -> { key, name, size, ts }（上传中，1 小时未确认作废）
const HOST_GRACE_MS = 90000; // 主播信令断开后房间保留 90 秒等重连（媒体流不受影响）；跨运营商/手机网络抖动 30 秒太短，观众会集体被踢
const MAX_VIEWERS = 8;       // mesh 架构上限：主播为每人单独推流，瓶颈在主播上行带宽
const CHAT_MAX_LEN = 500;
const CHAT_INTERVAL_MS = 800; // 观众发言限频

// ---------------- 房间 ----------------
// room(viewerToken) -> { host, hostToken, viewers: Map<vid, ws>, closeTimer }
const rooms = new Map();

const rid = () => crypto.randomBytes(8).toString('hex');
const send = (ws, obj) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); };

function destroyRoom(room, reason) {
  const r = rooms.get(room);
  if (!r) return;
  rooms.delete(room);
  if (r.closeTimer) clearTimeout(r.closeTimer);
  r.viewers.forEach((v) => send(v, { t: 'bye', reason }));
  send(r.host, { t: 'bye', reason });
}

// 禁用/删除访客码即刻生效：销毁该码名下的所有在线房间
function destroyRoomsOf(code, reason) {
  for (const [room, r] of rooms) {
    if (r.owner && r.owner.type === 'guest' && r.owner.code === code) destroyRoom(room, reason);
  }
}

// ---------------- HTTP：静态页 ----------------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  let p = new URL(req.url, 'http://x').pathname;
  if (p === '/') p = '/index.html';
  // 文件下载跳转：https 页面点 https 链接 → 302 到七牛 CDN（下载导航允许 http），文件流量不经过本服务
  if (p.startsWith('/dl/')) {
    const rec = fileRegistry[p.slice(4)];
    if (!rec || !QN) { res.writeHead(404); return res.end('文件不存在或已过期'); }
    const target = qiniuDownloadUrl(rec.key);
    // 七牛上传响应 200 后，CDN 边缘有几秒「不可读」窗口（首访 403）——观众刚弹窗就点会撞上。
    // 新文件先 HEAD 探测到可读再跳（最多 12 秒），老文件直接跳。
    if (Date.now() - (rec.ts || 0) > 10000) { res.writeHead(302, { Location: target }); return res.end(); }
    let tries = 0;
    const jump = () => { res.writeHead(302, { Location: target }); res.end(); };
    const probe = () => {
      tries++;
      const preq = http.request(target, { method: 'HEAD' }, (pres) => {
        pres.resume();
        if (pres.statusCode === 200 || tries >= 6) return jump();
        setTimeout(probe, 2000);
      });
      preq.on('error', () => { if (tries >= 6) return jump(); setTimeout(probe, 2000); });
      preq.end();
    };
    probe();
    return;
  }
  const file = path.normalize(path.join(WEB_DIR, p));
  if (!file.startsWith(WEB_DIR + path.sep)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-cache', // 页面要始终拿到最新版（有构建号可核对）
    });
    res.end(buf);
  });
});

// ---------------- WebSocket 信令 ----------------
const wss = new WebSocketServer({ server, path: '/ws' });

wss.on('connection', (ws) => {
  console.log('[conn] open', new Date().toISOString());
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });
  ws.role = null; // 'host' | 'viewer'

  ws.on('message', (raw) => {
    let m;
    try { m = JSON.parse(raw); } catch (_) { return; }

    switch (m.t) {
      case 'host-create': {
        const auth = checkAuth(m.secret);
        if (!auth) return send(ws, { t: 'err', msg: 'bad-secret' });
        if (ws.role === 'host' && ws.room) destroyRoom(ws.room, 'recreate');
        const room = rid();
        const hostToken = rid();
        rooms.set(room, { host: ws, hostToken, viewers: new Map(), closeTimer: null, owner: auth, startedAt: Date.now() });
        ws.role = 'host';
        ws.room = room;
        if (auth.type === 'guest') { guests[auth.code].lastUsed = Date.now(); saveGuests(); }
        send(ws, { t: 'host-ok', room, hostToken, ice: ICE_SERVERS });
        break;
      }

      case 'host-resume': {
        const r = rooms.get(m.room);
        if (!r || m.hostToken !== r.hostToken) return send(ws, { t: 'err', msg: 'bad-resume' });
        if (r.host && r.host !== ws) { try { r.host.close(); } catch (_) {} }
        r.host = ws;
        if (r.closeTimer) { clearTimeout(r.closeTimer); r.closeTimer = null; }
        ws.role = 'host';
        ws.room = m.room;
        // viewers 列表随消息带回：断线期间已建立的 PeerConnection 依然有效，无需重建
        send(ws, { t: 'host-ok', room: m.room, hostToken: r.hostToken, resumed: true, viewers: [...r.viewers.keys()], ice: ICE_SERVERS });
        break;
      }

      case 'view-join': {
        const r = rooms.get(m.room);
        if (!r || !r.host) return send(ws, { t: 'err', msg: 'no-room' });
        if (r.viewers.size >= MAX_VIEWERS) return send(ws, { t: 'err', msg: 'room-full' });
        const vid = rid().slice(0, 8);
        // 观众元数据：自取称呼 + 设备描述 + 设备 ID（同一手机点任何链接都认得出）
        ws.meta = {
          did: typeof m.did === 'string' ? m.did.slice(0, 32) : '',
          name: typeof m.name === 'string' ? m.name.trim().slice(0, 12) : '',
          desc: typeof m.desc === 'string' ? m.desc.slice(0, 20) : '',
        };
        r.viewers.set(vid, ws);
        ws.role = 'viewer';
        ws.room = m.room;
        ws.vid = vid;
        send(ws, { t: 'view-ok', vid, ice: ICE_SERVERS });
        send(r.host, { t: 'view-joined', vid, meta: ws.meta });
        break;
      }

      case 'signal': {
        const r = rooms.get(ws.room);
        if (!r) return;
        if (ws.role === 'host') {
          const v = r.viewers.get(m.to);
          if (v) send(v, { t: 'signal', from: 'host', data: m.data });
        } else if (ws.role === 'viewer') {
          send(r.host, { t: 'signal', from: ws.vid, data: m.data });
        }
        break;
      }

      case 'kick': {
        if (ws.role !== 'host') return;
        const r = rooms.get(ws.room);
        if (!r) return;
        const v = r.viewers.get(m.vid);
        if (v) {
          send(v, { t: 'bye', reason: 'kicked' });
          try { v.close(); } catch (_) {} // close 事件里统一清理并通知主播
        }
        break;
      }

      // ---------------- 管理后台（jacksun + 密码；hostSecret 供机器直登） ----------------
      case 'admin-login': {
        // 会话续登：断线重连凭 token 秒恢复，不过密码（续登即滚动延期）
        if (checkAdminSession(m.sessionToken)) {
          adminSessions.set(m.sessionToken, Date.now());
          ws.role = 'admin';
          send(ws, { t: 'admin-ok' });
          break;
        }
        // 机器/测试通道：hostSecret 直登（高熵密钥）
        if (m.secret === HOST_SECRET) {
          adminFails = 0; // 高熵密钥直登成功 → 不是暴力破解，清失败计数
          ws.role = 'admin';
          send(ws, { t: 'admin-ok', sessionToken: newAdminSession() });
          break;
        }
        if (Date.now() < adminLockUntil) return send(ws, { t: 'err', msg: 'admin-locked', retryAfter: Math.ceil((adminLockUntil - Date.now()) / 1000) });
        if (m.user !== ADMIN_USER || m.pass !== ADMIN_PASS) return adminFail(ws);
        adminFails = 0;
        ws.role = 'admin';
        send(ws, { t: 'admin-ok', sessionToken: newAdminSession() });
        break;
      }

      case 'admin-list': {
        if (ws.role !== 'admin') return send(ws, { t: 'err', msg: 'admin-expired' }); // 静默丢弃会让后台按钮「点了没反应」
        send(ws, { t: 'admin-guests', guests: listGuests() });
        break;
      }

      case 'admin-create': {
        if (ws.role !== 'admin') return send(ws, { t: 'err', msg: 'admin-expired' }); // 静默丢弃会让后台按钮「点了没反应」
        const name = typeof m.name === 'string' ? m.name.trim().slice(0, 24) : '';
        const code = genGuestCode();
        guests[code] = { name, createdAt: Date.now(), lastUsed: 0, disabled: false };
        saveGuests();
        send(ws, { t: 'admin-created', code });
        send(ws, { t: 'admin-guests', guests: listGuests() });
        break;
      }

      case 'admin-set': {
        if (ws.role !== 'admin') return send(ws, { t: 'err', msg: 'admin-expired' }); // 静默丢弃会让后台按钮「点了没反应」
        const g = guests[m.code];
        if (g) {
          g.disabled = !!m.disabled;
          saveGuests();
          if (g.disabled) destroyRoomsOf(m.code, 'code-disabled');
        }
        send(ws, { t: 'admin-guests', guests: listGuests() });
        break;
      }

      case 'admin-del': {
        if (ws.role !== 'admin') return send(ws, { t: 'err', msg: 'admin-expired' }); // 静默丢弃会让后台按钮「点了没反应」
        if (guests[m.code]) {
          delete guests[m.code];
          saveGuests();
          destroyRoomsOf(m.code, 'code-deleted');
        }
        send(ws, { t: 'admin-guests', guests: listGuests() });
        break;
      }

      case 'admin-rooms': {
        if (ws.role !== 'admin') return send(ws, { t: 'err', msg: 'admin-expired' }); // 静默丢弃会让后台按钮「点了没反应」
        const list = [...rooms.entries()].map(([room, r]) => ({
          room: room.slice(0, 6),
          owner: r.owner ? (r.owner.type === 'admin' ? '管理员' : (r.owner.name || r.owner.code)) : '?',
          viewers: r.viewers.size,
          startedAt: r.startedAt || 0,
        }));
        send(ws, { t: 'admin-rooms', rooms: list });
        break;
      }

      // ---------------- 通话中发文件（七牛直传） ----------------
      case 'file-token': {
        // 主播要传文件：发上传凭证（浏览器直传七牛，文件流不过服务器）
        if (ws.role !== 'host' || !QN) return send(ws, { t: 'err', msg: 'file-denied' });
        const size = +m.size || 0;
        if (size <= 0 || size > QN_MAX_SIZE) return send(ws, { t: 'err', msg: 'file-too-large' });
        const safeName = String(m.name || 'file').replace(/[/\\?%*:|"<>\x00-\x1f]/g, '_').slice(0, 150);
        const fileId = crypto.randomBytes(12).toString('hex');
        const key = `${QN_KEY_PREFIX}/${new Date().toISOString().slice(0, 10).replace(/-/g, '')}/${crypto.randomBytes(6).toString('hex')}/${safeName}`;
        pendingUploads.set(fileId, { key, name: safeName, size, ts: Date.now() });
        for (const [k, v] of pendingUploads) if (Date.now() - v.ts > 3600 * 1000) pendingUploads.delete(k);
        send(ws, { t: 'file-token', fileId, key, token: qiniuUploadToken(key), upHost: QN.upHost, maxSize: QN_MAX_SIZE });
        break;
      }

      case 'file-confirm': {
        // 直传完成：登记并推给直播间所有观众（fileId 由本服务签发，key 不信任客户端回传）
        if (ws.role !== 'host' || !QN) return;
        const rec = pendingUploads.get(m.fileId);
        if (!rec) return;
        pendingUploads.delete(m.fileId);
        fileRegistry[m.fileId] = { key: rec.key, name: rec.name, size: rec.size, ts: Date.now() };
        saveRegistry();
        const r2 = rooms.get(ws.room);
        let delivered = 0, noRoom = false;
        if (r2) {
          r2.viewers.forEach((v) => send(v, {
            t: 'chat', from: 'host', ts: Date.now(),
            text: '📎 发来文件：' + rec.name,
            file: { fileId: m.fileId, name: rec.name, size: rec.size },
          }));
          delivered = r2.viewers.size;
        } else {
          noRoom = true; // 直播已结束：文件仍登记可下载，但没人会收到通知
        }
        send(ws, { t: 'file-sent', fileId: m.fileId, delivered, noRoom }); // 主播要能知道到底送没送出去
        break;
      }

      case 'chat': {
        const r = rooms.get(ws.room);
        if (!r || typeof m.text !== 'string') return;
        const now = Date.now();
        if (ws.role === 'viewer' && now - (ws.lastChatTs || 0) < CHAT_INTERVAL_MS) return;
        ws.lastChatTs = now;
        const text = m.text.trim().slice(0, CHAT_MAX_LEN);
        if (!text) return;
        if (ws.role === 'viewer') {
          send(r.host, { t: 'chat', from: ws.vid, text, ts: now });
        } else if (ws.role === 'host') {
          if (m.to === 'all') {
            r.viewers.forEach((v) => send(v, { t: 'chat', from: 'host', text, ts: now }));
          } else if (m.to) {
            const v = r.viewers.get(m.to);
            if (v) send(v, { t: 'chat', from: 'host', text, ts: now });
          }
        }
        break;
      }

      case 'qos': {
        // 观众网络质量反馈 → 转给主播，供自动画质档位决策
        const r = rooms.get(ws.room);
        if (!r) return;
        if (ws.role === 'viewer' && r.host) {
          send(r.host, {
            t: 'qos', from: ws.vid,
            fps: +m.fps || 0, kbps: +m.kbps || 0, loss: +m.loss || 0, rtt: +m.rtt || 0,
          });
        }
        break;
      }

      case 'bye': {
        if (ws.role === 'host') {
          destroyRoom(ws.room, 'host-hangup');
        } else if (ws.role === 'viewer') {
          const r = rooms.get(ws.room);
          if (r) {
            r.viewers.delete(ws.vid);
            send(r.host, { t: 'view-left', vid: ws.vid });
          }
        }
        ws.role = null;
        break;
      }
    }
  });

  ws.on('close', (codeNum, reason) => {
    // 断连规律诊断：code 1001=页面关闭/导航，1006=异常断开（网络/超时类）
    console.log('[conn] close', new Date().toISOString(), 'code=' + codeNum, 'role=' + (ws.role || '-'), (reason || '').toString().slice(0, 40));
    if (ws.role === 'host') {
      const r = rooms.get(ws.room);
      if (!r || r.host !== ws) return;
      r.host = null;
      r.viewers.forEach((v) => send(v, { t: 'host-offline' }));
      r.closeTimer = setTimeout(() => {
        const cur = rooms.get(ws.room);
        if (cur === r && !r.host) destroyRoom(ws.room, 'host-timeout');
      }, HOST_GRACE_MS);
    } else if (ws.role === 'viewer') {
      const r = rooms.get(ws.room);
      if (!r) return;
      r.viewers.delete(ws.vid);
      send(r.host, { t: 'view-left', vid: ws.vid });
    }
  });
});

// 心跳：清死连接
setInterval(() => {
  wss.clients.forEach((c) => {
    if (!c.isAlive) return c.terminate();
    c.isAlive = false;
    c.ping();
  });
}, 15000);

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[screen-share-live] signaling ready on http://127.0.0.1:${PORT}`);
});
