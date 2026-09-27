#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同屏 2026-09-27 改版 e2e：fake 模式全链路验证 + 视觉验收截图"""
import pathlib, sys, time
from playwright.sync_api import sync_playwright

CHROME = '/Users/jacksun/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
BASE = 'http://127.0.0.1:8018'
OUT = pathlib.Path('/Users/jacksun/Documents/screen-share-live/review-2026-09-27')
OUT.mkdir(exist_ok=True)

results, js_errors = [], []

def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('PASS ' if ok else 'FAIL ') + name + ((' —— ' + detail) if detail else ''))

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)

    # ---------- 落地页 ----------
    pg_idx = browser.new_page(viewport={'width': 1440, 'height': 900})
    pg_idx.on('pageerror', lambda e: js_errors.append('index: ' + str(e)))
    pg_idx.goto(BASE + '/index.html')
    pg_idx.wait_for_load_state('networkidle')
    pg_idx.screenshot(path=str(OUT / '06-index.png'))
    check('落地页渲染', pg_idx.locator('.entry-card').count() == 3, '3 个入口卡')

    # ---------- 主播端：待命态 ----------
    pg_host = browser.new_page(viewport={'width': 1440, 'height': 900})
    pg_host.on('pageerror', lambda e: js_errors.append('host: ' + str(e)))
    pg_host.goto(BASE + '/host.html?fake=1&autostart=1&secret=dd329e399644b1d06177a09f434cc788')
    pg_host.wait_for_function("document.title.includes('H:ok:r')", timeout=15000)
    title = pg_host.title()
    room = title.split('H:ok:r')[1].strip()
    check('主播信令建立（房间 ' + room + '）', bool(room), title)
    pg_host.wait_for_timeout(800)
    pg_host.screenshot(path=str(OUT / '02-host-live.png'))
    check('待命卡已隐藏', not pg_host.locator('#secretCard').is_visible())
    badge_txt = pg_host.locator('#stateBadge').inner_text()
    check('状态徽章=直播中(或被摄像头瞬时态覆盖，原版行为)', ('直播中' in badge_txt) or ('摄像头' in badge_txt), badge_txt)
    check('观众链接已展示', 'viewer.html?r=' in pg_host.locator('#inviteLink').inner_text())
    check('直播条常驻可见', pg_host.locator('#linkCard').is_visible())
    copy_disabled = pg_host.locator('#copyBtn').is_disabled()
    check('复制按钮已启用', not copy_disabled)
    pg_host.click('#copyBtn')
    pg_host.wait_for_timeout(400)
    check('复制反馈', '已复制' in pg_host.locator('#copyBtnLabel').inner_text())
    check('stats 条可见', pg_host.locator('#liveStats').is_visible())
    # 录制按钮
    pg_host.click('#recBtn')
    pg_host.wait_for_timeout(1300)
    rec_label = pg_host.locator('#recLabel').inner_text()
    check('录制启动并计时', ':' in rec_label, rec_label)
    pg_host.click('#recBtn')  # 停止 → 触发下载
    pg_host.wait_for_timeout(600)

    # ---------- 观众端：加入页（移动视角，先截不加入的 join 页） ----------
    pg_view = browser.new_page(viewport={'width': 390, 'height': 844})
    pg_view.on('pageerror', lambda e: js_errors.append('viewer: ' + str(e)))
    pg_view.goto(BASE + f'/viewer.html?r={room}&fake=1')
    pg_view.wait_for_timeout(700)
    pg_view.screenshot(path=str(OUT / '04-viewer-join.png'))
    check('加入页渲染（品牌+称呼输入）', pg_view.locator('#joinScreen .join-card').is_visible() and pg_view.locator('#nameInput').is_visible())
    # 加入
    pg_view.fill('#nameInput', '测试观众')
    pg_view.click('#joinBtn')
    pg_view.wait_for_function("document.title === 'V:connected'", timeout=20000)
    check('观众接入（V:connected）', True)
    pg_view.wait_for_timeout(1200)
    pg_view.screenshot(path=str(OUT / '05-viewer-watching.png'))

    # 主播端成员面板应出现观众行
    pg_host.click('#tab-people')
    pg_host.wait_for_timeout(400)
    check('主播看到观众行', '测试观众' in pg_host.locator('#viewerList').inner_text())
    pg_host.screenshot(path=str(OUT / '02b-host-people.png'))

    # ---------- 聊天双向 ----------
    pg_view.click('#chatBtn')  # 打开观众端聊天浮层
    pg_view.wait_for_timeout(400)
    pg_view.fill('#coInput', '孙哥好，画面很清楚')
    pg_view.click('#coSend')
    pg_host.click('#tab-chat')
    pg_host.wait_for_timeout(500)
    host_chat = pg_host.locator('#chatList').inner_text()
    check('观众→主播 消息到达', '孙哥好，画面很清楚' in host_chat)
    pg_host.fill('#chatInput', '收到，看这个窗口')
    pg_host.press('#chatInput', 'Enter')
    pg_view.wait_for_timeout(600)
    check('主播→观众 弹幕到达', '收到，看这个窗口' in pg_view.locator('#danmaku').inner_text())

    # ---------- 表情回应 ----------
    pg_view.click('#coClose')  # 关聊天浮层，露出底栏
    pg_view.wait_for_timeout(400)
    pg_view.click('#reactBtn')
    pg_view.wait_for_timeout(300)
    check('回应面板展开', pg_view.locator('#reactPanel').is_visible())
    pg_view.click('#reactPanel button[data-emoji="👍"]')
    pg_host.wait_for_timeout(600)
    check('主播收到回应👍', '👍' in pg_host.locator('#chatList').inner_text())
    pg_host.click('#tab-people')
    pg_host.screenshot(path=str(OUT / '02c-host-react.png'))

    # ---------- 截图功能 ----------
    pg_host.click('#shotBtn')
    pg_host.wait_for_timeout(700)
    toast_txt = pg_host.locator('#toast').inner_text()
    check('截图反馈', ('截图' in toast_txt), toast_txt)

    # ---------- 管理后台：登录（无验证码） → 生成访客码 → 列表/房间 ----------
    pg_admin = browser.new_page(viewport={'width': 1280, 'height': 900})
    pg_admin.on('pageerror', lambda e: js_errors.append('admin: ' + str(e)))
    pg_admin.goto(BASE + '/admin.html')
    pg_admin.wait_for_timeout(800)
    pg_admin.screenshot(path=str(OUT / '09-admin-login.png'))
    check('admin 登录页渲染（无验证码）', pg_admin.locator('#loginCard').is_visible() and pg_admin.locator('#capInput').count() == 0)
    pg_admin.fill('#userInput', 'jacksun')
    pg_admin.fill('#passInput', 'jacksun1234')
    pg_admin.click('#loginBtn')
    pg_admin.wait_for_function("document.getElementById('mainCard').style.display === 'block'", timeout=10000)
    check('admin 登录成功进入主界面', True)
    pg_admin.fill('#nameInput', 'e2e 测试访客')
    pg_admin.click('#genBtn')
    pg_admin.wait_for_function("document.getElementById('newCode').style.display === 'block'", timeout=10000)
    new_code = pg_admin.locator('#newCode').inner_text().strip()
    check('访客码已生成', len(new_code) == 8, new_code)
    check('开播链接已带码', f'code={new_code}' in pg_admin.locator('#newLinkText').inner_text())
    pg_admin.wait_for_timeout(500)
    check('访客列表出现新码', new_code in pg_admin.locator('#guestRows').inner_text())
    pg_admin.screenshot(path=str(OUT / '10-admin-main.png'))

    # ---------- 主播端移动视角 ----------
    pg_m = browser.new_page(viewport={'width': 390, 'height': 844})
    pg_m.on('pageerror', lambda e: js_errors.append('host-mobile: ' + str(e)))
    pg_m.goto(BASE + '/host.html?fake=1&autostart=1&secret=dd329e399644b1d06177a09f434cc788')
    pg_m.wait_for_function("document.title.includes('H:ok:r')", timeout=15000)
    pg_m.wait_for_timeout(800)
    pg_m.screenshot(path=str(OUT / '03-host-mobile.png'), full_page=True)
    check('主播端移动布局可渲染', True)

    # ---------- 无 JS 报错 ----------
    check('全程无 JS 异常', not js_errors, '; '.join(js_errors[:3]))

    browser.close()

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
sys.exit(1 if fails else 0)
