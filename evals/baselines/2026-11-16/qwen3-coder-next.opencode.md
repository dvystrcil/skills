### qwen3-coder-next (opencode)

| skill | case | with | without | Δ | fired | note | costUsd |
|---|---|---|---|---|---|---|---|
| batch-lane | vt350-refresh-goes-to-lane | 0.88 | 0.70 | +0.18 | 4/10 | timed out: with 3/10, without 0/10 | — |
| change-validation | worker-bump-before-after | 0.33 | 0.33 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) | — |
| file-issue | follow-up-goes-to-draft-issue | 1.00 | 0.05 | +0.95 | 10/10 |  | — |
| git-workflow | fetch-before-editing | 0.05 | 0.00 | +0.05 | 1/10 |  | — |
| homelab-image-updater | filebrowser-stable-channel | 0.28 | 0.48 | -0.20 | 2/10 | skill makes it WORSE; hit max_turns: with 2/10, without 1/10 | — |
| homelab-secrets | literal-password-in-manifest | 0.27 | 0.33 | -0.07 | 0/10 | skill never fired; skill makes it WORSE | — |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.30 | 0.10 | +0.20 | 0/10 | skill never fired | — |
| three-anchor-truthiness | two-versus-one-drift | 0.00 | 0.00 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) | — |
| three-anchor-truthiness | user-supplied-value | 1.00 | 1.00 | +0.00 | 0/10 | should not fire | — |

Mean over 9 scored case(s): with 0.46, without 0.33, Δ +0.12. Errored: 0.
