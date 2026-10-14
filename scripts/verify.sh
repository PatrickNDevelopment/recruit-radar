#!/usr/bin/env sh
# Runs every verification step; stops at the first failure with a nonzero exit code.
set -eu
cd "$(dirname "$0")/.."

run() {
  echo "==> $1"
  shift
  npm "$@"
}

run "install (lockfile)" ci
run "format check" run format:check
run "lint" run lint
run "typecheck" run typecheck
run "frontend unit tests" test
run "backend lint" run backend:lint
run "backend format" run backend:format
run "backend types" run backend:types
run "backend tests" run backend:test
run "vectors + oracle self-check" run vectors:check
run "cross-implementation fuzz" run fuzz
run "production build" run build
run "secret scan" run secrets
run "browser e2e" run e2e
echo "ALL CHECKS PASSED"
