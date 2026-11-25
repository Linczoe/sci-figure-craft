// BioRender 素材采集：CDP 批处理驱动（单会话，保持仿真视口）。不含任何凭据。
// 用法：node biorender_capture.mjs <script.json>
//   script = 步骤数组，顺序执行；任一步失败打印 FAIL 并继续下一步。
//   前置条件：已按 references/biorender-capture.md 启动带 --remote-debugging-port 的
//   隔离浏览器，并打开一个已登录、可编辑的 BioRender 画布。
// 主要 op：
//   {"op":"nav","url":"...","wait":30000}         打开画布并等待加载
//   {"op":"count"}                                  读 "N / 50 objects" 计数
//   {"op":"search","term":"mouse"}                  搜索并返回几何排序后的缩略图
//   {"op":"place","term":"mouse","index":1,"cx":762,"cy":330}   拖入第 index 个结果
//   {"op":"placepos","term":"mouse","col":1,"row":0,"cx":762,"cy":330} 按网格(列,行)拖入
//   {"op":"shot","path":"raw/mouse.png","scale":3}  视口截图（scale 3；4 倍 WebGL 会黑图）
//   {"op":"delc"}                                   中心逐点点击+Delete 直到清零
//   {"op":"marquee"} / {"op":"wipe"} / {"op":"clear"}  其他清空画布方式
//   {"op":"click","x":..,"y":..} {"op":"key",...} {"op":"eval","expr":...} {"op":"sleep","ms":..}
// 典型单图标回路见 biorender_capture_run.ps1；坐标默认值对应 1400x900 窗口布局。
import fs from 'node:fs';

