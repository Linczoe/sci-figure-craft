# sci-figure-craft 跨 Harness 安装与调用

## 安装

压缩包根目录为 `sci-figure-craft/`，包含独立 `SKILL.md`、通用 Python 脚本、按需参考资料和无项目内容冒烟样例。

- **WorkBuddy**：将文件夹复制到 `~/.workbuddy/skills/sci-figure-craft/`。
- **DSH**：将文件夹复制到 `~/.dsh/skills/sci-figure-craft/`。若已有同名技能，先备份；本包不会自动覆盖旧版。
- **其他 Harness**：放入其技能/指令目录，按 `SKILL.md` 加载工作流；三个核心脚本也可完全脱离 Harness 直接调用。

## 依赖

- Python 3.10+；脚本只使用当前 `python`/`sys.executable`，不绑定特定虚拟环境。
- SVG 渲染：自动发现 Chromium/Edge/Chrome；无浏览器时可安装 `CairoSVG`。
- 图像裁切、透明度检查：建议安装 `Pillow`。
- 核心工作流不需要 Node、CDP、远程模型、API key 或 DSH 工具目录。

可选的 BioRender 采集适配器（仅经用户授权后使用，见 `references/biorender-capture.md`）另需：

- Node 18+（内置 `fetch` 与 `WebSocket`）；
- 可启动的 Edge/Chrome（CDP 远程调试）；
- `Pillow`、`numpy`、`scipy`（抠图）。

## 冒烟验证

```bash
python "<skill-dir>/scripts/render_svg.py" \
  "<skill-dir>/assets/smoke.svg" --output "<tmp>/smoke.png" --scale 2

python "<skill-dir>/scripts/audit_figure.py" \
  "<skill-dir>/assets/smoke.svg" --text-policy no-cjk \
  --check-all-sources --report "<tmp>/smoke-audit.json" --fail-on error

python "<skill-dir>/scripts/make_blind_panels.py" \
  --input "<skill-dir>/assets/smoke.svg" --out-dir "<tmp>/blind" \
  --views "<skill-dir>/assets/smoke_views.json" --scale 2 --seed 1
```

预期：渲染成功，审计 `errors=0`，盲读包包含 1 张整图和 1 张局部图。

## BioRender 凭据（可选）

安装包不包含任何账号或密码。任何 Harness 可导入：

```python
from biorender_auth import load_credentials
email, password, source = load_credentials()
```

凭据解析顺序：

1. `BIORENDER_EMAIL` 与 `BIORENDER_PASSWORD` 环境变量；
2. `BIORENDER_CREDENTIALS_FILE` 指定的 JSON/YAML 文件；
3. `~/.config/sci-figure-craft/biorender.json`。

标准 JSON 格式：

```json
{
  "BIORENDER_EMAIL": "your-account",
  "BIORENDER_PASSWORD": "your-password"
}
```

仅将私有凭据放在本机标准位置，不复制进技能目录、压缩包、日志或审计报告。掩码检查：

```bash
python "<skill-dir>/scripts/biorender_auth.py" --require
```

登录只用于用户明确授权的操作；遇到验证码或二次验证时停止并由用户处理。

需要批量采集画布图标时，按 `references/biorender-capture.md` 操作：`scripts/biorender_capture.mjs`（CDP 批处理）、`biorender_capture_run.ps1`（单图标回路，需 Windows PowerShell；其他平台可按文档手写等价脚本）、`biorender_cutout.py`（RGBA 抠图）。这些均为可选适配器，缺失时按原流程手动取材。

> 提示：若该 `.ps1` 在部分 Windows PowerShell 下中文报错，请保存为 UTF-8 with BOM（包内文件已带 BOM）。
