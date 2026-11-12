// 观众互通测试：1 主播 + 2 观众（headless Edge/Chrome fake 设备）
// 判定：只有观众 A 时，A 收到的「观众专线」无能量；B 加入后，A 和 B 的专线都有能量（互相能听到）
// 用法：node test/party_test.js                              （本机，自动起 server，端口 8019）
//      node test/party_test.js https://zhibo.jack-sun.com   （线上，secret 自动 ssh 取）
const { spawn, execSync } = require('child_process');
const http = require('http');
const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');
const BASE = path.join(__dirname, '..');
const CHROME = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'].find(fs.existsSync);
const REMOTE = process.argv[2] || '';
const ORIGIN = REMOTE || 'http://127.0.0.1:8019';
const HOSTFRAG = ORIGIN.split('//')[1];
const secret = REMOTE
  ? execSync(`ssh -o BatchMode=yes jacksun-tencent "node -e 'console.log(require(\\"/home/ubuntu/screen-share-live/config.json\\").hostSecret)'"`).toString().trim()
  : JSON.parse(fs.readFileSync(path.join(BASE, 'config.json'))).hostSecret;
const FLAGS = ['--headless=new', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required', '--no-first-run', '--no-default-browser-check', '--disable-sync'];
const procs = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function launch(port, name, url) {
  procs.push(spawn(CHROME, [...FLAGS, `--remote-debugging-port=${port}`, `--user-data-dir=/tmp/ssl-e2e-party-${name}`, url], { stdio: 'ignore' }));
}
function getJSON(port) {
  return new Promise((res, rej) => http.get(`http://127.0.0.1:${port}/json`, (r) => { let d = ''; r.on('data', (c) => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } }); }).on('error', rej));
}
async function page(port) {
  for (let i = 0; i < 40; i++) {
    try { const p = (await getJSON(port)).find((t) => t.type === 'page' && t.url.includes(HOSTFRAG)); if (p) return p; } catch (_) {}
    await sleep(500);
  }
  throw new Error('page not found ' + port);
}
async function evalIn(port, expr) {
  const p = await page(port);
  const ws = new WebSocket(p.webSocketDebuggerUrl);
  await new Promise((r) => ws.on('open', r));
  return new Promise((res, rej) => {
    ws.on('message', (m) => { const j = JSON.parse(m); if (j.id === 1) { ws.close(); j.result.exceptionDetails ? rej(new Error(JSON.stringify(j.result.exceptionDetails))) : res(j.result.result.value); } });
    ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: expr, awaitPromise: true, returnByValue: true } }));
  });
}
// 观众端所有入站音频的 {id, energy}：最后一条 m-line 是观众专线
const STATS = `(async()=>{const out=[];for(const tr of pc.getTransceivers()){if(tr.receiver.track.kind!=='audio')continue;const st=await tr.receiver.getStats();let e=0;st.forEach(r=>{if(r.type==='inbound-rtp')e=r.totalAudioEnergy||0});out.push({mid:tr.mid,e})}return out})()`;
let fail = 0;
function check(ok, msg) { console.log((ok ? '  [ok] ' : '  [FAIL] ') + msg); if (!ok) fail++; }
(async () => {
  try {
    execSync('pkill -f ssl-e2e-party || true');
    if (!REMOTE) {
      procs.push(spawn('node', [path.join(BASE, 'server.js')], { stdio: 'ignore', env: { ...process.env, SSL_PORT: '8019' } }));
      await sleep(1500);
    }
    launch(9322, 'host', `${ORIGIN}/host.html?fake=1&autostart=1&secret=${secret}`);
    let room;
    for (let i = 0; i < 40 && !room; i++) { await sleep(500); try { const t = (await page(9322)).title; if (t.includes('H:ok:r')) room = t.split('r').pop().trim(); } catch (_) {} }
    check(!!room, '主播开播 room=' + room);
    launch(9323, 'va', `${ORIGIN}/viewer.html?fake=1&autostart=1&r=${room}`);
    for (let i = 0; i < 40; i++) { await sleep(500); if ((await page(9323)).title === 'V:playing') break; }
    await sleep(4000);
    const a1 = await evalIn(9323, STATS);
    console.log('  A 单独在线 :', JSON.stringify(a1));
    const partyA1 = a1[a1.length - 1];
    check(a1.length >= 2, 'A 收到 ≥2 条音频 m-line（主播麦克风 + 观众专线），实际 ' + a1.length);
    check(partyA1.e < 0.0001, 'A 单独在线时观众专线无声（没有别人）');
    await evalIn(9323, `(()=>{window.__toasts=[];const o=showToast;showToast=(t)=>{__toasts.push(t);o(t)};return 1})()`);
    launch(9324, 'vb', `${ORIGIN}/viewer.html?fake=1&autostart=1&r=${room}`);
    for (let i = 0; i < 40; i++) { await sleep(500); try { if ((await page(9324)).title === 'V:playing') break; } catch (_) {} }
    await sleep(6000);
    const a2 = await evalIn(9323, STATS), b2 = await evalIn(9324, STATS);
    console.log('  A (B 加入后):', JSON.stringify(a2));
    console.log('  B          :', JSON.stringify(b2));
    check(a2[a2.length - 1].e > 0.001, 'A 能听到 B（专线有能量）');
    check(b2[b2.length - 1].e > 0.001, 'B 能听到 A（专线有能量）');
    // 主播关互通 → 专线能量不再增长
    await evalIn(9322, `setPartyOn(false)`);
    await sleep(1500);
    const c1 = await evalIn(9323, STATS); await sleep(3000); const c2 = await evalIn(9323, STATS);
    check(c2[c2.length - 1].e - c1[c1.length - 1].e < 0.0005, '主播关闭互通后 A 听不到 B');
    await evalIn(9322, `setPartyOn(true)`);
    await sleep(2500);
    const d1 = await evalIn(9323, STATS); await sleep(3000); const d2 = await evalIn(9323, STATS);
    check(d2[d2.length - 1].e - d1[d1.length - 1].e > 0.001, '重新开启后 A 又能听到 B');
    // 「谁在说话」提示：A 端应出现 B 的称呼（fake 设备是间歇 beep，轮询 10 秒）
    let talk = '';
    for (let i = 0; i < 20 && !talk; i++) { await sleep(500); talk = await evalIn(9323, `$('talkers').classList.contains('show') ? $('talkers').textContent : ''`); }
    check(/正在说话/.test(talk), 'A 端显示说话提示：' + JSON.stringify(talk));
    // 推子拉到 0 → 静音；拉回 150% → 有声
    await evalIn(9322, `(()=>{const r=$('partyVol');r.value=0;r.oninput({target:r})})()`);
    await sleep(1500);
    const v1 = await evalIn(9323, STATS); await sleep(3000); const v2 = await evalIn(9323, STATS);
    check(v2[v2.length - 1].e - v1[v1.length - 1].e < 0.0005, '互通音量推到 0% 后 A 听不到 B');
    await evalIn(9322, `(()=>{const r=$('partyVol');r.value=150;r.oninput({target:r})})()`);
    await sleep(2000);
    const w1 = await evalIn(9323, STATS); await sleep(3000); const w2 = await evalIn(9323, STATS);
    check(w2[w2.length - 1].e - w1[w1.length - 1].e > 0.001, '推回 150% 后 A 又能听到 B');
    // ---- 其他新功能 ----
    const toastsA = await evalIn(9323, `__toasts.join(' | ')`);
    check(/进来了/.test(toastsA), 'B 进来时 A 收到进场提示：' + toastsA);
    const labels = await evalIn(9322, `[...peers.keys()].map(vidLabel).join(',')`);
    check(/2号/.test(labels), '同款设备没填称呼自动编号：' + labels);
    await evalIn(9323, `ws.send(JSON.stringify({t:'chat',text:'hello-from-A'}))`);
    await sleep(1200);
    const chatB = await evalIn(9324, `JSON.stringify(chatHistory.slice(-1))`);
    check(/hello-from-A/.test(chatB), '观众之间文字群聊：B 收到 A 的消息 ' + chatB);
    await evalIn(9322, `muteAll(true)`);
    await sleep(1000);
    const mA = await evalIn(9323, `mutedByHost + '/' + (micTrack ? micTrack.enabled : 'none')`);
    check(mA === 'true/false', '全员静音：A 的麦被锁 ' + mA);
    await evalIn(9322, `muteAll(false)`);
    await sleep(1000);
    const mA2 = await evalIn(9323, `mutedByHost + '/' + (micTrack ? micTrack.enabled : 'none')`);
    check(mA2 === 'false/true', '全员解除：A 的麦恢复 ' + mA2);
    const sw = await evalIn(9322, `(async()=>{const old=screenTrack.id;await switchScreen();const ok=[...peers.values()].every(pc=>pc.getSenders().some(x=>x.track===screenTrack));return (screenTrack.id!==old)+'/'+ok+'/'+peers.size})()`);
    check(sw === 'true/true/2', '换屏幕：新轨替换到所有观众、无人掉线 ' + sw);
    const f1 = await evalIn(9324, `video.webkitDecodedFrameCount`); await sleep(2500); const f2 = await evalIn(9324, `video.webkitDecodedFrameCount`);
    check(f2 - f1 > 10, '换屏幕后观众画面继续在走（2.5 秒解码 ' + (f2 - f1) + ' 帧）');
    const qr = await evalIn(9322, `(()=>{$('qrBtn').click();const ok=!!$('qrBox').querySelector('svg')&&$('qrPop').classList.contains('show');$('qrClose').click();return ok})()`);
    check(qr === true, '二维码弹层生成 SVG');
    const zm = await evalIn(9323, `(()=>{zoomAt(200,150,2.5);const a=video.style.transform;const b=$('zoomBadge').classList.contains('show');resetZoom();return a+'|'+b+'|'+video.style.transform})()`);
    check(/scale\(2\.5\)\|true\|$/.test(zm), '观众端放大/还原：' + zm);
    // 移出 B：B 看到休息文案 + 倒计时；A 的专线随之静音
    await evalIn(9322, `(()=>{const ids=[...peers.keys()];ws.send(JSON.stringify({t:'kick',vid:ids[ids.length-1]}));})()`);
    await sleep(2500);
    const kb = await evalIn(9324, `document.title + '|' + ($('kickCount')||{}).textContent + '|' + document.querySelector('.kick-card h2').textContent`);
    console.log('  B 被移出后:', kb);
    check(/^V:kicked\|\d+\|.+/.test(kb), 'B 显示休息文案与倒计时');
    // B 刷新页面想立刻回来：服务器应拒绝（休息期内），B 仍显示倒计时
    await evalIn(9324, `location.reload()`);
    await sleep(1500);
    await evalIn(9324, `(()=>{const b=document.getElementById('joinBtn'); if (b) b.click(); return 1})()`);
    await sleep(3000);
    const kb2 = await evalIn(9324, `document.title + '|' + (($('kickCount')||{}).textContent||'')`);
    console.log('  B 刷新重进:', kb2);
    check(/\|\d+$/.test(kb2), '休息期内刷新重进被拦下，继续倒计时');
    const hv = await evalIn(9322, `peers.size + '/' + party.size`);
    const toastsA2 = await evalIn(9323, `__toasts.join(' | ')`);
    check(/先走了/.test(toastsA2), 'B 离开时 A 收到提示');
    check(hv === '1/1', '主播端清理干净（peers/party 都剩 1）：' + hv);
  } catch (e) { console.log('  [ERR]', e.message); fail++; }
  procs.forEach((p) => { try { p.kill(); } catch (_) {} });
  try { execSync('pkill -f ssl-e2e-party || true'); } catch (_) {}
  console.log(fail ? '\nFAIL' : '\nPASS：观众互通全链路通过'); process.exit(fail ? 1 : 0);
})();
