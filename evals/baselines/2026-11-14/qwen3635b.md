### qwen3635b

| skill | case | with | without | Δ | fired | note |
|---|---|---|---|---|---|---|
| batch-lane | vt350-refresh-goes-to-lane | 0.70 | 0.55 | +0.15 | 3/10 | hit max_turns: with 2/10, without 2/10; timed out: with 5/10, without 4/10 |
| change-validation | worker-bump-before-after | 0.47 | 0.47 | +0.00 | 0/10 | skill never fired; no skill effect: tests the base model (AC4) |
| file-issue | follow-up-goes-to-draft-issue | 0.85 | 0.15 | +0.70 | 9/10 |  |
| git-workflow | fetch-before-editing | 0.25 | 0.05 | +0.20 | 1/10 | hit max_turns: with 1/10, without 0/10 |
| homelab-image-updater | filebrowser-stable-channel | 0.78 | 0.60 | +0.18 | 7/10 | timed out: with 0/10, without 1/10 |
| homelab-secrets | literal-password-in-manifest | 0.43 | 0.20 | +0.23 | 2/10 |  |
| three-anchor-truthiness | jvm-heap-on-a-go-service | 0.05 | 0.00 | +0.05 | 0/10 | skill never fired |
| three-anchor-truthiness | two-versus-one-drift | 0.13 | 0.33 | -0.20 | 4/10 | skill makes it WORSE; timed out: with 3/10, without 0/10 |

Mean over 8 scored case(s): with 0.46, without 0.29, Δ +0.16. Errored: 0.
