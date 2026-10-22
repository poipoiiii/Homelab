<#
  开机自启控制台 —— 本地可视化开关面板
  ------------------------------------------------------------------
  只监听 http://localhost:<Port>/，不对外网开放。
  “禁用”= 把条目移出启动位置并备份到 .\backup\，随时可恢复，不删除程序。
  改注册表本机项 / 服务 / 计划任务需要管理员权限，脚本默认自动提权。

  用法：
    双击 start-panel.cmd（推荐），或
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\Start-Panel.ps1
    pwsh -File .\Start-Panel.ps1 -NoElevate   # 不提权，只读/HKCU 实验用
#>
[CmdletBinding()]
param(
    [int]$Port = 8360,
    [switch]$NoElevate
)

$ErrorActionPreference = 'Stop'
$script:Root      = $PSScriptRoot
$script:BackupDir = Join-Path $PSScriptRoot 'backup'
$script:IsAdmin   = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
                        [Security.Principal.WindowsBuiltInRole]::Administrator)

# ── 自动提权 ──────────────────────────────────────────────────────
if (-not $script:IsAdmin -and -not $NoElevate) {
    try {
        $exe = (Get-Process -Id $PID).Path
        Start-Process -FilePath $exe -Verb RunAs -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', ('"{0}"' -f $PSCommandPath),
            '-Port', $Port
        )
        return
    } catch {
        Write-Host '提权被取消，将以当前权限运行（服务/本机注册表项不可改）。' -ForegroundColor Yellow
    }
}

New-Item -ItemType Directory -Force -Path $script:BackupDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $script:BackupDir 'startup') | Out-Null

