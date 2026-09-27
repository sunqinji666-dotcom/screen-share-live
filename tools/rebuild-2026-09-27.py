#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-09-27 界面改版组装脚本
- host.html：全新工作台壳（同屏设计语言）+ 原脚本逻辑零转录提取 + 16 处精准补丁 + 新功能模块
- viewer.html：保留沉浸式观看逻辑，重做加入页视觉 + 表情回应 + 修 joinBtn 空指针
- index.html / manifest.json 由 Write 直接生成，不在本脚本内
用法：python3 tools/rebuild-2026-09-27.py
"""
import pathlib, sys, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / 'web'
# 幂等：每次从 git 初始备份（b01a8de）恢复原始页面再打补丁，脚本可任意重跑
ORIG_HOST = subprocess.run(['git', '-C', str(ROOT), 'show', 'b01a8de:web/host.html'],
                           capture_output=True, text=True, check=True).stdout
ORIG_VIEWER = subprocess.run(['git', '-C', str(ROOT), 'show', 'b01a8de:web/viewer.html'],
                             capture_output=True, text=True, check=True).stdout
FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%231c3f32'/%3E%3Ctext x='32' y='44' font-size='32' font-weight='700' text-anchor='middle' fill='%23e9f1e9' font-family='PingFang SC'%3E%E5%90%8C%3C/text%3E%3C/svg%3E"

def patch(src: str, pairs, label: str) -> str:
    """按顺序做唯一匹配替换；任何一处匹配失败或命中多次都直接报错，防止静默错位。
    pairs 元素可为 (old, new) 或 (old, new, expect_n)。"""
    for item in pairs:
        old, new = item[0], item[1]
        expect = item[2] if len(item) > 2 else 1
        n = src.count(old)
        if n != expect:
            sys.exit(f"[{label}] 补丁匹配异常（{n} 处，期望 {expect}）: {old[:80]!r}")
        src = src.replace(old, new)
    return src

# ---------------------------------------------------------------- host
host = ORIG_HOST

# 提取原 <script> 逻辑（文件中只有一段 script）
i0 = host.index('<script>')
i1 = host.index('</script>')
script = host[i0 + len('<script>'):i1]

script = patch(script, [
    # P1 混音台声明加 recDest（录制取混音用）
    ("let mixCtx = null, micGainNode = null, sysGainNode = null; // 混音台：两条音轨各一道增益",
     "let mixCtx = null, micGainNode = null, sysGainNode = null, recDest = null; // 混音台：两条音轨各一道增益；recDest 供本地录制取混音"),
    # P1b liveSince 声明提前（autostart 会同步调用 start()，声明必须在其词法之前）
    ("""let ws = null;
let wsRetry = 0;""",
     """let liveSince = null; // 顶部状态栏计时起点（P19 设、P20 清）
