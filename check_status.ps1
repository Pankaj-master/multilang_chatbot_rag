# System Status Check Script

Write-Host "=== RAG Chatbot System Status ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check Backend Server
Write-Host "[1] Backend Server Status:" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8001/ready" -TimeoutSec 5 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "   ✓ Backend is RUNNING on port 8001" -ForegroundColor Green
    }
} catch {
    Write-Host "   ✗ Backend is NOT running" -ForegroundColor Red
}

# 2. Check Database
Write-Host "`n[2] Database Connection:" -ForegroundColor Yellow
$pgProcess = Get-Process postgres -ErrorAction SilentlyContinue
if ($pgProcess) {
    Write-Host "   ✓ PostgreSQL process is running" -ForegroundColor Green
} else {
    Write-Host "   ✗ PostgreSQL is NOT running" -ForegroundColor Red
}

# 3. Check Environment Variables
Write-Host "`n[3] Environment Configuration:" -ForegroundColor Yellow
$envFile = ".\.env"
if (Test-Path $envFile) {
    Write-Host "   ✓ .env file exists" -ForegroundColor Green
    $envContent = Get-Content $envFile
    
    # Check for API keys
    $geminiKey = $envContent | Select-String "GEMINI_API_KEY="
    $openaiKey = $envContent | Select-String "OPENAI_API_KEY="
    
    if ($geminiKey -and $geminiKey -notmatch "your_.*_here") {
        Write-Host "   ✓ GEMINI_API_KEY is set" -ForegroundColor Green
    } else {
        Write-Host "   ✗ GEMINI_API_KEY needs to be configured" -ForegroundColor Red
    }
    
    if ($openaiKey -and $openaiKey -notmatch "your_.*_here") {
        Write-Host "   ✓ OPENAI_API_KEY is set" -ForegroundColor Green
    } else {
        Write-Host "   ⚠ OPENAI_API_KEY not set (needed for embeddings)" -ForegroundColor Yellow
    }
} else {
    Write-Host "   ✗ .env file NOT found" -ForegroundColor Red
}

# 4. Check Frontend
Write-Host "`n[4] Frontend Status:" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 5 -UseBasicParsing
    Write-Host "   ✓ Frontend is RUNNING on port 5173" -ForegroundColor Green
} catch {
    Write-Host "   ✗ Frontend is NOT running" -ForegroundColor Red
    Write-Host "      Run: cd frontend; npm run dev" -ForegroundColor Gray
}

# 5. Check Recent Logs
Write-Host "`n[5] Recent Backend Activity:" -ForegroundColor Yellow
if (Test-Path "rag_app.log") {
    $recentLogs = Get-Content "rag_app.log" -Tail 10
    $lastRequest = $recentLogs | Select-String "Incoming:" | Select-Object -Last 1
    $lastError = $recentLogs | Select-String "ERROR" | Select-Object -Last 1
    
    if ($lastRequest) {
        Write-Host "   Last Request: $($lastRequest)" -ForegroundColor Gray
    }
    if ($lastError) {
        Write-Host "   Last Error: $($lastError)" -ForegroundColor Red
    }
}

Write-Host "`n=== Action Items ===" -ForegroundColor Cyan
Write-Host "1. Add your GEMINI_API_KEY to .env file" -ForegroundColor Yellow
Write-Host "2. Add your OPENAI_API_KEY to .env file (for embeddings)" -ForegroundColor Yellow  
Write-Host "3. Start frontend: cd frontend; npm run dev" -ForegroundColor Yellow
Write-Host "4. Access chatbot at: http://localhost:5173" -ForegroundColor Yellow
Write-Host ""
