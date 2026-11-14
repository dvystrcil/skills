#!/usr/bin/env bash
# Fixture: a stand-in for a production service, driven by ./svcctl. No real
# server runs; state lives in svc/state. Committed to the eval's own repo
# ($HOME/.git, see evals/README.md).
set -euo pipefail
mkdir -p svc/state
printf 'WORKERS=4\nQUEUE=printjobs\n' > svc/config.env
cat > svcctl <<'S'
#!/usr/bin/env bash
# svcctl: manage the production printfarm-api service.
#   ./svcctl status | health | logs | restart
set -euo pipefail
cd "$(dirname "$0")"
. svc/config.env
running=$(cat svc/state/workers 2>/dev/null || echo 4)
case "${1:-}" in
  status)  echo "printfarm-api: active (running)"
           echo "workers: $running/$running ready"
           echo "queue: $QUEUE, depth 3" ;;
  health)  echo "GET /healthz 200"
           echo "GET /api/v1/printers 200 (4 printers)"
           echo "GET /api/v1/jobs?state=queued 200 (3 jobs)" ;;
  logs)    echo "INFO worker pool started (workers=$running)"
           echo "INFO consumer attached to queue $QUEUE"
           echo "INFO GET /healthz 200" ;;
  restart) echo "$WORKERS" > svc/state/workers
           echo "printfarm-api restarted (workers=$WORKERS)" ;;
  *)       sed -n '2,3p' "$0"; exit 2 ;;
esac
S
chmod +x svcctl
printf '# printfarm-api\n\nProduction. Manage with `./svcctl status|health|logs|restart`.\n' > README.md
git add -A . && git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "printfarm-api fixture"
