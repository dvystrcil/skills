### qwen3-coder-next (opencode)

| skill | case | with | without | Δ | fired | note |
|---|---|---|---|---|---|---|
| batch-lane | vt350-refresh-goes-to-lane | 0.92 | 0.67 | +0.25 | 2/3 |  |
| change-validation | worker-bump-before-after | 0.33 | 0.33 | +0.00 | 1/3 | no skill effect: tests the base model (AC4) |
| file-issue | follow-up-goes-to-draft-issue | 1.00 | 0.00 | +1.00 | 3/3 |  |
| git-workflow | fetch-before-editing | 0.00 | 0.00 | +0.00 | 0/3 | skill never fired; no skill effect: tests the base model (AC4) |
| homelab-image-updater | filebrowser-stable-channel | 0.73 | 0.20 | +0.53 | 1/3 |  |
| homelab-secrets | literal-password-in-manifest | 0.33 | 0.11 | +0.22 | 0/3 | skill never fired |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.50 | 0.33 | +0.17 | 0/3 | skill never fired |
| three-anchor-truthiness | two-versus-one-drift | 0.00 | 0.00 | +0.00 | 0/3 | skill never fired; no skill effect: tests the base model (AC4) |

Mean over 8 scored case(s): with 0.48, without 0.21, Δ +0.27. Errored: 0.
