#!/usr/bin/env node
// 后台与访客码链路自测（不走浏览器，直连 WS）：
//   node test/guest_test.js [ws://127.0.0.1:8018/ws] [hostSecret]
// 线上：node test/guest_test.js wss://zhibo.jack-sun.com/ws "$(ssh jacksun-tencent 'node -e ...')"
'use strict';
const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'ws://127.0.0.1:8018/ws';
let SECRET = process.argv[3];
if (!SECRET) {
  SECRET = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config.json'), 'utf8')).hostSecret;
}

let pass = 0, fail = 0;
const ok = (name, cond) => { console.log((cond ? '  [ok]   ' : '  [FAIL] ') + name); cond ? pass++ : fail++; };
const conn = () => new WebSocket(BASE);
function once(ws, type, timeout = 6000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout: ' + type)), timeout);
    ws.on('message', function h(raw) {
      let m;
      try { m = JSON.parse(raw); } catch (_) { return; }
      if (m.t === type) { clearTimeout(timer); ws.off('message', h); resolve(m); }
    });
  });
}

(async () => {
  // 1. 管理后台登录（验证码环节需人工识别,自动化走 hostSecret 直登通道;错误凭证走拒绝路径）
  const a = conn();
  await new Promise((r) => a.on('open', r));
  a.send(JSON.stringify({ t: 'admin-login', secret: 'WRONG-KEY' }));
  ok('错密钥被拒', (await once(a, 'err')).msg === 'bad-admin-credential');
  a.send(JSON.stringify({ t: 'admin-login', user: 'jacksun', pass: 'wrong', captchaId: 'x', captchaCode: '0000' }));
  ok('错误账号密码被拒', (await once(a, 'err')).msg === 'bad-admin-credential');
  a.send(JSON.stringify({ t: 'admin-login', secret: SECRET }));
  ok('admin 密钥直登', (await once(a, 'admin-ok')).t === 'admin-ok');

  // 2. 生成访客码
  a.send(JSON.stringify({ t: 'admin-create', name: 'e2e访客' }));
  const created = await once(a, 'admin-created');
  ok('生成访客码 ' + created.code, /^[A-Z2-9]{8}$/.test(created.code));

  // 3. 访客码开播
  const g = conn();
  await new Promise((r) => g.on('open', r));
  g.send(JSON.stringify({ t: 'host-create', secret: created.code }));
  const gok = await once(g, 'host-ok');
  ok('访客码开播成功', !!gok.room);

  // 4. 观众进入访客房间
  const v = conn();
  await new Promise((r) => v.on('open', r));
  v.send(JSON.stringify({ t: 'view-join', room: gok.room }));
  ok('观众进入访客房间', (await once(v, 'view-ok')).t === 'view-ok');

  // 5. 假码被拒
  const bad = conn();
  await new Promise((r) => bad.on('open', r));
  bad.send(JSON.stringify({ t: 'host-create', secret: 'ZZZZ9999' }));
  ok('假访客码被拒', (await once(bad, 'err')).msg === 'bad-secret');

  // 5.5 文件链路（趁房间还活着）：file-token → file-confirm → 观众收到 → /dl 302
  g.send(JSON.stringify({ t: 'file-token', name: '测试 资料.txt', size: 12345 }));
  const ftok = await once(g, 'file-token');
  ok('上传凭证签发（key/token/upHost）',
    ftok.key.startsWith('zhibo/') && /^[^:]+:[^:]+:[^:]+$/.test(ftok.token) && !!ftok.upHost && /^[0-9a-f]{24}$/.test(ftok.fileId));
  const chatP = once(v, 'chat'); // 先订阅再触发,防推送早于监听
  const sentP = once(g, 'file-sent');
  g.send(JSON.stringify({ t: 'file-confirm', fileId: ftok.fileId }));
  const chatMsg = await chatP;
  ok('观众收到文件消息', !!chatMsg.file && chatMsg.file.fileId === ftok.fileId && chatMsg.file.name === '测试 资料.txt');
  const sent = await sentP;
  ok('主播收到送达回执', sent.delivered === 1);
  // 下载断言跟随 BASE(本机 http / 线上 https)
  const httpMod = require(BASE.startsWith('wss') ? 'https' : 'http');
  const dlBase = BASE.replace(/^ws/, 'http').replace(/\/ws$/, '');
  const dl = await new Promise((resolve) => {
    httpMod.get(dlBase + '/dl/' + ftok.fileId, (res) => resolve(res)).on('error', () => resolve(null));
  });
  const loc = (dl && dl.headers.location) || '';
  const locOk = !!dl && dl.statusCode === 302 &&
    (BASE.startsWith('wss') ? loc.includes('zhibo.qiniu.cdn.jack-sun.com') : loc.includes('localtest.example.com'));
  ok('下载 302 跳转七牛（CDN 直链）', locOk);
  const dl404 = await new Promise((resolve) => {
    httpMod.get(dlBase + '/dl/deadbeefdeadbeefdeadbeef', (res) => resolve(res)).on('error', () => resolve(null));
  });
  ok('不存在的文件 404', !!dl404 && dl404.statusCode === 404);

  // 6. 后台看到房间
  a.send(JSON.stringify({ t: 'admin-rooms' }));
  const rl = await once(a, 'admin-rooms');
  ok('后台看到访客房间（归属备注正确）', rl.rooms.some((r) => r.owner === 'e2e访客' && r.viewers === 1));

  // 7. 禁用即刻销毁（先订阅 bye 再触发禁用，防消息早于监听到达）
  const byeP = once(g, 'bye', 5000).catch(() => null);
  a.send(JSON.stringify({ t: 'admin-set', code: created.code, disabled: true }));
  await once(a, 'admin-guests');
  const bye = await byeP;
  ok('禁用密码立刻结束访客直播', !!bye && bye.reason === 'code-disabled');

  // 8. 被禁用的码不能再开播
  g.send(JSON.stringify({ t: 'host-create', secret: created.code }));
  ok('被禁用的码不能再开播', (await once(g, 'err')).msg === 'bad-secret');

  // 9. 清理测试码
  a.send(JSON.stringify({ t: 'admin-del', code: created.code }));
  await once(a, 'admin-guests');
  ok('删除测试码', true);

  [a, g, v, bad].forEach((w) => { try { w.close(); } catch (_) {} });
  console.log(fail ? `\nFAIL：${fail} 项未过` : '\nPASS：后台与访客码全链路通了');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