let ws = null;
let wsRetry = 0;"""),
    # P2 start() 里麦克风初始状态 → label
    ("""    micMuted = false;
    $('micBtn').textContent = '闭麦';
    $('micBtn').classList.remove('muted');""",
     """    micMuted = false;
    $('micBtnLabel').textContent = '闭麦';
    $('micBtn').classList.remove('muted');
    $('micBtn').setAttribute('aria-pressed', 'true');"""),
    # P3 混音台接录制支路
    ("""          sysSendTrack = sysDst.stream.getAudioTracks()[0];
        }""",
     """          sysSendTrack = sysDst.stream.getAudioTracks()[0];
        }
        recDest = mixCtx.createMediaStreamDestination(); // 录制裁：混音后的麦克声+系统声
        micGainNode.connect(recDest);
        if (sysGainNode) sysGainNode.connect(recDest);"""),
    # P4 setBadge 同步舞台状态条
    ("""function setBadge(text, on) {
  badge.textContent = text;
  badge.className = 'badge' + (on ? ' on' : '');
}""",
     """function setBadge(text, on) {
  if (badge) {
    badge.textContent = text;
    badge.className = 'badge' + (on ? ' on' : '');
  }
  const stageStatusEl = document.getElementById('stageStatus');
  const stageDotEl = document.getElementById('stageDot');
  if (stageStatusEl && (on || text === '未开播')) stageStatusEl.textContent = on ? '直播中 · 画面与声音实时送达观众' : '未开播 · 画面与声音仅本机可见';
  if (stageDotEl) stageDotEl.className = 'status-dot' + (on ? '' : ' off');
  const stripStateEl = document.getElementById('stripState');
  if (stripStateEl && (on || text === '未开播')) stripStateEl.textContent = on ? '直播中' : '未开播';
  const stripDotEl = document.getElementById('stripDot');
  if (stripDotEl) stripDotEl.className = 'status-dot' + (on ? '' : ' off');
}"""),
    # P5a stop() 先收录制
    ("""function stop() {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: 'bye' }));""",
     """function stop() {
  if (recorder) stopRec();
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: 'bye' }));"""),
    # P5b stop() 清 recDest
    ("  mixCtx = micGainNode = sysGainNode = null;",
     "  mixCtx = micGainNode = sysGainNode = recDest = null;"),
    # P5c stop() 恢复待命卡（结束即可再开一场）
    ("""  if (ws) { try { ws.close(); } catch (_) {} ws = null; }
  room = null;
  hostToken = null;
}""",
     """  if (ws) { try { ws.close(); } catch (_) {} ws = null; }
  room = null;
  hostToken = null;
  $('secretCard').classList.add('show'); // 回到待命卡，可直接再开一场
}"""),
    # P6 摄像头开 → label
    ("""    camOn = true;
    $('camBtn').textContent = '📷 关摄像头';
    $('camBtn').classList.add('active');""",
     """    camOn = true;
    $('camBtnLabel').textContent = '已开启';
    $('camBtn').classList.add('active');"""),
    # P7 摄像头关 → label
    ("""  camStream = camTrack = null;
  $('camBtn').textContent = '📷 摄像头';
  $('camBtn').classList.remove('active');""",
     """  camStream = camTrack = null;
  $('camBtnLabel').textContent = '摄像头';
  $('camBtn').classList.remove('active');"""),
    # P8 喇叭按钮 → title（图标按钮不再放长文本）
    ("  $('spkBtn').textContent = speakerMuted ? '开启喇叭' : '静音对方';",
     "  $('spkBtn').title = speakerMuted ? '开启观众声音' : '静音观众声音';"),
    # P9 复制按钮 → label
    ("""    $('copyBtn').textContent = '已复制';
    setTimeout(() => { $('copyBtn').textContent = '复制观众链接'; }, 1500);""",
     """    $('copyBtnLabel').textContent = '已复制';
    setTimeout(() => { $('copyBtnLabel').textContent = '复制观众链接'; }, 1500);"""),
    # P10 麦克风切换 → label
    ("""  $('micBtn').textContent = micMuted ? '开麦' : '闭麦';
  $('micBtn').classList.toggle('muted', micMuted);""",
     """  $('micBtnLabel').textContent = micMuted ? '已静音' : '麦克风';
  $('micBtn').setAttribute('aria-pressed', String(!micMuted));
  $('micBtn').classList.toggle('muted', micMuted);"""),
    # P11 聊天计数
    ("""  list.appendChild(d);
  list.scrollTop = list.scrollHeight;
}
function sendChat() {""",
     """  list.appendChild(d);
  list.scrollTop = list.scrollHeight;
  const chatCountEl = document.getElementById('chatCount');
  if (chatCountEl) chatCountEl.textContent = list.children.length;
}
function sendChat() {"""),
    # P12 成员计数 + 空态互斥（"暂无观众"不得与成员行并存——原版存量 bug）
    ("""function updateViewerList() {
  // 无观众时立即归零；有观众时的行内容与 title 由统计定时器刷新""",
     """function updateViewerList() {
  const peopleCountEl = document.getElementById('peopleCount');
  if (peopleCountEl) peopleCountEl.textContent = peers.size;
  const viewerEmptyEl = document.getElementById('viewerEmpty');
  if (viewerEmptyEl) viewerEmptyEl.style.display = peers.size ? 'none' : 'block';
  // 无观众时立即归零；有观众时的行内容与 title 由统计定时器刷新"""),
    # P13 表情回应信令
    ("""async function onSignal(from, data) {
  const pc = peers.get(from);
  if (data.control === 'mic-state') {""",
     """async function onSignal(from, data) {
  const pc = peers.get(from);
  if (data.control === 'react') {
    const emo = String(data.emoji || '').slice(0, 8);
    if (emo) {
      addChat(vidLabel(from), emo);
      showToast(vidLabel(from) + ' ' + emo);
    }
    return;
  }
  if (data.control === 'mic-state') {"""),
    # P14 文件面板登记
    ("  addFileMsg(msgId, f.name, f.size, '准备上传…', '');",
     "  addFileMsg(msgId, f.name, f.size, '准备上传…', '');\n  trackFile(msgId, f.name, f.size);"),
    # P23 无观众时也显示采集帧率（原版直接 return，主播开播后顶部/统计条全空）
    ("""setInterval(async () => {
  if (!peers.size) { $('stats').textContent = ''; lastStatsTs = 0; return; }""",
     """setInterval(async () => {
  if (!peers.size) {
    // 无观众：没有推流统计，但屏幕采集在进行——显示采集帧率，主播开播即有数
    if (screenTrack) {
      const capFps0 = screenTrack.getSettings().frameRate;
      const fpsTxt = capFps0 ? String(Math.round(capFps0)) : '-';
      setStat('stFps', fpsTxt);
      setStat('stCap', fpsTxt);
      setStat('stRes', '—');
      setStat('stRate', '—');
      setStat('stRtt', '—');
      const viaEl0 = document.getElementById('stVia');
      if (viaEl0) { viaEl0.textContent = '—'; viaEl0.className = ''; }
    }
    $('stats').textContent = '';
    lastStatsTs = 0;
    return;
  }"""),
    ("""function setStat(id, val) {
  const el = document.getElementById(id);
  if (!el || el.textContent === String(val)) return;
  el.textContent = String(val);
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 650);
}""",
     """const STAT_MIRROR = { stFps: 'stripFps', stRate: 'stripRate', stRtt: 'stripRtt' };
function setStat(id, val) {
  const el = document.getElementById(id);
  if (el && el.textContent !== String(val)) {
    el.textContent = String(val);
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 650);
  }
  const mirrorEl = document.getElementById(STAT_MIRROR[id] || '');
  if (mirrorEl && mirrorEl.textContent !== String(val)) mirrorEl.textContent = String(val);
}"""),
    # P22 stVia 镜像（线路色同步）
    ("""    const viaEl = document.getElementById('stVia');
    if (viaEl) {
      viaEl.textContent = viaTxt;
      viaEl.className = viaTxt.includes('中继') ? 'warn' : viaTxt.includes('直连') ? 'good' : '';
    }""",
     """    const viaEl = document.getElementById('stVia');
    if (viaEl) {
      viaEl.textContent = viaTxt;
      viaEl.className = viaTxt.includes('中继') ? 'warn' : viaTxt.includes('直连') ? 'good' : '';
    }
    const stripViaEl = document.getElementById('stripVia');
    if (stripViaEl) {
      stripViaEl.textContent = viaTxt;
      stripViaEl.className = viaTxt.includes('中继') ? 'warn' : viaTxt.includes('直连') ? 'good' : '';
    }"""),
    # P19 开播成功 → 舞台标签切"直播中"（锚定真实采集流，不随瞬时提示漂移；
    # sourceTag 不挂 setBadge——摄像头等瞬时提示会把"直播中"打回"待开播"）
    ("""    $('preview').srcObject = screenStream;
    $('preview').style.display = 'block';
    $('liveStats').style.display = 'block';""",
     """    $('preview').srcObject = screenStream;
    $('preview').style.display = 'block';
    $('liveStats').style.display = 'block';
    liveSince = Date.now(); // 顶部状态栏计时起点"""),
    # P20 结束 → 舞台标签复位 + 观众列表重置为空态（新版 stop 后可再开一场）+ 计时清零
    ("""  $('liveStats').style.display = 'none';
  myMeterBuf = null;""",
     """  $('liveStats').style.display = 'none';
  $('viewerList').innerHTML = '<p id="viewerEmpty">暂无观众</p>';
  liveSince = null;
  myMeterBuf = null;"""),
    # P16 观众行状态中文化（connectionState 英文 → 中文）
    ("      vs.textContent = `${pc.connectionState} · ${voice}`;",
     """      const stateZh = { connected: '已接通', checking: '接通中', disconnected: '波动中', failed: '已断开', new: '连接中', closed: '已关闭' }[pc.connectionState] || pc.connectionState;
      vs.textContent = `${stateZh} · ${voice}`;"""),
    # P17 观众行静音按钮 emoji → Lucide
    ("    muteB.textContent = '🔇';",
     "    muteB.innerHTML = '<i data-lucide=\"mic-off\"></i>';"),
    # P18 动态行插入后刷新图标
    ("""    ops.appendChild(muteB);
    ops.appendChild(kickB);""",
     """    ops.appendChild(muteB);
    ops.appendChild(kickB);
    if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });"""),
    # P15 文件状态同步到面板
    ("""    if (isErr || statusText.includes('✓')) bar.style.display = 'none';
  }
}""",
     """    if (isErr || statusText.includes('✓')) bar.style.display = 'none';
  }
  trackFileStatus(id, statusText, isErr);
}"""),
], 'host-script')

