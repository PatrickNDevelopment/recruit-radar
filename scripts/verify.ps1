# Runs every verification step; stops at the first failure with a nonzero exit code.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$steps = @(
  @{ Name = 'install (lockfile)'; Args = @('ci') },
  @{ Name = 'format check'; Args = @('run', 'format:check') },
  @{ Name = 'lint'; Args = @('run', 'lint') },
  @{ Name = 'typecheck'; Args = @('run', 'typecheck') },
  @{ Name = 'frontend unit tests'; Args = @('test') },
  @{ Name = 'backend lint'; Args = @('run', 'backend:lint') },
  @{ Name = 'backend format'; Args = @('run', 'backend:format') },
  @{ Name = 'backend types'; Args = @('run', 'backend:types') },
  @{ Name = 'backend tests'; Args = @('run', 'backend:test') },
  @{ Name = 'vectors + oracle self-check'; Args = @('run', 'vectors:check') },
  @{ Name = 'cross-implementation fuzz'; Args = @('run', 'fuzz') },
  @{ Name = 'production build'; Args = @('run', 'build') },
  @{ Name = 'secret scan'; Args = @('run', 'secrets') },
  @{ Name = 'browser e2e'; Args = @('run', 'e2e') }
)
foreach ($s in $steps) {
  Write-Host "==> $($s.Name)" -ForegroundColor Cyan
  & npm @($s.Args)
  if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: $($s.Name) (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
  }
}
Write-Host 'ALL CHECKS PASSED' -ForegroundColor Green
