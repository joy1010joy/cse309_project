# setup_env.ps1 - UniCafe Project Environment Setup
# Run this script to set up Node.js and npm in your PowerShell session

# Add Node.js to PATH
$env:PATH = "C:\nodejs\node-v20.12.2-win-x64;C:\Users\$env:USERNAME\AppData\npm-global;" + $env:PATH

# Verify Node.js installation
Write-Host "Node.js version:" -ForegroundColor Green
node --version

Write-Host "npm version:" -ForegroundColor Green
npm --version

Write-Host "`n✅ Environment setup complete!" -ForegroundColor Green
Write-Host "You can now use: npm, node, firebase commands" -ForegroundColor Green
