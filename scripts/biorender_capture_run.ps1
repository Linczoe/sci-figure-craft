# BioRender 单图标采集回路驱动：每步一个独立 node 进程，带超时与重试。
# 每步进程隔离是刻意的：单步 CDP 调用挂死只损失该步，不会拖垮整批。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File biorender_capture_run.ps1 `
#       -Items items.json -RawDir "<项目>\_参考\raw" [-From 0] [-To 20]
#
# items.json 示例（index 为几何排序后的结果序号；可先用 harness 的 search op 截图挑选）：
#   [
#     {"term": "mouse",  "index": 1, "name": "mouse"},
#     {"term": "tablet", "index": 0, "name": "tablet_white"}
#   ]
#
# 单图标回路：delc 清零 → place（失败重试至多 3 次）→ 点空白取消选择 → 3 倍截图 → delc 清零。
# 前置条件与不变量见 references/biorender-capture.md。本脚本不含任何凭据。
param(
  [Parameter(Mandatory = $true)][string]$Items,
  [Parameter(Mandatory = $true)][string]$RawDir,
  [string]$Harness = (Join-Path $PSScriptRoot 'biorender_capture.mjs'),
  [int]$From = 0,
  [int]$To = -1,
  [int]$Cx = 762,
  [int]$Cy = 330
)
$node = (Get-Command node).Source
$s = Join-Path $RawDir '_step.json'
New-Item -ItemType Directory -Force $RawDir | Out-Null
$enc = New-Object System.Text.UTF8Encoding $false
$itemList = @(Get-Content -Raw -Encoding UTF8 $Items | ConvertFrom-Json)
if ($To -lt 0) { $To = $itemList.Count - 1 }

function RunSteps($steps, [int]$timeoutSec = 75) {
  [IO.File]::WriteAllText($s, (ConvertTo-Json -InputObject @($steps) -Depth 6), $enc)
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $node; $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
  $psi.Arguments = '"' + $Harness + '" "' + $s + '"'
  $proc = [System.Diagnostics.Process]::Start($psi)
  $ot = $proc.StandardOutput.ReadToEndAsync(); $et = $proc.StandardError.ReadToEndAsync()
  if (-not $proc.WaitForExit($timeoutSec * 1000)) { try { $proc.Kill() } catch {}; Start-Sleep -Milliseconds 500; return "TIMEOUT" }
  $txt = $ot.Result.Trim()
  if ($txt -eq '') { $txt = 'ERR ' + $et.Result.Trim().Split("`n")[0] }
  return $txt
}

for ($i = $From; $i -le $To; $i++) {
  $it = $itemList[$i]
  $log = @()
  $log += RunSteps @(@{ op = 'delc' }) 160
  $placed = $false
  for ($try = 1; $try -le 3 -and -not $placed; $try++) {
    $r = RunSteps @(@{ op = 'place'; term = $it.term; index = $it.index; cx = $Cx; cy = $Cy }) 170
    $log += $r
    if ($r -match '(^|\n)placed ') { $placed = $true } elseif ($r -like '*NOT_PLACED*' -or $r -eq 'TIMEOUT') { $log += RunSteps @(@{ op = 'delc' }) 160 }
  }
  if ($placed) {
    # 点画布空白处取消选择（避免蓝色选择框混入截图），再 3 倍截图
    $log += RunSteps @(@{ op = 'click'; x = $Cx; y = ($Cy + 215) }, @{ op = 'sleep'; ms = 900 }, @{ op = 'shot'; path = (Join-Path $RawDir ($it.name + '.png')); scale = 3 }) 60
    $log += RunSteps @(@{ op = 'delc' }) 160
  }
  "[$i] $($it.name) :: " + ($log -join ' | ')
}