# ── 清单：只管理这里列出的条目 ────────────────────────────────────
# advice: off=建议关闭 / optional=按需 / keep=建议保留
# mode:   manual=关闭时只降为“手动启动”
$script:Defs = @(
    # 注册表 Run · 当前用户
    @{ id='run-user-taptap';     type='run'; scope='HKCU';   match='^TapTap$';                   label='TapTap';               usage='游戏平台（用户级，与机器级重复）'; advice='off' }
    @{ id='run-user-quark';      type='run'; scope='HKCU';   match='^quark$';                    label='夸克网盘';             usage='网盘客户端常驻';                   advice='off' }
    @{ id='run-user-quarkupd';   type='run'; scope='HKCU';   match='^QuarkUpdaterTaskUser';      label='夸克更新器';           usage='夸克后台更新进程';                 advice='off' }
    @{ id='run-user-battlenet';  type='run'; scope='HKCU';   match='^Battle\.net$';              label='Battle.net';           usage='暴雪战网';                         advice='off' }
    @{ id='run-user-steam';      type='run'; scope='HKCU';   match='^Steam$';                    label='Steam';                usage='游戏平台（-silent 后台常驻）';     advice='off' }
    @{ id='run-user-qqmusic';    type='run'; scope='HKCU';   match='^QQMusic$';                  label='QQ 音乐';              usage='后台常驻';                         advice='off' }
    @{ id='run-user-edge';       type='run'; scope='HKCU';   match='^MicrosoftEdgeAutoLaunch';   label='Edge 后台预热';        usage='浏览器开机预启动';                 advice='off' }
    @{ id='run-user-filmora';    type='run'; scope='HKCU';   match='^FilmoraTray$';              label='Filmora 托盘';         usage='万兴喵影托盘';                     advice='off' }
    @{ id='run-user-onedrive';   type='run'; scope='HKCU';   match='^OneDrive$';                 label='OneDrive';             usage='云盘同步（不用可关）';             advice='optional' }
    @{ id='run-user-clashwin';   type='run'; scope='HKCU';   match='^com\.lbyczf\.clashwin$';    label='Clash for Windows';    usage='代理客户端';                       advice='optional' }
    @{ id='run-user-cordc';      type='run'; scope='HKCU';   match='^CordC$';                    label='Clash Verge (CordC)';  usage='代理客户端';                       advice='optional' }
    @{ id='run-user-utools';     type='run'; scope='HKCU';   match='^org\.yuanli\.utools$';      label='uTools';               usage='常用工具箱';                       advice='keep' }
    @{ id='run-user-weixin';     type='run'; scope='HKCU';   match='^Weixin$';                   label='微信';                 usage='常用即时通讯';                     advice='keep' }
    @{ id='run-user-workbuddy';  type='run'; scope='HKCU';   match='^WorkBuddy\.WorkBuddy$';     label='WorkBuddy';            usage='AI 编码助手';                      advice='keep' }
    @{ id='run-user-amdanr';     type='run'; scope='HKCU';   match='^AMDNoiseSuppression$';      label='AMD 降噪';             usage='声卡驱动组件';                     advice='keep'; protected=$true }
    @{ id='run-user-ctfmon';     type='run'; scope='HKCU';   match='^ctfmon$';                   label='ctfmon 输入法';        usage='系统输入法';                       advice='keep'; protected=$true }

    # 注册表 Run · 本机
    @{ id='run-machine-taptap';   type='run'; scope='HKLM';   match='^TapTap$';                    label='TapTap';              usage='游戏平台（机器级重复项）';   advice='off' }
    @{ id='run-machine-musehub';  type='run'; scope='HKLM';   match='^MuseHub$';                   label='MuseHub';             usage='音乐软件，极少用';           advice='off' }
    @{ id='run-machine-leigod';   type='run'; scope='HKLM32'; match='^electron\.app\.leigod$';     label='雷神加速器';          usage='游戏加速器后台';             advice='off' }
    @{ id='run-machine-wshelper'; type='run'; scope='HKLM32'; match='^Wondershare Helper Compact'; label='万兴 Helper';         usage='万兴后台助手';               advice='off' }
    @{ id='run-machine-pico';     type='run'; scope='HKLM32'; match='^PICOConnect$';               label='PICO Connect';        usage='VR 串流（无设备可关）';      advice='off' }
    @{ id='run-machine-security'; type='run'; scope='HKLM';   match='^SecurityHealth$';            label='Windows 安全中心';    usage='系统必需';                   advice='keep'; protected=$true }
    @{ id='run-machine-rtk';      type='run'; scope='HKLM';   match='^RtkAudUService$';            label='Realtek 音频服务';    usage='声卡驱动组件';               advice='keep'; protected=$true }

    # 启动文件夹
    @{ id='startup-rustdesk'; type='startup'; match='RustDesk Tray.lnk'; label='RustDesk Tray'; usage='远程桌面，按需'; advice='optional' }

    # 计划任务
    @{ id='task-wps-logon'; type='task'; task='WpsUpdateLogonTask_USER'; label='WPS 更新（登录触发）'; usage='WPS 后台更新'; advice='off' }
    @{ id='task-wps-timer'; type='task'; task='WpsUpdateTask_USER';      label='WPS 更新（定时）';     usage='WPS 后台更新'; advice='off' }

    # 自动启动服务
    @{ id='svc-wondershare'; type='service'; service='NativePushService';       label='Wondershare 推送'; usage='万兴推送服务';       advice='off' }
    @{ id='svc-pcmanager';   type='service'; service='PCManager Service Store'; label='Microsoft PC Manager'; usage='微软电脑管家';  advice='off' }
    @{ id='svc-pico';        type='service'; service='ps_service';              label='PICO Streaming';   usage='VR 串流服务';        advice='off' }
    @{ id='svc-msi-center';  type='service'; service='MSI_Center_Service';      label='MSI Center';       usage='微星控制中心';       advice='off' }
    @{ id='svc-msi-case';    type='service'; service='MSI_Case_Service';        label='MSI Case';         usage='微星机箱灯控';       advice='off' }
    @{ id='svc-mystic';      type='service'; service='Mystic_Light_Service';    label='Mystic Light';     usage='微星灯效服务';       advice='off' }
    @{ id='svc-lightkeeper'; type='service'; service='LightKeeperService';      label='LightKeeper';      usage='微星灯效守护';       advice='off' }
    @{ id='svc-cordc';       type='service'; service='CordCHelperService';      label='CordC Helper';     usage='Clash Verge 辅助';   advice='optional' }
    @{ id='svc-sangfor-pw';  type='service'; service='SangforPWEx';             label='深信服 VPN 防护';  usage='工作 VPN，按需';     advice='optional' }
    @{ id='svc-sangfor-sp';  type='service'; service='SangforSP';               label='SangforSP';        usage='深信服组件，按需';   advice='optional' }
    @{ id='svc-rustdesk';    type='service'; service='RustDesk';                label='RustDesk 服务';    usage='远程控制，按需';     advice='optional' }
    @{ id='svc-zerotier';    type='service'; service='ZeroTierOneService';      label='ZeroTier One';     usage='虚拟组网，按需';     advice='optional' }
    @{ id='svc-wsl';         type='service'; service='WSLService';              label='WSL 服务';         usage='关闭只降为「手动」，不影响 wsl'; advice='optional'; mode='manual' }

    # 系统策略
    @{ id='sys-windows-update'; type='wupdate'; label='Windows 自动更新'; usage='关闭后不自动下载/安装，也不会自动重启'; advice='optional' }
)

