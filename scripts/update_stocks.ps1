# 每日更新个股：同步 Substack、刷新现价，有变化则提交并推送。
# 由「任务计划程序」里的「宏观研究-更新个股」调用，也可手动运行。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "update_stocks.log"

function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Host $line
}

function Test-ForeignChanges {
    foreach ($line in @(git status --porcelain)) {
        if (-not $line) { continue }
        foreach ($path in (($line.Substring(3) -replace '\\', '/') -split ' -> ')) {
            if ($path -notmatch '^(data/substack/|data/cache/stk_|site/data/stocks\.json)') { return $path }
        }
    }
    return $null
}

try {
    Write-Log "开始更新个股"
    $foreign = Test-ForeignChanges
    if ($foreign) {
        Write-Log "工作区有其他未提交修改（$foreign），跳过本次，避免打断正在进行的编辑"
        exit 0
    }

    git pull --rebase --autostash
    if ($LASTEXITCODE -ne 0) { throw "git pull 失败" }

    $py = Join-Path $root ".venv\Scripts\python.exe"
    $pyLog = Join-Path $logDir "stocks.out"
    & $py -W ignore -m pipeline.stocks *> $pyLog
    $code = $LASTEXITCODE
    Get-Content $pyLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Log $_ }
    if ($code -ne 0) { throw "pipeline.stocks 失败（退出码 $code）" }

    git add -- data/substack site/data/stocks.json
    $caches = Get-ChildItem (Join-Path $root "data\cache\stk_*.csv") -ErrorAction SilentlyContinue
    if ($caches) { git add -- $caches.FullName }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Log "价格和帖子都没有新变化"
        exit 0
    }

    git commit -m "data: 个股自动更新 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    if ($LASTEXITCODE -ne 0) { throw "git commit 失败" }

    git pull --rebase --autostash
    if ($LASTEXITCODE -ne 0) {
        git rebase --abort 2>$null
        throw "推送前 rebase 失败，已保留本地提交，下次运行会重试"
    }
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push 失败" }
    Write-Log "已推送"
} catch {
    Write-Log "失败：$($_.Exception.Message)"
    exit 1
}
