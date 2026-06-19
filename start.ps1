$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RootDir ".venv"
$ServerProcess = $null

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    # 先递归处理子进程，避免浏览器检测等子进程残留。
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-Server {
    if ($null -ne $script:ServerProcess -and -not $script:ServerProcess.HasExited) {
        Write-Host ""
        Write-Host "正在停止 Proxy Checker 服务..."
        Stop-ProcessTree -ProcessId $script:ServerProcess.Id
        $script:ServerProcess.WaitForExit()
    }
}

try {
    Set-Location $RootDir

    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if ($null -eq $PythonCommand) {
        throw "错误：未找到 python 或 py，请先安装 Python 3。"
    }

    if (-not (Test-Path $VenvDir)) {
        Write-Host "创建 Python 虚拟环境：$VenvDir"
        if ($PythonCommand.Name -eq "py.exe" -or $PythonCommand.Name -eq "py") {
            & $PythonCommand.Source -3 -m venv $VenvDir
        }
        else {
            & $PythonCommand.Source -m venv $VenvDir
        }
    }

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        throw "错误：虚拟环境 Python 不存在：$VenvPython"
    }

    Write-Host "安装/更新 Python 依赖..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $RootDir "requirements.txt")
    & $VenvPython -m playwright install chromium

    Write-Host "启动 Proxy Checker 服务..."
    $ServerProcess = Start-Process `
        -FilePath $VenvPython `
        -ArgumentList @((Join-Path $RootDir "server.py")) `
        -WorkingDirectory $RootDir `
        -NoNewWindow `
        -PassThru

    while (-not $ServerProcess.HasExited) {
        Start-Sleep -Milliseconds 300
        $ServerProcess.Refresh()
    }

    exit $ServerProcess.ExitCode
}
finally {
    Stop-Server
}
