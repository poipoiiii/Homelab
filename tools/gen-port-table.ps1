<#
  生成 AGENTS.md 第 4 节的服务/端口表。
  直接扫描 homelab/**/docker-compose.yml，不依赖 docker 或 yaml 模块。

  用法（Windows PowerShell / pwsh）：
      pwsh -NoProfile -File tools/gen-port-table.ps1
  把输出整段贴进 AGENTS.md 的「服务与端口（自动生成）」章节即可。
#>
[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$script:Rows = @()

function Clean-Value([string]$value) {
    return ($value -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")
}

function Add-Row($stack, $current) {
    if (-not $current) { return }
    $script:Rows += [pscustomobject]@{
        Stack   = $stack
        Service = $current.Name
        Image   = $current.Image
        Ports   = ($current.Ports -join '<br>')
        Volumes = ($current.Volumes -join '<br>')
    }
}

$files = Get-ChildItem -Path (Join-Path $Root 'homelab') -Recurse -Filter 'docker-compose.yml' |
    Sort-Object FullName

foreach ($file in $files) {
    $stack = Split-Path -Leaf (Split-Path -Parent $file.FullName)
    $inServices = $false
    $current = $null
    $section = ''

    foreach ($line in (Get-Content -LiteralPath $file.FullName -Encoding UTF8)) {
        if ($line -match '^services:\s*$') { $inServices = $true; continue }
        if (-not $inServices) { continue }
        if ($line -match '^\S') { break }

        if ($line -match '^  ([A-Za-z0-9_.-]+):\s*$') {
            Add-Row $stack $current
            $current = @{ Name = $Matches[1]; Image = ''; Ports = @(); Volumes = @() }
            $section = ''
            continue
        }
        if (-not $current) { continue }

        if ($line -match '^    image:\s*(.+)$') {
            $current.Image = Clean-Value $Matches[1]
            $section = ''
        } elseif ($line -match '^    ports:\s*$') {
            $section = 'ports'
        } elseif ($line -match '^    volumes:\s*$') {
            $section = 'volumes'
        } elseif ($line -match '^    [A-Za-z0-9_.-]+:') {
            $section = ''
        } elseif ($line -match '^      -\s*(.+)$') {
            if ($section -eq 'ports') {
                $current.Ports += ('`' + (Clean-Value $Matches[1]) + '`')
            } elseif ($section -eq 'volumes') {
                $current.Volumes += ('`' + (Clean-Value $Matches[1]) + '`')
            }
        }
    }
    Add-Row $stack $current
}

Write-Output '| 堆栈 | 服务 | 镜像 | 端口 | 挂载 |'
Write-Output '| --- | --- | --- | --- | --- |'
foreach ($row in ($script:Rows | Sort-Object Stack, Service)) {
    $image = if ($row.Image) { '`' + $row.Image + '`' } else { '—' }
    $ports = if ($row.Ports) { $row.Ports } else { '—' }
    $volumes = if ($row.Volumes) { $row.Volumes } else { '—' }
    Write-Output ('| `{0}` | `{1}` | {2} | {3} | {4} |' -f $row.Stack, $row.Service, $image, $ports, $volumes)
}