EXTRA = """
// ==================== 2026-09-27 新增：toast / 面板 / 截图 / 录制 / 文件面板 / 快捷键 ====================
setInterval(() => {
  const c = document.getElementById('stripClock');
  if (!c) return;
  if (!liveSince) { if (c.textContent !== '00:00') c.textContent = '00:00'; return; }
  const s = Math.floor((Date.now() - liveSince) / 1000);
  const t = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  if (c.textContent !== t) c.textContent = t;
}, 1000);
let toastTimer2 = null;
function showToast(text) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer2);
  toastTimer2 = setTimeout(() => el.classList.remove('show'), 2600);
}
function switchPanel(name) {
  ['chat', 'people', 'files'].forEach((t) => {
    const tab = document.getElementById('tab-' + t);
    const panel = document.getElementById('panel-' + t);
    if (!tab || !panel) return;
    const on = t === name;
    tab.setAttribute('aria-selected', String(on));
    panel.hidden = !on;
  });
}
document.querySelectorAll('.panel-tab').forEach((tab) => {
  tab.addEventListener('click', () => switchPanel(tab.dataset.panel));
});
const volBtnEl = document.getElementById('volBtn');
if (volBtnEl) volBtnEl.onclick = () => switchPanel('people');
const stageFullBtnEl = document.getElementById('stageFullBtn');
if (stageFullBtnEl) stageFullBtnEl.onclick = () => {
  const v = document.getElementById('preview');
  try {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (v.requestFullscreen) v.requestFullscreen();
  } catch (_) {}
};

// 截图：当前共享画面进剪贴板（受限环境自动转为下载）
async function takeShot() {
  const v = document.getElementById('preview');
  if (!v || !v.videoWidth) { showToast('还没有可截取的画面'); return; }
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  c.toBlob(async (b) => {
    if (!b) { showToast('截图失败'); return; }
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': b })]);
      showToast('截图已复制到剪贴板');
    } catch (_) {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = '同屏截图-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '') + '.png';
      a.click();
      showToast('截图已保存到下载');
    }
  }, 'image/png');
}
const shotBtnEl = document.getElementById('shotBtn');
if (shotBtnEl) shotBtnEl.onclick = takeShot;

// 录制：共享画面 + 混音后的人声/系统声，本地完整成片
let recorder = null, recChunks = [], recSeconds = 0, recTicker = null, recFileExt = 'webm', recMime = 'video/webm';
function pickRecMime() {
  const list = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=h264,opus', 'video/webm', 'video/mp4'];
  for (const m of list) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch (_) {}
  }
  return '';
}
function toggleRec() {
  if (recorder) { stopRec(); return; }
  if (!screenTrack) { showToast('先开始共享，再录制'); return; }
  const mime = pickRecMime();
  const tracks = [screenTrack];
  if (recDest) recDest.stream.getAudioTracks().forEach((t) => tracks.push(t));
  else if (micSendTrack) tracks.push(micSendTrack);
  const stream = new MediaStream(tracks);
  try {
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  } catch (err) {
    showToast('当前浏览器不支持录制');
    recorder = null;
    return;
  }
  recMime = recorder.mimeType || 'video/webm';
  recFileExt = recMime.includes('mp4') ? 'mp4' : 'webm';
  recChunks = [];
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) recChunks.push(e.data); };
  recorder.onstop = () => {
    const blob = new Blob(recChunks, { type: recMime });
    recChunks = [];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '同屏录制-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.' + recFileExt;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  };
  recorder.start(2000);
  recSeconds = 0;
  document.getElementById('recBtn').classList.add('rec-active');
  recTicker = setInterval(() => {
    recSeconds++;
    const mm = String(Math.floor(recSeconds / 60)).padStart(2, '0');
    const ss = String(recSeconds % 60).padStart(2, '0');
    document.getElementById('recLabel').textContent = mm + ':' + ss;
  }, 1000);
  showToast('开始录制（保存在本机）');
}
function stopRec() {
  if (!recorder) return;
  try { recorder.stop(); } catch (_) {}
  recorder = null;
  clearInterval(recTicker);
  document.getElementById('recBtn').classList.remove('rec-active');
  document.getElementById('recLabel').textContent = '录制';
  showToast('录制已保存到下载');
}
const recBtnEl = document.getElementById('recBtn');
if (recBtnEl) recBtnEl.onclick = toggleRec;

// 文件面板：本场发送过的文件与状态
const sentFiles = [];
const escHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
function trackFile(msgId, name, size) {
  sentFiles.push({ msgId, name, size, st: '准备上传' });
  renderSentFiles();
}
function trackFileStatus(msgId, statusText, isErr) {
  const f = sentFiles.find((x) => x.msgId === msgId);
  if (!f) return;
  f.st = isErr ? statusText : (statusText.includes('✓') ? '已送达' : statusText);
  renderSentFiles();
}
function renderSentFiles() {
  const box = document.getElementById('sentFileList');
  if (!box) return;
  box.innerHTML = sentFiles.length
    ? '<div class="sent-list">' + sentFiles.map((f) =>
        '<div class="vrow"><span class="vlabel" style="min-width:0;flex:1">' + escHtml(f.name) +
        '</span><span class="vstate">' + fmtSize(f.size) + ' · ' + escHtml(f.st) + '</span></div>').join('') + '</div>'
    : '<p class="tip" style="margin:0">还没有发送过文件。点聊天框旁的回形针发送，观众会在聊天里收到下载卡片。</p>';
  const fc = document.getElementById('filesCount');
  if (fc) fc.textContent = sentFiles.length;
}
renderSentFiles();

// 快捷键：Alt+M 麦克风 · Alt+V 摄像头 · Alt+S 截图 · Alt+R 录制
document.addEventListener('keydown', (e) => {
  if (!e.altKey || e.metaKey || e.ctrlKey) return;
  if (e.target && e.target.matches && e.target.matches('input,textarea,select')) return;
  if (e.code === 'KeyM') { e.preventDefault(); document.getElementById('micBtn').click(); }
  else if (e.code === 'KeyV') { e.preventDefault(); const cb = document.getElementById('camBtn'); if (cb && !cb.disabled) cb.click(); }
  else if (e.code === 'KeyS') { e.preventDefault(); takeShot(); }
  else if (e.code === 'KeyR') { e.preventDefault(); toggleRec(); }
});

// e2e 断言钩子（fake 模式）
if (FAKE) window.__ssl = { peers, room: () => room, live: () => !!screenTrack };
(function refreshIconsOnce() {
  const run = () => { if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } }); };
  if (window.lucide) run(); else window.addEventListener('load', run);
})();
"""

