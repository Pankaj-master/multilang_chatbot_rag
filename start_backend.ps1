param(
  [string]$api_host = "0.0.0.0",
  [int]$api_port = 8001
)

# Activate virtualenv
& "$PSScriptRoot\backend\app\.venv\Scripts\Activate.ps1"

# Start server
python -m uvicorn backend.app.main:app --host $api_host --port $api_port --reload
