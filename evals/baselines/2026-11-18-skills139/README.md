# skills#139 re-measure, 2026-11-18

Descriptions from https://github.com/dvystrcil/skills/pull/168. 10 runs per arm.

## qwen3-coder-next, --harness opencode

| skill | case | with | without | Δ | fired | note | costUsd |
|---|---|---|---|---|---|---|---|
| three-anchor-truthiness | two-versus-one-drift | 0.07 | 0.00 | +0.07 | 0/10 | skill never fired | — |
| change-validation | worker-bump-before-after | 0.93 | 0.33 | +0.60 | 8/10 |  | — |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.10 | 0.25 | -0.15 | 0/10 | skill never fired; skill makes it WORSE | — |
| homelab-image-updater | filebrowser-stable-channel | 0.20 | 0.42 | -0.22 | 10/10 | skill makes it WORSE; hit max_turns: with 4/10, without 1/10 | — |
| homelab-secrets | literal-password-in-manifest | 0.73 | 0.10 | +0.63 | 4/10 |  | — |
| git-workflow | fetch-before-editing | 0.40 | 0.00 | +0.40 | 3/10 |  | — |

## Claude (sonnet), --harness claude (est. at API prices, subscription run)

| skill | case | with | without | Δ | fired | note | costUsd |
|---|---|---|---|---|---|---|---|
| change-validation | worker-bump-before-after | 0.93 | 0.40 | +0.53 | 10/10 |  | 1.41 |
| homelab-secrets | literal-password-in-manifest | 1.00 | 0.33 | +0.67 | 10/10 |  | 1.15 |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.10 | 0.00 | +0.10 | 10/10 |  | 0.95 |
| three-anchor-truthiness | two-versus-one-drift | 1.00 | 0.10 | +0.90 | 10/10 |  | 0.91 |
| three-anchor-truthiness | user-supplied-value | 1.00 | 1.00 | +0.00 | 0/10 | should not fire | 0.68 |
| homelab-image-updater | filebrowser-stable-channel | 1.00 | 0.60 | +0.40 | 10/10 |  | 1.16 |
| git-workflow | fetch-before-editing | 1.00 | 0.00 | +1.00 | 10/10 |  | 1.27 |