# ── 注册表 / 文件夹 / 服务 / 任务 的读写 ──────────────────────────
function Get-RunKeyPath([string]$scope) {
    switch ($scope) {
        'HKCU'   { 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' }
        'HKLM'   { 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' }
        'HKLM32' { 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run' }
    }
}

function Resolve-RunValue([string]$scope, [string]$pattern) {
    $path = Get-RunKeyPath $scope
    $key  = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if (-not $key) { return $null }
    foreach ($n in $key.GetValueNames()) {
        if ($n -match $pattern) {
            return @{
                Name  = $n
                Value = [string]$key.GetValue($n)
                Kind  = [string]$key.GetValueKind($n)
                Path  = $path
            }
        }
    }
    return $null
}

function Get-StartupDirs {
    @(
        @{ Scope = 'user';   Dir = [Environment]::GetFolderPath('Startup') }
        @{ Scope = 'common'; Dir = [Environment]::GetFolderPath('CommonStartup') }
    )
}

function Resolve-StartupFile([string]$pattern) {
    foreach ($d in Get-StartupDirs) {
        $f = Get-Item -LiteralPath (Join-Path $d.Dir $pattern) -ErrorAction SilentlyContinue
        if ($f) { return @{ Scope = $d.Scope; Dir = $d.Dir; File = $f.FullName; Name = $f.Name } }
    }
    return $null
}

function Get-StartupBackupFile([string]$name) {
    Get-ChildItem -Path (Join-Path $script:BackupDir 'startup') -Recurse -Filter $name -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Read-RunBackup {
    $f = Join-Path $script:BackupDir 'run.json'
    if (Test-Path -LiteralPath $f) {
        return (Get-Content -LiteralPath $f -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable)
    }
    return @{}
}

function Save-RunBackup($map) {
    $f = Join-Path $script:BackupDir 'run.json'
    $map | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $f -Encoding utf8
}

function Can-Edit($d) {
    if ($script:IsAdmin) { return $true }
    if ($d.type -eq 'run' -and $d.scope -eq 'HKCU') { return $true }
    if ($d.type -eq 'startup') { return $false }
    return $false
}

# ── 读取单项当前状态 ──────────────────────────────────────────────
function Get-DefState($d) {
    $exists = $false; $enabled = $false; $detail = ''; $meta = ''

    switch ($d.type) {
        'run' {
            $cur = Resolve-RunValue $d.scope $d.match
            if ($cur) {
                $exists = $true; $enabled = $true; $detail = $cur.Value; $meta = $cur.Name
            } else {
                $bk = Read-RunBackup
                foreach ($k in $bk.Keys) {
                    if ($k -like ("{0}|*" -f $d.scope) -and ($k.Split('|')[1] -match $d.match)) {
                        $exists = $true; $enabled = $false
                        $detail = $bk[$k].Value; $meta = $k.Split('|')[1]
                        break
                    }
                }
                if (-not $exists) { $detail = '未在注册表中找到' }
            }
        }
        'startup' {
            $cur = Resolve-StartupFile $d.match
            if ($cur) {
                $exists = $true; $enabled = $true; $detail = $cur.File
                $meta = if ($cur.Scope -eq 'common') { '所有用户' } else { '当前用户' }
            } else {
                $bk = Get-StartupBackupFile $d.match
                if ($bk) { $exists = $true; $enabled = $false; $detail = $bk.FullName }
                else { $detail = '启动文件夹中未找到' }
            }
        }
        'service' {
            $svc = Get-Service -Name $d.service -ErrorAction SilentlyContinue
            if ($svc) {
                $exists = $true
                $enabled = ($svc.StartType -ne 'Disabled' -and $svc.StartType -ne 'Manual')
                $wmi = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $d.service) -ErrorAction SilentlyContinue
                $detail = if ($wmi) { $wmi.PathName } else { '' }
                $meta = '启动类型：{0} · 状态：{1}' -f $svc.StartType, $svc.Status
            } else {
                $detail = '服务不存在'
            }
        }
        'task' {
            $t = Get-ScheduledTask -TaskPath '\' -TaskName $d.task -ErrorAction SilentlyContinue
            if ($t) {
                $exists = $true
                $enabled = ($t.State -ne 'Disabled')
                $meta = '状态：{0}' -f $t.State
                $detail = '\' + $d.task
            } else {
                $detail = '计划任务不存在'
            }
        }
        'wupdate' {
            $exists = $true
            $pv     = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' -ErrorAction SilentlyContinue
            $noAuto = ($pv -and $pv.NoAutoUpdate -eq 1)
            $wu     = Get-Service -Name wuauserv -ErrorAction SilentlyContinue
            $uso    = Get-Service -Name UsoSvc  -ErrorAction SilentlyContinue
            $svcOff = (($wu -and $wu.StartType -eq 'Disabled') -or ($uso -and $uso.StartType -eq 'Disabled'))
            $enabled = -not ($noAuto -or $svcOff)
            $meta = '策略：{0} · wuauserv：{1} · UsoSvc：{2}' -f `
                $(if ($noAuto) { '已关闭自动更新' } else { '默认' }),
                $(if ($wu) { $wu.StartType } else { '缺失' }),
                $(if ($uso) { $uso.StartType } else { '缺失' })
            $detail = 'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU + 服务 wuauserv / UsoSvc'
        }
    }

    @{ Exists = $exists; Enabled = $enabled; Detail = $detail; Meta = $meta }
}

function Get-Items {
    $list = foreach ($d in $script:Defs) {
        $s = Get-DefState $d
        [ordered]@{
            id        = $d.id
            group     = if ($d.type -eq 'run') { if ($d.scope -eq 'HKCU') { 'run-user' } else { 'run-machine' } } elseif ($d.type -eq 'wupdate') { 'system' } else { $d.type }
            label     = $d.label
            usage     = $d.usage
            advice    = $d.advice
            protected = [bool]$d.protected
            mode      = if ($d.mode) { $d.mode } else { 'toggle' }
            exists    = $s.Exists
            enabled   = $s.Enabled
            detail    = $s.Detail
            meta      = $s.Meta
            editable  = (Can-Edit $d)
        }
    }
    return @($list)
}

# ── 执行开关 ──────────────────────────────────────────────────────
function Set-DefState($d, [bool]$enable) {
    if (-not (Can-Edit $d)) { throw '需要管理员权限才能修改这一项' }

    switch ($d.type) {
        'run' {
            $path = Get-RunKeyPath $d.scope
            if ($enable) {
                $bk = Read-RunBackup
                $hit = $null
                foreach ($k in $bk.Keys) {
                    if ($k -like ("{0}|*" -f $d.scope) -and ($k.Split('|')[1] -match $d.match)) { $hit = $k; break }
                }
                if (-not $hit) { throw '找不到备份，无法恢复（可能当初不是用本面板关闭的）' }
                if (-not (Test-Path -LiteralPath $path)) { New-Item -Path $path -Force | Out-Null }
                $name = $hit.Split('|')[1]
                New-ItemProperty -LiteralPath $path -Name $name -Value $bk[$hit].Value `
                    -PropertyType $bk[$hit].Kind -Force | Out-Null
                $bk.Remove($hit); Save-RunBackup $bk
                return '已恢复到注册表启动项'
            } else {
                $cur = Resolve-RunValue $d.scope $d.match
                if (-not $cur) { throw '该启动项当前不存在' }
                $bk = Read-RunBackup
                $bk["{0}|{1}" -f $d.scope, $cur.Name] = @{ Value = $cur.Value; Kind = $cur.Kind }
                Save-RunBackup $bk
                Remove-ItemProperty -LiteralPath $path -Name $cur.Name
                return '已移出启动项并备份'
            }
        }
        'startup' {
            if ($enable) {
                $bk = Get-StartupBackupFile $d.match
                if (-not $bk) { throw '找不到备份，无法恢复' }
                $scopeName = Split-Path -Leaf $bk.DirectoryName
                $target = if ($scopeName -eq 'common') { [Environment]::GetFolderPath('CommonStartup') }
                          else { [Environment]::GetFolderPath('Startup') }
                Move-Item -LiteralPath $bk.FullName -Destination (Join-Path $target $bk.Name) -Force
                return '已放回启动文件夹'
            } else {
                $cur = Resolve-StartupFile $d.match
                if (-not $cur) { throw '启动文件夹中找不到该项' }
                $dest = Join-Path $script:BackupDir ('startup\' + $cur.Scope)
                New-Item -ItemType Directory -Force -Path $dest | Out-Null
                Move-Item -LiteralPath $cur.File -Destination (Join-Path $dest $cur.Name) -Force
                return '已移出启动文件夹并备份'
            }
        }
        'service' {
            $svc = Get-Service -Name $d.service -ErrorAction Stop
            if ($enable) {
                Set-Service -Name $d.service -StartupType Automatic
                return '启动类型已设为「自动」（下次开机生效）'
            } else {
                if ($d.mode -eq 'manual') {
                    Set-Service -Name $d.service -StartupType Manual
                    return '启动类型已降为「手动」，服务本身未停止'
                }
                Stop-Service -Name $d.service -Force -ErrorAction SilentlyContinue
                Set-Service -Name $d.service -StartupType Disabled
                return '服务已停止并禁用'
            }
        }
        'task' {
            if ($enable) {
                Enable-ScheduledTask -TaskPath '\' -TaskName $d.task | Out-Null
                return '计划任务已启用'
            } else {
                Disable-ScheduledTask -TaskPath '\' -TaskName $d.task | Out-Null
                return '计划任务已禁用'
            }
        }
        'wupdate' {
            $au = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
            if ($enable) {
                if (Test-Path -LiteralPath $au) {
                    Remove-ItemProperty -LiteralPath $au -Name NoAutoUpdate -ErrorAction SilentlyContinue
                    Remove-ItemProperty -LiteralPath $au -Name NoAutoRebootWithLoggedOnUsers -ErrorAction SilentlyContinue
                }
                Set-Service -Name wuauserv -StartupType Manual
                Set-Service -Name UsoSvc  -StartupType Automatic
                Start-Service -Name UsoSvc -ErrorAction SilentlyContinue
                return '已恢复 Windows 更新（策略已删除，服务恢复默认）'
            } else {
                New-Item -Path $au -Force | Out-Null
                New-ItemProperty -LiteralPath $au -Name NoAutoUpdate -Value 1 -PropertyType DWord -Force | Out-Null
                New-ItemProperty -LiteralPath $au -Name NoAutoRebootWithLoggedOnUsers -Value 1 -PropertyType DWord -Force | Out-Null
                Stop-Service -Name UsoSvc -Force -ErrorAction SilentlyContinue
                Stop-Service -Name wuauserv -Force -ErrorAction SilentlyContinue
                Set-Service -Name wuauserv -StartupType Disabled
                Set-Service -Name UsoSvc  -StartupType Disabled
                return '已关闭自动更新并停止 wuauserv / UsoSvc（可随时恢复）'
            }
        }
    }
}

# ── HTTP ──────────────────────────────────────────────────────────
function Send-Json($ctx, $obj, [int]$code = 200) {
    $json  = $obj | ConvertTo-Json -Depth 8 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $ctx.Response.StatusCode = $code
    $ctx.Response.ContentType = 'application/json; charset=utf-8'
    $ctx.Response.Headers['Cache-Control'] = 'no-store'
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.Close()
}

function Send-File($ctx, [string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        $ctx.Response.StatusCode = 404; $ctx.Response.Close(); return
    }
    $bytes = [IO.File]::ReadAllBytes($path)
    $ctx.Response.StatusCode = 200
    $ctx.Response.ContentType = 'text/html; charset=utf-8'
    $ctx.Response.Headers['Cache-Control'] = 'no-store'
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.Close()
}

$listener = [System.Net.HttpListener]::new()
$prefix   = "http://localhost:$Port/"
$listener.Prefixes.Add($prefix)
try {
    $listener.Start()
} catch {
    Write-Host ("端口 {0} 无法监听：{1}" -f $Port, $_.Exception.Message) -ForegroundColor Red
    return
}

Write-Host ''
Write-Host '  开机自启控制台' -ForegroundColor Cyan
Write-Host ("  地址   : http://localhost:{0}/" -f $Port)
Write-Host ("  权限   : {0}" -f $(if ($script:IsAdmin) { '管理员（可改服务/计划任务）' } else { '普通用户（仅当前用户注册表项可改）' }))
Write-Host ("  备份   : {0}" -f $script:BackupDir)
Write-Host '  关闭   : 在本窗口按 Ctrl+C，或页面右上角「退出面板」'
Write-Host ''

while ($listener.IsListening) {
    try { $ctx = $listener.GetContext() } catch { break }
    $req  = $ctx.Request
    $path = $req.Url.AbsolutePath
    $verb = $req.HttpMethod

    try {
        if ($verb -eq 'GET' -and ($path -eq '/' -or $path -eq '/index.html')) {
            Send-File $ctx (Join-Path $script:Root 'ui.html')
            continue
        }
        if ($verb -eq 'GET' -and $path -eq '/api/state') {
            $items = Get-Items
            Send-Json $ctx ([ordered]@{
                ok        = $true
                admin     = $script:IsAdmin
                port      = $Port
                backupDir = $script:BackupDir
                items     = $items
            })
            continue
        }
        if ($verb -eq 'POST' -and $path -eq '/api/item') {
            $reader = [IO.StreamReader]::new($req.InputStream, [Text.Encoding]::UTF8)
            $body   = $reader.ReadToEnd()
            $reader.Dispose()
            $data = $body | ConvertFrom-Json -AsHashtable
            $def  = $script:Defs | Where-Object { $_.id -eq $data.id } | Select-Object -First 1
            if (-not $def) { Send-Json $ctx @{ ok = $false; error = '未知条目' } 400; continue }
            $msg = Set-DefState $def ([bool]$data.enabled)
            Write-Host ("  [改] {0} -> {1}：{2}" -f $def.label, $(if ($data.enabled) { '启用' } else { '禁用' }), $msg) -ForegroundColor DarkGray
            Send-Json $ctx @{ ok = $true; message = $msg; items = (Get-Items) }
            continue
        }
        if ($verb -eq 'POST' -and $path -eq '/api/bulk') {
            $reader = [IO.StreamReader]::new($req.InputStream, [Text.Encoding]::UTF8)
            $body   = $reader.ReadToEnd()
            $reader.Dispose()
            $data = $body | ConvertFrom-Json -AsHashtable
            $done = 0; $errors = @()
            foreach ($id in @($data.ids)) {
                $def = $script:Defs | Where-Object { $_.id -eq $id } | Select-Object -First 1
                if (-not $def) { continue }
                try { Set-DefState $def ([bool]$data.enabled) | Out-Null; $done++ }
                catch { $errors += ('{0}：{1}' -f $def.label, $_.Exception.Message) }
            }
            Write-Host ("  [批] 已处理 {0} 项，失败 {1} 项" -f $done, $errors.Count) -ForegroundColor DarkGray
            Send-Json $ctx @{ ok = $true; done = $done; errors = $errors; items = (Get-Items) }
            continue
        }
        if ($verb -eq 'POST' -and $path -eq '/api/restore-all') {
            $done = 0; $errors = @()
            foreach ($def in $script:Defs) {
                $s = Get-DefState $def
                if (-not $s.Exists -or $s.Enabled) { continue }
                try { Set-DefState $def $true | Out-Null; $done++ }
                catch { $errors += ('{0}：{1}' -f $def.label, $_.Exception.Message) }
            }
            Write-Host ("  [恢复] 已恢复 {0} 项" -f $done) -ForegroundColor DarkGray
            Send-Json $ctx @{ ok = $true; done = $done; errors = $errors; items = (Get-Items) }
            continue
        }
        if ($verb -eq 'POST' -and $path -eq '/api/quit') {
            Send-Json $ctx @{ ok = $true }
            Start-Sleep -Milliseconds 200
            break
        }
        if ($path -eq '/favicon.ico') { $ctx.Response.StatusCode = 204; $ctx.Response.Close(); continue }

        Send-Json $ctx @{ ok = $false; error = 'not found' } 404
    } catch {
        try { Send-Json $ctx @{ ok = $false; error = $_.Exception.Message } 500 } catch { }
    }
}

$listener.Stop()
$listener.Close()
Write-Host '面板已退出。' -ForegroundColor DarkGray
