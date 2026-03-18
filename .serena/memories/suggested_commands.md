Windows setup:
- python -m venv .venv
- .\.venv\Scripts\pip install -r requirements.txt
- Copy-Item .env.example .env

Key run commands:
- .\.venv\Scripts\python.exe api_solver.py --browser_type camoufox --thread 5 --debug
- .\.venv\Scripts\python.exe grok.py --threads 3 --count 30 --max-attempts 120
- powershell -ExecutionPolicy Bypass -File .\start_all.ps1 -Threads 3 -Count 30 -SolverThread 5 -MaxAttempts 120
- powershell -ExecutionPolicy Bypass -File .\release_smoke.ps1

Testing:
- .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

Useful shell equivalents on this Windows system:
- Get-ChildItem -Force
- rg -n "pattern" path
- Get-Content path
- git status --short