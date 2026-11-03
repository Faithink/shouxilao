# Windows 冒烟测试(GitHub Actions 里跑):启动打包好的 exe,走一遍"首次使用"流程,包括点「刷新数据」。
# Windows 默认编码不是 UTF-8,正是 1.5.0 里「刷新后详情页和持仓页打不开」的原因,这里专门复现一遍。
$ErrorActionPreference = "Stop"
$exe = "packaging/build/dist/收息佬/收息佬.exe"
$p = Start-Process $exe -PassThru
Start-Sleep -Seconds 15
$home_ = "$env:APPDATA/收息佬"
$port = (Get-Content "$home_/server.port" -Raw).Trim()
$base = "http://127.0.0.1:$port"
Write-Host "port $port; culture/encoding: $([Console]::OutputEncoding.WebName) / ANSI cp $([System.Text.Encoding]::Default.WebName)"
$fail = @()
function Check($name, [scriptblock]$f) {
    try { $ok = & $f } catch { $ok = $false; Write-Host "  exception: $($_.Exception.Message)" }
    if ($ok) { Write-Host "PASS $name" } else { Write-Host "FAIL $name"; $script:fail += $name }
}
function Get-Utf8($path) {
    $r = Invoke-WebRequest "$base$path" -UseBasicParsing
    return [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
}
Check "首页 200" { (Invoke-WebRequest "$base/" -UseBasicParsing).StatusCode -eq 200 }
Check "版本号" { (Get-Utf8 "/api/version") -match '"version"' }
Check "股票池 50 只" { (Get-Utf8 "/api/pool" | ConvertFrom-Json).stocks.Count -ge 50 }
Check "个股详情(刷新前)" { (Get-Utf8 "/api/stock/600941") -match "中国移动" }
Check "ETF 详情(刷新前)" { (Get-Utf8 "/api/stock/563020") -match "红利低波" }
Check "录入持仓" {
    $body = '{"settings":{},"lots":[{"id":"t1","code":"600941","date":"2026-06-17","price":90,"shares":100}],"sells":[]}'
    (Invoke-WebRequest "$base/api/holdings" -Method Put -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -UseBasicParsing).StatusCode -eq 200
}
Check "读回持仓" { (Get-Utf8 "/api/holdings" | ConvertFrom-Json).lots[0].code -eq "600941" }
Check "二维码" { (Invoke-WebRequest "$base/api/qr?u=http%3A%2F%2F192.168.1.5%3A$port" -UseBasicParsing).StatusCode -eq 200 }

# 点「刷新数据」:全部股票重新采集一遍,最久等 14 分钟
Invoke-WebRequest "$base/api/refresh" -Method Post -UseBasicParsing | Out-Null
$deadline = (Get-Date).AddMinutes(14)
do {
    Start-Sleep -Seconds 10
    $st = Get-Utf8 "/api/status" | ConvertFrom-Json
    Write-Host "refresh: running=$($st.running) $($st.done)/$($st.total)"
} while ($st.running -and (Get-Date) -lt $deadline)
$nerr = @($st.errors.PSObject.Properties).Count
Write-Host "refresh finished, errors: $nerr"
Check "刷新已结束" { -not $st.running }
Check "刷新后:股票池仍可读" { (Get-Utf8 "/api/pool" | ConvertFrom-Json).stocks.Count -ge 50 }
Check "刷新后:个股详情仍可读" { (Get-Utf8 "/api/stock/600941") -match "中国移动" }
Check "刷新后:ETF 详情仍可读" { (Get-Utf8 "/api/stock/563020") -match "红利低波" }
Check "刷新后:持仓仍可读" { (Get-Utf8 "/api/holdings" | ConvertFrom-Json).lots.Count -eq 1 }
Check "刷新写出的详情文件是合法 UTF-8" {
    $bytes = [System.IO.File]::ReadAllBytes("$home_/data/stocks/600941.json")
    $enc = New-Object System.Text.UTF8Encoding($false, $true)
    $null = $enc.GetString($bytes); $true
}
Check "刷新后大部分股票成功(失败数 < 10)" { $nerr -lt 10 }
Stop-Process $p -Force
if ($fail.Count -gt 0) { Write-Host "FAILED: $($fail -join ', ')"; exit 1 }
Write-Host "ALL PASS"