const PORT = process.env.CDP_PORT || '9222';
const script = JSON.parse(fs.readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, ''));
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find(t => t.type === 'page' && /biorender/i.test(t.url || '')) || list.find(t => t.type === 'page');
if (!page) { console.error('NO_PAGE_TARGET'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0; const pending = new Map();
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); } };
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
await send('Page.enable');
try { await send('Page.bringToFront'); } catch (e) {}   // 页面在后台时拖放不生效：每次先把页面置前
await new Promise(r => setTimeout(r, 400));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function ev(expr) { const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result?.value; }
async function mouse(type, x, y, buttons) { await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons, clickCount: 1 }); }
async function click(x, y) { await mouse('mouseMoved', x, y, 0); await sleep(60); await mouse('mousePressed', x, y, 1); await sleep(60); await mouse('mouseReleased', x, y, 0); }
async function drag(x1, y1, x2, y2) {
  await mouse('mouseMoved', x1, y1, 0); await sleep(200);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y: y1, button: 'left', buttons: 1, clickCount: 1 });
  const n = 20;
  for (let i = 1; i <= n; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x1 + (x2 - x1) * i / n, y: y1 + (y2 - y1) * i / n, button: 'left', buttons: 1 }); await sleep(25); }
  await sleep(200);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y: y2, button: 'left', buttons: 0, clickCount: 1 });
}
async function key(k, vk, mod = 0, code = '') { await send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk, modifiers: mod }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk, modifiers: mod }); }
// 让画布拿到键盘焦点（搜索框会抢焦点，导致 Ctrl+A / Delete 无效）；不要 canvas.focus()，应用快捷键监听会失效
const FOCUS = `(()=>{const a=document.activeElement; if(a&&a.blur&&a.tagName!=='BODY') a.blur(); return document.activeElement.tagName;})()`;
async function shot(path, scale = 1) {
  const m = await send('Page.getLayoutMetrics');
  const w = Math.ceil(m.cssVisualViewport.clientWidth), h = Math.ceil(m.cssVisualViewport.clientHeight);
  if (scale !== 1) await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: scale, mobile: false });
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  if (scale !== 1) await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  fs.writeFileSync(path, Buffer.from(data, 'base64'));
  return `saved ${path} scale=${scale}`;
}
const dismiss = `(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^dismiss$/i.test((x.textContent||'').trim()));if(b){b.click();return 'dismissed';}return 'no-banner';})()`;
const SETTER = `(()=>{const t=document.querySelector('#biorender-asset-search-panel textarea');if(!t)return 'NO_TA';t.focus();const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;s.call(t,TERM);t.dispatchEvent(new InputEvent('input',{bubbles:true}));return 'TYPED';})()`;
const openPanel = `(()=>{const t=document.querySelector('#biorender-asset-search-panel textarea');if(t)return 'OPEN';const b=[...document.querySelectorAll('button,a,div,span')].filter(e=>(e.textContent||'').trim()==='Search').map(e=>({e,r:e.getBoundingClientRect()})).filter(o=>o.r.x<80&&o.r.width>10&&o.r.width<90).sort((a,b)=>b.r.width-a.r.width)[0];if(!b)return 'NO_SEARCH_BTN';return JSON.stringify({x:b.r.x+b.r.width/2,y:b.r.y+b.r.height/2});})()`;
async function search(term, retry = true) {
  let st = await ev(openPanel);
  if (st !== 'OPEN') { if (st === 'NO_SEARCH_BTN') throw new Error('NO_SEARCH_BTN'); const p = JSON.parse(st); await click(p.x, p.y); await sleep(2500); }
  await ev(SETTER.replace('TERM', '""')); await sleep(350);      // 先清空，确保同词重搜也触发 input
  const typed = await ev(SETTER.replace('TERM', JSON.stringify(term)));
  await sleep(1500);
  const row = await ev(`(()=>{const els=[...document.querySelectorAll('#biorender-asset-search-panel *')].filter(e=>/^Search for:/.test((e.textContent||'').trim())&&e.children.length<=3);if(!els.length)return null;const b=els[els.length-1].getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()`);
  if (!row) throw new Error('NO_SEARCH_ROW after ' + typed);
  await click(row.x, row.y);
  const sig = () => ev(`JSON.stringify([...document.querySelectorAll('#biorender-asset-search-panel img')].filter(i=>(i.src||'').includes('icons.cdn')).slice(0,8).map(i=>(i.src||'').slice(-48)))`);
  const before = await sig();
  let thumbs = []; let changed = false;
  const pick = `[...document.querySelectorAll('#biorender-asset-search-panel img')].filter(i=>{const s=i.src||'';return s.includes('icons.cdn')||/\\/biorender\\/.+\\/image\\//.test(s);}).map(i=>{const b=i.getBoundingClientRect();return {x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2),w:Math.round(b.width),h:Math.round(b.height)};}).filter(o=>o.w>30&&o.w<=100&&o.x>=90&&o.x<=372&&o.y>=215&&o.y<=560)`;
  for (let k = 0; k < 40; k++) {   // 轮询最多 20 s：等"新"结果（首行 src 相对搜索前已变化，防止拿到上一次搜索的旧结果）
    await sleep(500);
    thumbs = JSON.parse(await ev(`JSON.stringify(${pick})`));
    if (thumbs.length >= 8) { if ((await sig()) !== before) { changed = true; await sleep(1000); thumbs = JSON.parse(await ev(`JSON.stringify(${pick})`)); break; } }
  }
  if (!changed && thumbs.length >= 8) console.log('  note: results signature unchanged (same term?) -> accepting');
  // 行优先排序：同一行（y 相差 < 40）按 x 升序，再按行；DOM 顺序与视觉行列不一致，不能按 DOM 取序号
  thumbs.sort((a, b) => (Math.abs(a.y - b.y) < 40 ? a.x - b.x : a.y - b.y));
  if (thumbs.length === 0 && retry) return search(term, false);   // 重试一次
  if (thumbs.length === 0) {
    const dbg = await ev(`(function(){const all=[...document.querySelectorAll('#biorender-asset-search-panel img')];const a=all.filter(i=>(i.src||'').includes('icons.cdn'));const m=a.map(i=>{const b=i.getBoundingClientRect();return {x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2),w:Math.round(b.width),h:Math.round(b.height)};});const f=m.filter(o=>o.w>30&&o.w<=100&&o.x>=90&&o.x<=372&&o.y>=215&&o.y<=560);return JSON.stringify({all:all.length,cdn:a.length,mapped:m.length,pass:f.length,first:m.slice(0,4)});})()`);
    console.log('  dbg: ' + dbg);
    const txt = await ev(`(document.querySelector('#biorender-asset-search-panel')||document.body).innerText.slice(0,160).replace(/\\s+/g,' ')`); console.log('  panel: ' + txt);
  }
  return thumbs;
}
const count = () => ev("document.body.innerText.match(/\\d+\\s*\\/\\s*\\d+\\s*objects/)?.[0]||'NO'");
const canvasRect = () => ev(`(()=>{const cs=[...document.querySelectorAll('canvas')].map(c=>{const b=c.getBoundingClientRect();return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),area:b.width*b.height}}).sort((a,b)=>b.area-a.area);return JSON.stringify(cs[0]||null);})()`);

