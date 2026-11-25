# BioRender 素材采集适配器（可选）

经用户明确授权后，用 CDP 浏览器自动化批量采集画布图标为 RGBA 素材。
本适配器只是 `assets-and-licensing.md` 中"页面自动化可选适配器"的具体实现；
授权边界、验证码/二次验证即停、不规避导出与水印限制、不删云端文件等规则全部沿用，
不在此重复。核心工作流不依赖本适配器；无 Node 或无授权时按原流程手动取材。

脚本（均在 `scripts/`）：

| 文件 | 作用 |
|---|---|
| `biorender_capture.mjs` | CDP 批处理驱动：搜索、拖放、截图、清空等 op，JSON 步骤数组顺序执行 |
| `biorender_capture_run.ps1` | 单图标采集回路：每步独立 node 进程 + 超时 + 重试 |
| `biorender_cutout.py` | 从中心窗口截图抠出 RGBA PNG（依赖 Pillow、numpy、scipy） |

## 1. 启动隔离浏览器

不碰用户日常浏览器；用独立 profile 起带 CDP 的 Edge/Chrome：

```powershell
Start-Process "<edge.exe>" -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=<项目>_参考\br_profile",
  "--no-first-run", "--no-default-browser-check",
  "--disable-features=CalculateNativeWinOcclusion",
  "--window-size=1400,900",
  "https://app.biorender.com/")
```

- 窗口尺寸用启动参数设**真实窗口**，不要用仿真视口凑尺寸：编辑器在 iframe/WebGL 里，不吃仿真。
- `CalculateNativeWinOcclusion` 必须关：窗口被遮挡/最小化后 `visibilityState=hidden`，鼠标拖放会静默失效。
- 驱动每次运行已内置 `Page.bringToFront`；批量运行时仍应避免遮挡该窗口。

## 2. 登录

凭据只经 `biorender_auth.py` 从本机私有文件读到内存，用 CDP 注入登录表单，不写盘、不回显、
不进脚本与日志。遇到验证码或二次验证立即停止，请用户处理。也可经用户授权复制已登录
浏览器的登录态到隔离 profile；用完连同 profile 一起删除。

## 3. 画布与配额

免费账号"新建插画"配额可能用尽：复用画廊里一张**用户允许改动的空旧画布**（先经用户确认），
不要新建，也不要删除任何云端画布。注意对象上限（如 50 objects）：组合图标一次可能带入
十几个对象，超限时放置会失败。搜索面板里带皇冠的是付费图标，跳过。

## 4. 采集回路（一次一个图标）

先把要采的图标写成 items.json（`term` 搜索词、`index` 结果序号、`name` 本地名）：

```json
[
  {"term": "mouse", "index": 1, "name": "mouse"},
  {"term": "tablet", "index": 0, "name": "tablet_white"}
]
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\biorender_capture_run.ps1" `
  -Items items.json -RawDir "<项目>\_参考\raw" -From 0 -To 6
```

每个图标的回路：**delc 清零 → place 拖入画布中心（失败重试 ≤3）→ 点空白取消选择 → 3 倍截图 → delc 清零**。
小批量运行（每批 5–7 个），便于定位失败项。

挑选 index 时不要盲猜：先用 harness 的 `search` op 对每个候选词截图，把结果面板拼成对照图，
看图选定后再填 items.json。结果含宽图或重复项时序号可能错位，改用 `placepos` op 按
网格（列,行）取；个别错位项单独补拍即可。

关键不变量（回路已内置，改动脚本时不得破坏）：

1. 截图倍率用 3，不用 4：4 倍仿真下 WebGL 画布渲染为全黑。
2. 截图前必须取消选择，否则蓝色选择框会混进素材。
3. 对象计数刷新滞后，放置/删除后必须轮询确认计数变化，不能立即读一次就下结论。
4. 键盘事件用带 `code` 的标准 `keyDown`；`rawKeyDown` 对 Delete 无效。
5. 不要 `canvas.focus()`：会让应用快捷键监听失效；清空焦点用 blur 当前元素即可。
6. 搜索结果必须等"首行缩略图 src 相对搜索前发生变化"再取，否则会拿到上一次搜索的旧结果。
7. 缩略图按几何（先行后列）排序取序号，DOM 顺序与视觉行列不一致。

## 5. 抠图

```bash
python "<skill-dir>/scripts/biorender_cutout.py" \
  --raw-dir "<项目>/_参考/raw" --out-dir "<素材库>" --sheet "<项目>/_参考/assets_sheet.png"
```

中心窗口与放置坐标默认对应 1400×900 窗口、中心 (762,330)；改动放置坐标时用
`--cx/--cy/--half` 同步。坐标换算 K=scale（仿真下 deviceScaleFactor 被直接设为 scale，
不要再乘屏幕 DPR）。抠出后**逐张目视验收**：是目标结构、轮廓完整、无邻接残片、透明边缘干净，
再按素材清单规范登记来源与变换。

## 6. 收尾与回退

- 采集结束关闭隔离浏览器，删除含登录态的隔离 profile 目录；原始截图与对照图留作采集证据。
- BioRender 前端会改版：若面板选择器、缩略图 URL 形式或坐标布局漂移，先用 harness 的
  `eval`/`shot` op 查看真实页面状态再小修，不要盲目重跑整批；无法稳定运行时回退为
  用户手动放入图标、脚本只负责截图与抠图的半自动模式，不要死磕。
