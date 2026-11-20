# Project-local uv; bypass stale Clash proxy settings for this process only.
$previousNoProxy = $env:NO_PROXY
try {
    $env:NO_PROXY = '*'
    Push-Location $PSScriptRoot
    try {
        & "$PSScriptRoot/.tools/uv-package/bin/uv.exe" @args
        $result = $LASTEXITCODE
    } finally { Pop-Location }
} finally { $env:NO_PROXY = $previousNoProxy }
exit $result
