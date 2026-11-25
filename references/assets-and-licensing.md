# 素材、BioRender 与授权

## 素材来源优先级

1. 用户提供且确认可用的素材；
2. 用户有权使用的 BioRender 素材；
3. 开放许可或公共领域素材；
4. 为机制、轮廓、过程节点和符号自绘的 SVG。

不得把 BioRender 当作科学正确性的保证，也不得把“所有元素必须来自 BioRender”作为通用铁律。自绘或开放素材必须记录理由并做同样的科学审查。

## 素材清单

每个素材至少记录：

```json
{
  "asset_id": "stable-local-id",
  "name": "mitochondrion",
  "source": "BioRender / user / open-license / self-drawn",
  "source_id": "platform id or citation",
  "license": "project-specific license or user confirmation",
  "acquired_at": "YYYY-MM-DD",
  "local_file": "relative/path.png",
  "sha256": "content hash",
  "transforms": ["crop transparent margin", "brightness 0.68"],
  "notes": "scientific identity and intended compartment"
}
```

保留原文件，派生文件另存。裁切、去背景、改色、旋转和亮度调整均记录，不覆盖原素材。

## 素材验收

- 确认是目标生物结构，不是同名的整细胞、模板或错误器官。
- 检查透明通道、残片、邻接图标、意外裁切、分辨率和缩放后的清晰度。
- 保持同一图内的光影、饱和度和视角一致；必要时使用有记录的派生版本。
- 检查图标实际可见轮廓，不能只用矩形包围盒判断箭头是否命中。

## 账号与自动化边界

不得把凭据、邮箱、密码、Cookie、浏览器 profile 或 API key 写入技能、脚本或项目日志。

不得自动执行以下操作：

- 未经用户明确授权读取密码并登录账号；经授权时仅通过 `biorender_auth.py` 读取本机私有凭据，且不打印密码；
- 删除云端画布或“看起来无用”的文件；
- 强制结束 Photoshop、浏览器或 Office 进程；
- 使用固定屏幕坐标盲目拖拽；
- 规避平台导出、授权或水印要求；
- 未获用户同意将未发表图片上传到外部服务。

页面自动化只作为经用户明确授权的可选适配器。先验证当前页面和授权状态；遇到验证码、二次验证、配额或删除请求时停止并询问。

需要批量采集画布图标时，使用 `references/biorender-capture.md` 及配套脚本（`scripts/biorender_capture.mjs`、`biorender_capture_run.ps1`、`biorender_cutout.py`）：隔离浏览器、单图标回路、3 倍截图、抠图与清理已固化为可复用流程，不要每次从零摸索 CDP 操作。

## 外部模型看图

上传未发表图片前获得用户同意，遵循最小化上传和日志脱敏。外部模型不是必需的完成条件；经用户同意，可使用本地或全新视觉代理完成独立盲读。服务不可用时记录 `NOT_ASSESSED`，不伪造通过结果。
