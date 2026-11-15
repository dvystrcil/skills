### qwen3-coder-next (opencode)

| skill | case | with | without | Δ | fired | note |
|---|---|---|---|---|---|---|
| batch-lane | vt350-refresh-goes-to-lane | 0.95 | 0.65 | +0.30 | 6/10 |  |
| change-validation | worker-bump-before-after | 0.33 | 0.33 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) |
| file-issue | follow-up-goes-to-draft-issue | 1.00 | 0.00 | +1.00 | 10/10 | hit max_turns: with 1/10, without 0/10 |
| git-workflow | fetch-before-editing | 0.05 | 0.00 | +0.05 | 1/10 |  |
| homelab-image-updater | filebrowser-stable-channel | 0.46 | 0.42 | +0.04 | 1/10 |  |
| homelab-secrets | literal-password-in-manifest | 0.27 | 0.17 | +0.10 | 0/10 | skill never fired |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.20 | 0.25 | -0.05 | 0/10 | skill never fired; skill makes it WORSE |
| three-anchor-truthiness | two-versus-one-drift | 0.07 | 0.07 | +0.00 | 1/10 | no skill effect: tests the base model (AC4) |

Mean over 8 scored case(s): with 0.42, without 0.24, Δ +0.18. Errored: 0.