let canvas = null, out0 = '';
const num = (s) => parseInt(String(s), 10) || 0;
const settleCount = async (c0, ms = 5000) => {   // 对象计数刷新滞后：轮询直到变化或超时
  const t0 = Date.now(); let c = String(await count());
  while (num(c) === num(c0) && Date.now() - t0 < ms) { await sleep(400); c = String(await count()); }
  return c;
};
for (const step of script) {
  const o = step.op; let out = out0; out0 = '';
  try {
    if (o === 'viewport') { await send('Emulation.setDeviceMetricsOverride', { width: step.w, height: step.h, deviceScaleFactor: 1, mobile: false }); await sleep(step.wait || 1500); out = `viewport ${step.w}x${step.h}`; }
    else if (o === 'nav') { await send('Page.navigate', { url: step.url }); await sleep(step.wait || 30000); out = `nav objects=${await count()}`; }
    else if (o === 'dismiss') { out = String(await ev(dismiss)); }
    else if (o === 'count') { out = String(await count()); }
    else if (o === 'canvas') { canvas = JSON.parse(await canvasRect()); out = JSON.stringify(canvas); }
    else if (o === 'count0') { out = String(await count()); }
    else if (o === 'search') { const t = await search(step.term); if (step.shot) await shot(step.shot, step.scale || 1); out = `${step.term}: ${t.length} thumbs first=${JSON.stringify(t[0] || null)}`; }
    else if (o === 'place') { if (!canvas) canvas = JSON.parse(await canvasRect()); const t = await search(step.term.replace(/^#/, '')); const i = Number(step.index ?? 0); if (!t[i]) throw new Error(`NO_THUMB ${step.term}[${i}] of ${t.length}`); let placed = false; for (let k = 0; k < 2 && !placed; k++) { const c0 = await count(); await drag(t[i].x, t[i].y, step.cx, step.cy); await sleep(1500); const c1 = await settleCount(c0); placed = num(c1) !== num(c0); if (!placed) await sleep(800); } out = `${placed ? 'placed' : 'NOT_PLACED'} ${step.term}[${i}] -> ${step.cx},${step.cy} objects=${await count()}`; }
    else if (o === 'placepos') {   // 按结果网格的（列,行）取缩略图：期望坐标 = 列[113,190,266,343] × 行[232,321,410,499]
      if (!canvas) canvas = JSON.parse(await canvasRect()); const t = await search(step.term); if (!t.length) throw new Error('NO_THUMBS ' + step.term);
      const ex = [113, 190, 266, 343][step.col], ey = [232, 321, 410, 499][step.row];
      let best = null, bd = 1e9; for (const th of t) { const d = Math.hypot(th.x - ex, th.y - ey); if (d < bd) { bd = d; best = th; } }
      if (bd > 22) throw new Error(`NO_THUMB_AT ${step.col},${step.row} (nearest ${Math.round(bd)}px) for ${step.term}`);
      let placed = false; for (let k = 0; k < 2 && !placed; k++) { const c0 = await count(); await drag(best.x, best.y, step.cx, step.cy); await sleep(1500); const c1 = await settleCount(c0); placed = num(c1) !== num(c0); if (!placed) await sleep(800); }
      out = `${placed ? 'placed' : 'NOT_PLACED'} ${step.term}@${step.col},${step.row} -> ${step.cx},${step.cy} objects=${await count()}`; }
    else if (o === 'shot') { out = await shot(step.path, step.scale || 1); }
    else if (o === 'eval') { out = String(await ev(step.expr)); }
    else if (o === 'click') { await click(step.x, step.y); out = `click ${step.x},${step.y}`; }
    else if (o === 'key') { await key(step.key, step.vk, step.mod || 0); out = `key ${step.key}`; }
    else if (o === 'wipe') {   // 清空画布：夺回键盘焦点 → 点空白处 → Ctrl+A → Delete，校验为 0
      let ok = false, last = '';
      for (let k = 0; k < 4 && !ok; k++) {
        await ev(FOCUS); await click(1000, 575); await sleep(300); await ev(FOCUS);
        await key('a', 65, 2, 'KeyA'); await sleep(400); await key('Delete', 46, 0, 'Delete'); await sleep(1000);
        last = String(await count()); ok = /^0\s/.test(last);
      }
      out = `wipe -> objects=${last}`;
    }
    else if (o === 'del') {   // 点中画布 (x,y) 处的对象并删除，直到对象数不再减少
      let c0 = await count();
      for (let k = 0; k < 5; k++) { await click(step.x, step.y); await sleep(350); await key('Delete', 46, 0, 'Delete'); await sleep(800); const c1 = await count(); if (c1 === c0) break; c0 = c1; }
      out = `del at ${step.x},${step.y} -> objects=${c0}`;
    }
    else if (o === 'clear') { if (!canvas) canvas = JSON.parse(await canvasRect()); let ok = false; for (let k = 0; k < 3 && !ok; k++) { await click(step.x || 762, step.y || 330); await sleep(300); await key('a', 65, 2); await sleep(300); await key('Delete', 46); await sleep(900); ok = /^0\s/.test(String(await count())); } out = `clear -> objects=${await count()}`; }
    else if (o === 'marquee') {   // 框选整张画布后删除；若未清零，再逐点扫描点击删除
      let last = String(await count());
      for (let k = 0; k < 3 && !/^0\s/.test(last); k++) {
        await ev(FOCUS); await click(1000, 575); await sleep(250);
        await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 426, y: 118, button: 'left', buttons: 1, clickCount: 1 }); await sleep(150);
        for (let i = 1; i <= 12; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 426 + (1100 - 426) * i / 12, y: 118 + (604 - 118) * i / 12, button: 'left', buttons: 1 }); await sleep(30); }
        await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 1100, y: 604, button: 'left', buttons: 0, clickCount: 1 }); await sleep(500);
        await key('Delete', 46, 0, 'Delete'); await sleep(1200);
        last = String(await count());
      }
      let guard = 0;
      while (!/^0\s/.test(last) && guard < 1) {
        guard++;
        for (let y = 130; y <= 600 && !/^0\s/.test(last); y += 40) for (let x = 440; x <= 1095; x += 40) {
          await click(x, y); await sleep(80); await key('Delete', 46, 0, 'Delete'); await sleep(140);
          if (((x - 440) / 40) % 5 === 0) last = String(await count());
          if (/^0\s/.test(last)) break;
        }
        last = String(await count());
      }
      out = `marquee-wipe -> objects=${last}`;
    }
    else if (o === 'delc') {   // 中心附近逐点点击并 Delete，直到对象数不再减少
      const pts = [[762, 330], [730, 315], [795, 315], [730, 350], [795, 350], [762, 292], [762, 372], [700, 332], [825, 332], [762, 262], [762, 405]];
      let c0 = String(await count());
      for (let round = 0; round < 7 && !/^0\s/.test(c0); round++) {
        let changed = false;
        for (const [x, y] of pts) {
          await click(x, y); await sleep(450); await key('Delete', 46, 0, 'Delete'); await sleep(1500);
          const c1 = String(await count()); if (c1 !== c0) { changed = true; c0 = c1; }
          if (/^0\s/.test(c0)) break;
        }
        if (!changed) break;
      }
      out = `delc -> objects=${c0}`;
    }
    else if (o === 'rawkey') { await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: step.key, windowsVirtualKeyCode: step.vk, modifiers: step.mod || 0 }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: step.key, windowsVirtualKeyCode: step.vk, modifiers: step.mod || 0 }); out = `rawkey ${step.key}`; }
    else if (o === 'sleep') { await sleep(step.ms); out = `slept ${step.ms}`; }
    else if (o === 'resize') {
      // 浏览器级：把真实窗口设为指定尺寸（不经仿真，编辑器 iframe 不吃仿真视口），然后重载页面
      await send('Emulation.clearDeviceMetricsOverride');
      const wf = await send('Browser.getWindowForTarget', {});
      try { await send('Browser.setWindowBounds', { windowId: wf.windowId, bounds: { windowState: 'normal' } }); } catch (e) {}
      await send('Browser.setWindowBounds', { windowId: wf.windowId, bounds: { left: 0, top: 0, width: step.w, height: step.h } });
      await sleep(1500);
      out0 = `bounds set ${step.w}x${step.h}; `;
      await send('Page.reload'); await sleep(step.wait || 36000);
      out = `resized real window ${step.w}x${step.h}; ` + String(await ev('JSON.stringify({win:[innerWidth,innerHeight], dpr:devicePixelRatio, screen:[screen.width,screen.height], canvases:document.querySelectorAll("canvas").length, txt:document.body.innerText.slice(0,80).replace(/\\s+/g," ")})'));
    }
    else out = 'unknown op ' + o;
  } catch (err) { console.log(`FAIL at ${o} (${step.term || step.path || ''}): ${err.message}`); continue; }
  console.log(out);
}
ws.close();
