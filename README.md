# sci-figure-craft

科研机制图创作与审查技能（Agent Skill）：把综述/论文正文变成可复核的机制图，而不是"画得像机制图"。

A skill for building and auditing scientific figures — turn review/paper evidence into mechanism figures that can be traced, audited and blind-read.

## 它解决什么问题

机制图最常见的失败不是画得丑，而是：把相关画成因果、把推断画成实证、箭头指到空白、文字列表冒充机制网络、图上一堆句子没人读得下去。

本技能用一条固定工作流把这些错误挡在交付之前：

1. **验收清单**：原始要求、科学主干、非目标、交付物、验收方式；
2. **证据矩阵**：一句话论点、关系类型、每条机制边的位置/上下游/方向/出处；
3. **空间网络设计**：区室与细胞器 → 状态变化 → 分子输入输出 → 跨区室连接 → 细胞命运 → 组织结局；
4. **自描述 SVG**：每个关键元素带 `id`、`data-kind`、`data-source-id/-target-id`、`data-relation`，机械审计可读；
5. **机械审计**：唯一 ID、真实路径起止、声明目标、重复连接、断链、文字压叠、图例一致性、可见箭头头；
6. **独立盲读**：中性命名的盲读包交给全新视觉代理，只给图片和通用问题，揭盲后逐条比对；
7. **评分回归与交付**：同尺寸同配置的新旧评分对比，`PASS` / `BLOCKED` / `NOT_ASSESSED` 如实标注。

审计器只证明"声明、几何与引用一致"，科学正确性必须回原文核对——这一点写在技能里，不允许用"审计全绿"冒充科学正确。

## 安装

技能是纯文件，无安装器、无运行时依赖锁定。解压后把 `sci-figure-craft/` 放进目标 harness 的技能目录：

- **DeepSeek Harness (DSH)**：`~/.dsh/skills/sci-figure-craft/`
- **WorkBuddy**：`~/.workbuddy/skills/sci-figure-craft/`
- **Claude Code / 其他 Agent**：放入其技能或指令目录，Agent 读取 `SKILL.md` 即可；核心脚本也可脱离 harness 直接命令行调用。

通用安装说明见 [INSTALL.md](INSTALL.md)。

## 依赖

- Python 3.10+；SVG 渲染自动发现 Chromium/Edge/Chrome，无浏览器时可装 `CairoSVG`；
- 图像裁切与透明度检查建议 `Pillow`；
- 核心工作流不需要 Node、CDP、远程模型、API key。

可选 BioRender 采集适配器另需 Node 18+、CDP 浏览器、`Pillow`/`numpy`/`scipy`，详见 `references/biorender-capture.md`。

## 冒烟验证

```bash
python "sci-figure-craft/scripts/render_svg.py" \
  "sci-figure-craft/assets/smoke.svg" --output "/tmp/smoke.png" --scale 2

python "sci-figure-craft/scripts/audit_figure.py" \
  "sci-figure-craft/assets/smoke.svg" --text-policy no-cjk \
  --check-all-sources --report "/tmp/smoke-audit.json" --fail-on error

python "sci-figure-craft/scripts/make_blind_panels.py" \
  --input "sci-figure-craft/assets/smoke.svg" --out-dir "/tmp/blind" \
  --views "sci-figure-craft/assets/smoke_views.json" --scale 2 --seed 1
```

预期：渲染成功，审计 `errors=0`，盲读包含 1 张整图 + 1 张局部图。

## 目录结构

```text
sci-figure-craft/
  SKILL.md                       # 主工作流（Agent 入口）
  INSTALL.md                     # 安装、依赖、凭据
  assets/                        # 无项目内容的冒烟样例
  references/                    # 按需加载：设计语法、审计盲读、素材授权、交付评分、BioRender 采集
  scripts/
    render_svg.py                # SVG → PNG（Chromium/CairoSVG）
    audit_figure.py              # 机械与语义声明审计
    make_blind_panels.py         # 中性命名盲读包
    biorender_auth.py            # 凭据读取（仅脱敏输出）
    biorender_capture.mjs        # 可选：BioRender 画布批量采集（CDP）
    biorender_capture_run.ps1    # 可选：单图标采集回路（Windows）
    biorender_cutout.py          # 可选：截图抠图为 RGBA
```

## 授权与边界

- 默认不写入任何凭据；BioRender 凭据只从本机私有文件或环境变量读取，不回显、不落盘、不进日志。
- 页面自动化仅作为经用户明确授权的可选适配器；遇到验证码、二次验证、配额或删除请求时停止并询问，不规避平台授权或水印限制。
- 不删除云端文件、不强制结束用户程序、未获同意不上传未发表图片到外部服务。

## License

[MIT](LICENSE)