HOST_BODY = """<header class="topbar">
  <a class="brand" href="./index.html" aria-label="同屏首页"><span class="brand-mark"><i data-lucide="screen-share"></i></span><span class="brand-name">同屏</span></a>
  <span class="brand-description">互动开播 · 8 人内双向通话</span>
  <div class="top-right">
    <button class="icon-btn" data-theme-toggle title="切换日夜模式" aria-label="切换日夜模式"></button>
    <a class="icon-btn" href="./admin.html" title="管理后台" aria-label="管理后台"><i data-lucide="settings-2"></i></a>
  </div>
</header>
<main class="page-body">
  <div id="liveStrip" class="live-strip">
    <div class="live-strip-status">
      <span class="status-dot off" id="stripDot"></span>
      <strong id="stripState">未开播</strong>
      <time id="stripClock" class="mono">00:00</time>
    </div>
    <div class="live-strip-stats">
      <span class="strip-stat">帧率 <b id="stripFps">—</b></span>
      <span class="strip-stat">速率 <b id="stripRate">—</b></span>
      <span class="strip-stat">延迟 <b id="stripRtt">—</b></span>
      <span class="strip-stat">线路 <b id="stripVia">—</b></span>
    </div>
    <button id="stopBtn" class="button danger" disabled><i data-lucide="phone-off"></i>结束共享</button>
  </div>
  <section class="room-heading">
    <div>
      <div class="heading-title"><h1>互动开播</h1></div>
    </div>
  </section>
  <div id="linkCard" class="live-bar">
    <span class="live-bar-icon"><i data-lucide="link"></i></span>
    <div class="live-bar-main">
      <div class="live-bar-label">观众链接</div>
      <div id="inviteLink" class="link"></div>
    </div>
    <button id="copyBtn" class="button primary" disabled><i data-lucide="copy"></i><span id="copyBtnLabel">复制观众链接</span></button>
  </div>
  <section class="workspace">
    <div class="stage-column">
      <section class="share-stage">
        <div class="stage-top">
          <div class="stage-top-left"><i data-lucide="app-window"></i><span id="sourceTitle">共享预览</span></div>
          <div class="stage-top-right"><span class="stage-quality">自适应画质</span><button class="icon-btn" id="stageFullBtn" aria-label="画面全屏" title="画面全屏"><i data-lucide="maximize"></i></button></div>
        </div>
        <div class="stage-content">
          <div id="secretCard" class="show">
            <span class="secret-icon"><i data-lucide="monitor-up"></i></span>
            <h2>准备好了就开始</h2>
            <div class="row" style="margin-top:16px"><input id="secretInput" type="password" placeholder="主播密钥 / 访客密码"><button id="saveSecretBtn" class="button" style="flex-shrink:0">保存</button></div>
            <div class="tip" id="codeTip" style="display:none;color:#7fb99a;text-align:center"></div>
            <div style="margin-top:14px"><button id="startBtn" class="button primary" style="font-size:15px;padding:13px 34px">开始共享</button></div>
          </div>
          <video id="preview" muted autoplay playsinline></video>
          <video id="camSelf" muted autoplay playsinline></video>
        </div>
      </section>
      <div id="liveStats" style="display:none;margin-top:2px"><div class="statrow">
        <span class="sitem">画质 <b id="stRes">—</b></span>
        <span class="sitem">帧率 <b id="stFps">—</b></span>
        <span class="sitem">采集 <b id="stCap">—</b></span>
        <span class="sitem">速率 <b id="stRate">—</b></span>
        <span class="sitem">编码 <b id="stEnc">—</b></span>
        <span class="sitem">延迟 <b id="stRtt">—</b></span>
        <span class="sitem">线路 <b id="stVia">—</b></span>
      </div></div>
      <div id="camsRow"></div>
    </div>
    <aside class="side-panel">
      <div class="panel-tabs" role="tablist" aria-label="协作面板">
        <button class="panel-tab" role="tab" id="tab-chat" data-panel="chat" aria-selected="true">聊天<span class="tab-count" id="chatCount">0</span></button>
        <button class="panel-tab" role="tab" id="tab-people" data-panel="people" aria-selected="false">成员<span class="tab-count" id="peopleCount">0</span></button>
        <button class="panel-tab" role="tab" id="tab-files" data-panel="files" aria-selected="false">文件<span class="tab-count" id="filesCount">0</span></button>
      </div>
      <section id="panel-chat" class="panel-content" role="tabpanel" aria-label="聊天">
        <div id="chatCard" class="chat-inner">
          <div id="chatList" class="chatlist"></div>
          <div class="chatrow">
            <select id="chatTarget" aria-label="发送对象"><option value="all">全体</option></select>
            <input id="chatInput" placeholder="输入消息，回车发送" maxlength="500" autocomplete="off">
            <button id="fileBtn" class="icon-btn" title="发文件给观众（直传七牛，不占服务器）" aria-label="发送文件"><i data-lucide="paperclip"></i></button>
            <input id="fileInput" type="file" style="display:none">
          </div>
        </div>
      </section>
      <section id="panel-people" class="panel-content" role="tabpanel" aria-label="成员" hidden>
        <div id="viewersCard" style="display:flex;flex-direction:column;flex:1;min-height:0">
          <div class="card-title"><i data-lucide="users"></i>观众与通话</div>
          <div id="viewerList" class="viewers"><p id="viewerEmpty">暂无观众</p></div>
          <div class="speakerRow" id="micRow">
            <span style="flex-shrink:0">我的麦克风</span>
            <span class="levelbar"><span class="levelfill" id="myLevel"></span></span>
          </div>
          <div class="speakerRow" id="micVolRow">
            <span style="flex-shrink:0">麦克风音量</span>
            <input type="range" id="micVol" min="0" max="200" value="100" aria-label="麦克风音量">
            <span id="micVolVal" class="range-val">100%</span>
          </div>
          <div class="speakerRow" id="sysVolRow">
            <span style="flex-shrink:0">系统声音</span>
            <input type="range" id="sysVol" min="0" max="200" value="100" disabled aria-label="系统声音音量">
            <span id="sysVolState" class="range-val">未共享</span>
          </div>
          <div class="speakerRow" id="speakerRow">
            <span style="flex-shrink:0">观众声音</span>
            <input type="range" id="volSlider" min="0" max="100" value="100" aria-label="观众声音音量">
            <button id="spkBtn" class="icon-btn" title="静音观众声音" aria-label="静音观众声音"><i data-lucide="volume-2"></i></button>
          </div>
          <div id="stats" class="stats"></div>
        </div>
      </section>
      <section id="panel-files" class="panel-content" role="tabpanel" aria-label="文件" hidden>
        <div class="section-kicker">本场发送的文件</div>
        <div id="sentFileList"></div>
      </section>
    </aside>
  </section>
  <section class="controls">
    <div class="connection-summary">
      <span class="connection-icon"><i data-lucide="signal"></i></span>
      <div><div class="connection-label">同屏 · 互动开播</div><div class="connection-meta">8 人内 · 双向通话 · 低延迟</div></div>
    </div>
    <div class="control-dock">
      <div class="control-item"><button id="micBtn" aria-pressed="false" title="麦克风 · Alt+M" aria-label="麦克风开关"><i data-lucide="mic"></i></button><span id="micBtnLabel" class="control-label">麦克风</span></div>
      <div class="control-item"><button id="camBtn" disabled title="摄像头 · Alt+V" aria-label="摄像头开关"><i data-lucide="video"></i></button><span id="camBtnLabel" class="control-label">摄像头</span></div>
      <div class="control-item"><button id="shotBtn" title="截图到剪贴板 · Alt+S" aria-label="截图"><i data-lucide="camera"></i></button><span class="control-label">截图</span></div>
      <div class="control-item"><button id="recBtn" title="录制本场直播 · Alt+R" aria-label="录制"><i data-lucide="disc"></i></button><span id="recLabel" class="control-label">录制</span></div>
      <span class="dock-divider" aria-hidden="true"></span>
      <div class="control-item"><button id="volBtn" title="音频推子与观众控制" aria-label="音频台"><i data-lucide="sliders-horizontal"></i></button><span class="control-label">音频台</span></div>
    </div>
  </section>
</main>
<div id="toast" role="status" aria-live="polite"></div>
"""

