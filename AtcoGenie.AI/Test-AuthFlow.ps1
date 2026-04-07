# PowerShell Script - Full E2E Test: Auth + Chat
$ErrorActionPreference = "Stop"

$dotNetUrl = "http://localhost:5256/api/auth/token"
$pythonAuthUrl = "http://localhost:8000/api/auth/test"
$pythonChatUrl = "http://localhost:8000/api/chat/"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  AtcoGenie AI - Full E2E Test (Auth + Insight Engine)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Step 1: Get Session Token from .NET
Write-Host ""
Write-Host "[Step 1] Authenticating via .NET Windows Auth..." -ForegroundColor Yellow
try {
    $authResponse = Invoke-RestMethod -Uri $dotNetUrl -Method Post -UseDefaultCredentials
    $token = $authResponse.access_token
    $displayName = $authResponse.user.display_name
    Write-Host "  SUCCESS! Authenticated as: $displayName" -ForegroundColor Green
    Write-Host "  Token: $token" -ForegroundColor DarkGray
} catch {
    Write-Host "  FAILED: $_" -ForegroundColor Red
    Write-Host "  Make sure .NET Server is running on localhost:5256" -ForegroundColor Yellow
    exit 1
}

# Step 2: Verify Python reads the token
Write-Host ""
Write-Host "[Step 2] Verifying Python SecurityContext from Redis..." -ForegroundColor Yellow
$headers = @{ "Authorization" = "Bearer $token" }
try {
    $ctxResponse = Invoke-RestMethod -Uri $pythonAuthUrl -Method Get -Headers $headers
    Write-Host "  SUCCESS! Python hydrated SecurityContext:" -ForegroundColor Green
    Write-Host ("    User: " + $ctxResponse.user_id) -ForegroundColor White
    Write-Host ("    Employee: " + $ctxResponse.employee_id) -ForegroundColor White
    Write-Host ("    Rights count: " + $ctxResponse.form_rights.Count) -ForegroundColor White
} catch {
    Write-Host "  FAILED: $_" -ForegroundColor Red
    Write-Host "  Make sure Python FastAPI is running on localhost:8000" -ForegroundColor Yellow
    exit 1
}

# Step 3: Send a chat prompt to the Insight Engine
Write-Host ""
Write-Host "[Step 3] Sending prompt to LangChain Insight Engine..." -ForegroundColor Yellow
Write-Host "  Prompt: What reports are available for me?" -ForegroundColor DarkGray

$chatBody = @{
    message = "What reports are available for me?"
    chat_history = @()
} | ConvertTo-Json

$chatHeaders = @{
    "Authorization" = "Bearer $token"
    "Content-Type"  = "application/json"
}

try {
    $chatResponse = Invoke-RestMethod -Uri $pythonChatUrl -Method Post -Headers $chatHeaders -Body $chatBody -TimeoutSec 60
    Write-Host "  SUCCESS!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Genie says:" -ForegroundColor Cyan
    Write-Host ("  " + $chatResponse.reply) -ForegroundColor White
    Write-Host ""
    Write-Host "  User context:" -ForegroundColor Yellow
    Write-Host ("    Role: " + $chatResponse.user.role) -ForegroundColor White
    $teamList = $chatResponse.user.teams -join ", "
    Write-Host ("    Teams: " + $teamList) -ForegroundColor White
    Write-Host ("    Admin: " + $chatResponse.user.is_admin) -ForegroundColor White
} catch {
    Write-Host "  FAILED: $_" -ForegroundColor Red
    try {
        $errorStream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($errorStream)
        $body = $reader.ReadToEnd()
        Write-Host ("  Response Body: " + $body) -ForegroundColor DarkRed
    } catch {}
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Test Complete!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
