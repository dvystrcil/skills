### qwen3635b (opencode)

| skill | case | with | without | Δ | fired | note | costUsd |
|---|---|---|---|---|---|---|---|
| batch-lane | vt350-refresh-goes-to-lane | 0.75 | 0.68 | +0.07 | 4/10 | hit max_turns: with 0/10, without 1/10; timed out: with 7/10, without 6/10 | — |
| change-validation | worker-bump-before-after | 0.37 | 0.33 | +0.03 | 1/10 |  | — |
| file-issue | follow-up-goes-to-draft-issue | 0.95 | 0.20 | +0.75 | 9/10 |  | — |
| git-workflow | fetch-before-editing | 0.00 | 0.00 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) | — |
| homelab-image-updater | filebrowser-stable-channel | 0.72 | 0.60 | +0.12 | 3/10 | timed out: with 0/10, without 1/10 | — |
| homelab-secrets | literal-password-in-manifest | 0.27 | 0.27 | +0.00 | 1/10 | no skill effect: tests the base model (AC4) | — |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.00 | 0.00 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) | — |
| three-anchor-truthiness | two-versus-one-drift | 0.07 | 0.00 | +0.07 | 1/10 |  | — |
| three-anchor-truthiness | user-supplied-value | 1.00 | 0.90 | +0.10 | 0/10 | should not fire; timed out: with 0/10, without 1/10 | — |

Mean over 9 scored case(s): with 0.46, without 0.33, Δ +0.13. Errored: 0.