HOST_HEAD = """<!DOCTYPE html>
<html lang="zh-CN" data-build="__BUILD__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>同屏 · 互动开播</title>
<meta name="theme-color" content="#1c3f32">
<script>document.documentElement.dataset.theme = (function(){try{return localStorage.getItem('ssl_theme')||'dark'}catch(_){return 'dark'}})();</script>
<link rel="manifest" href="manifest.json">
<link rel="icon" href="__FAVICON__">
<link rel="stylesheet" href="theme.css">
<script src="theme-toggle.js"></script>
<script src="assets/lucide.min.js"></script>
</head>
<body>
""".replace('__FAVICON__', FAVICON)

(host_web := HOST_HEAD + HOST_BODY + '<script>' + script + '\n' + EXTRA + '</script>\n</body>\n</html>\n')
(WEB / 'host.html').write_text(HOST_HEAD + HOST_BODY + '<script>' + script + '\n' + EXTRA + '</script>\n</body>\n</html>\n')
print('host.html 组装完成')

# ---------------------------------------------------------------- viewer
viewer = ORIG_VIEWER

VIEWER_OVERRIDE = """<style>
/* 同屏 2026-09-27 主题升级：主色绿 + 加入页新视觉 + 表情回应 */
:root{--green:#285b48;--green-deep:#1c3f32;--canvas:#f5f6f3;--ink:#24332d;--muted:#727a75;--line:#e4e8e2}
#joinBtn{background:var(--green)}
#fpDownload{background:var(--green)}
.chm .fdl{background:rgba(40,91,72,.25);color:#8fc7a8}
.dm b{color:#8fc7a8}
.chm b{color:#8fc7a8}
#bar button.active{background:rgba(40,91,72,.38)}
#joinScreen{background:var(--canvas);color:var(--ink)}
#joinScreen h2{font-size:24px;letter-spacing:-.4px;color:var(--ink);font-weight:650}
#joinScreen p{color:var(--muted);font-size:13.5px;line-height:1.8;margin:10px 0 0}
.join-card{width:min(400px,100%);background:var(--paper);border:1px solid var(--line);border-radius:20px;padding:32px 28px 26px;text-align:center;box-shadow:0 1px 2px rgba(28,63,50,.05),0 10px 32px rgba(28,63,50,.08)}
.join-brand{display:flex;align-items:center;justify-content:center;gap:9px;font-weight:650;font-size:16px;margin-bottom:20px;color:var(--ink)}
.join-mark{width:36px;height:36px;border-radius:11px;background:var(--green-deep);color:#e9f1e9;display:inline-flex;align-items:center;justify-content:center}
.join-mark .icon{width:19px;height:19px}
.join-kicker{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:650;letter-spacing:.08em;color:var(--green);background:var(--light-green);border-radius:999px;padding:5px 14px;margin-bottom:14px}
.join-dot{width:8px;height:8px;border-radius:50%;background:#2e7d4f}
#nameInput{width:100%;margin-bottom:12px}
#joinBtn{width:100%;font-size:15px;padding:13px 0;border-radius:13px;font-weight:650}
#reactPanel{position:fixed;left:10px;right:10px;bottom:calc(84px + env(safe-area-inset-bottom));background:rgba(18,18,24,.92);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:10px;display:none;gap:6px;justify-content:space-around;z-index:56}
#reactPanel.open{display:flex}
#reactPanel button{font-size:26px;background:none;border:0;padding:8px 10px;border-radius:12px;cursor:pointer}
#reactPanel button:active{background:rgba(255,255,255,.12);transform:scale(1.18)}
#bar button .ico{display:flex;align-items:center;justify-content:center}
#bar button .icon{width:22px;height:22px;stroke-width:1.75}
#filePopup .fico .icon{width:36px;height:36px}
#flipBtn .icon{width:15px;height:15px}
#nameInput{padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--field);color:var(--ink);font-size:14.5px;text-align:center;transition:border-color 140ms}
#nameInput::placeholder{color:var(--muted)}
#nameInput:focus{outline:none;border-color:var(--green);box-shadow:0 0 0 3px rgba(40,91,72,.12)}
#joinBtn{border:0}
#topHang{margin-left:10px;width:34px;height:34px;border-radius:50%;border:0;background:rgba(224,82,82,.18);color:#ff8484;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;cursor:pointer}
#topHang:active{background:rgba(224,82,82,.35)}
#topHang .icon{width:17px;height:17px}
</style>
"""

