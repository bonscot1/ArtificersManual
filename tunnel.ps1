# Expose the running site to the internet through a Cloudflare quick tunnel (no account needed).
# Start the server first (run.ps1), set table_password + dm_password in settings.json, then run this.
$port = 8000
if (Test-Path "$PSScriptRoot\settings.json") {
    $s = Get-Content "$PSScriptRoot\settings.json" | ConvertFrom-Json
    if ($s.port) { $port = $s.port }
    if (-not $s.table_password -or -not $s.dm_password) {
        Write-Host "Set table_password and dm_password in settings.json before exposing the site." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "No settings.json - copy settings.example.json and set both passwords first." -ForegroundColor Yellow
    exit 1
}
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared not found. Install it once with:  winget install Cloudflare.cloudflared" -ForegroundColor Yellow
    exit 1
}
Write-Host "Tunnelling http://localhost:$port - share the https://...trycloudflare.com URL below. Ctrl+C to stop."
cloudflared tunnel --url "http://localhost:$port"