VIEWER_REACT_JS = """
// ==================== 2026-09-27 新增：表情回应 ====================
const reactBtnEl = document.getElementById('reactBtn');
if (reactBtnEl) reactBtnEl.onclick = () => {
  document.getElementById('reactPanel').classList.toggle('open');
};
document.querySelectorAll('#reactPanel button').forEach((b) => {
  b.addEventListener('click', () => {
    const emo = b.dataset.emoji;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ t: 'signal', data: { control: 'react', emoji: emo } })); showToast('已发送 ' + emo); }
      catch (_) { showToast('发送失败'); }
    } else {
      showToast('还没有进入直播');
    }
    document.getElementById('reactPanel').classList.remove('open');
  });
});
document.addEventListener('click', (e) => {
  const p = document.getElementById('reactPanel');
  if (p && p.classList.contains('open') && !p.contains(e.target) && !(e.target.closest && e.target.closest('#reactBtn'))) p.classList.remove('open');
});
(function refreshIconsV() {
  const run = () => { if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } }); };
  if (window.lucide) run(); else window.addEventListener('load', run);
})();
"""

viewer = patch(viewer, [
    # V1 head：标题/manifest/图标/lucide
    ("""<title>屏幕共享 · 观看</title>""",
     """<title>同屏 · 观看</title>
<meta name="theme-color" content="#000000">
<script>document.documentElement.dataset.theme = (function(){try{return localStorage.getItem('ssl_theme')||'dark'}catch(_){return 'dark'}})();</script>
<link rel="manifest" href="manifest.json">
<link rel="icon" href="__FAVICON__">
<script src="theme-toggle.js"></script>
<script src="assets/lucide.min.js"></script>""".replace('__FAVICON__', FAVICON)),
    # V2 override 样式
    ("</style>", "</style>\n" + VIEWER_OVERRIDE),
    # V4 底栏加回应按钮
    ("""  <button id="chatBtn"><span class="ico">💬</span><span>聊天</span></button>""",
     """  <button id="chatBtn"><span class="ico">💬</span><span>聊天</span></button>
  <button id="reactBtn"><span class="ico">🎉</span><span>回应</span></button>"""),
    # V5 回应面板
    ("""<div id="toast"></div>""",
     """<div id="reactPanel"><button data-emoji="👍">👍</button><button data-emoji="👏">👏</button><button data-emoji="❤️">❤️</button><button data-emoji="😂">😂</button><button data-emoji="😮">😮</button><button data-emoji="🙋">🙋</button></div>
<div id="toast"></div>"""),
    # V3 加入页重做（保留 nameInput/joinBtn id）
    ("""<div id="joinScreen">
  <h2>有人想给你看他的屏幕</h2>
  <p>点下方按钮加入。加入后你能看到对方的屏幕，<br>并且可以开口对话（会用到你的麦克风）。</p>
  <input id="nameInput" placeholder="你的称呼（对方会看到）" maxlength="12"
    style="font:inherit;font-size:14px;padding:10px 14px;border-radius:999px;border:1px solid #33333d;background:#1c1c23;color:#e8e8ee;width:240px;text-align:center">
  <button id="joinBtn">加入观看</button>
  <div style="font-size:10px;color:#55555e" id="ver"></div>
</div>""",
     """<div id="joinScreen" class="show">
  <div class="join-card">
    <div class="join-brand"><span class="join-mark"><i data-lucide="screen-share"></i></span>同屏</div>
    <div class="join-kicker"><span class="join-dot"></span>共享邀请</div>
    <h2>有人想给你看他的屏幕</h2>
    <p class="join-desc">加入后你能看到对方的屏幕，<br>并且可以开口对话（会用到你的麦克风）。</p>
    <input id="nameInput" placeholder="你的称呼（对方会看到）" maxlength="12" autocomplete="nickname">
    <button id="joinBtn">加入观看</button>
  </div>
</div>"""),
    # V6 joinBtn 空指针修复（链接不完整时 joinScreen 被 innerHTML 替换，$ 取不到）
    ("$('joinBtn').onclick = join;", "if ($('joinBtn')) $('joinBtn').onclick = join;"),
    # V7 末尾追加回应逻辑
    ("</script>\n</body>\n</html>", VIEWER_REACT_JS + "</script>\n</body>\n</html>"),
    # V8 底栏/弹窗图标 Lucide 化（黑底 emoji 对比度事故 + 与主播端体系统一）
    ('''  <button id="muteBtn"><span class="ico">🎙️</span><span>麦克风</span></button>''',
     '''  <button id="muteBtn"><span class="ico"><i data-lucide="mic"></i></span><span>麦克风</span></button>'''),
    ('''  <button id="camBtn"><span class="ico">📷</span><span>摄像头</span></button>''',
     '''  <button id="camBtn"><span class="ico"><i data-lucide="video"></i></span><span>摄像头</span></button>'''),
    ('''  <button id="reactBtn"><span class="ico">🎉</span><span>回应</span></button>''',
     '''  <button id="reactBtn"><span class="ico"><i data-lucide="party-popper"></i></span><span>回应</span></button>'''),
    ('''  <button id="boostBtn"><span class="ico">🚀</span><span>提速</span></button>''',
     '''  <button id="boostBtn"><span class="ico"><i data-lucide="rocket"></i></span><span>提速</span></button>'''),
    ('''  <button id="fullBtn"><span class="ico">⛶</span><span>全屏</span></button>''',
     '''  <button id="fullBtn"><span class="ico"><i data-lucide="maximize"></i></span><span>全屏</span></button>'''),
    ('''  <button id="hangBtn" class="danger"><span class="ico">✕</span><span>挂断</span></button>''',
     '''  <button id="hangBtn" class="danger"><span class="ico"><i data-lucide="x"></i></span><span>挂断</span></button>'''),
    ('''<button id="flipBtn">🔄</button>''',
     '''<button id="flipBtn"><i data-lucide="refresh-cw"></i></button>'''),
    ('''  <div class="fico">📎</div>''',
     '''  <div class="fico"><i data-lucide="paperclip"></i></div>'''),
    # V9 mic 图标切换 JS（两处缩进不同，分别打）
    ("""    $('muteBtn').querySelector('.ico').textContent = selfMuted ? '🔇' : '🎙️';""",
     """    const muteIcoH = $('muteBtn').querySelector('.ico'); muteIcoH.innerHTML = '<i data-lucide="' + (selfMuted ? 'mic-off' : 'mic') + '"></i>'; if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });"""),
    ("""  $('muteBtn').querySelector('.ico').textContent = selfMuted ? '🔇' : '🎙️';""",
     """  const muteIcoC = $('muteBtn').querySelector('.ico'); muteIcoC.innerHTML = '<i data-lucide="' + (selfMuted ? 'mic-off' : 'mic') + '"></i>'; if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });"""),
    # V11 顶部状态栏右侧加挂断（最重要的操作放顶部，底部控制条保留）
    ("""<div id="topbar">
  <span id="dot" class="dot off"></span><span id="topStatus">未连接</span>
  <span id="topMeta"></span>
</div>""",
     """<div id="topbar">
  <span id="dot" class="dot off"></span><span id="topStatus">未连接</span>
  <span id="topMeta"></span>
  <button id="topHang" aria-label="挂断" title="挂断"><i data-lucide="phone-off"></i></button>
</div>"""),
    # V12 顶部挂断绑定（复用底部挂断逻辑）
    ("""// ==================== 2026-09-27 新增：表情回应 ====================""",
     """// ==================== 2026-09-27 新增：顶部挂断 + 表情回应 ====================
const topHangEl = document.getElementById('topHang');
if (topHangEl) topHangEl.onclick = () => { const hb = document.getElementById('hangBtn'); if (hb) hb.click(); };
// ==================== 表情回应 ===================="""),
], 'viewer')

(WEB / 'viewer.html').write_text(viewer)
print('viewer.html 组装完成')

# ---- 构建号注入（本地即成品；线上 deploy.sh 再注入一次，无占位符则无操作）----
import datetime
build = datetime.datetime.now().strftime('%m-%d %H:%M')
for name in ('host.html', 'viewer.html', 'index.html', 'admin.html'):
    p = WEB / name
    txt = p.read_text()
    if '__BUILD__' in txt:
        p.write_text(txt.replace('__BUILD__', build))
print('构建号注入:', build)
print('全部完成')
