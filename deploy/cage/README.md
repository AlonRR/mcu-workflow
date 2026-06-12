# cage — boundary enforcement (deliverable #5)

The disposable sandbox the launcher opens, with the guardrails from `docs/architecture.md` Section 7 enforced **by the environment, not the agent**. The design rule: the agent should be *physically unable* to do the forbidden thing.

## What's here

- `docker-compose.yml` — two services on two networks. `cage` sits on an **internal** network (`cage-net`, no internet). The `egress-proxy` bridges `cage-net` and an `outbound` network, so the cage's only route out is through the proxy.
- `proxy/` — a tiny **default-deny** allowlisting proxy (tinyproxy). `allowlist.txt` is the fixed host set; anything not listed is refused.

## Run

```bash
docker compose -f cage/docker-compose.yml up --build
```

The agent inside gets `HTTP(S)_PROXY=http://egress-proxy:8888`; direct connections fail because `cage-net` is `internal: true`.

## How each Section-7 promise is enforced

| Promise | Mechanism here |
|---|---|
| Egress allowlist | `cage-net` is `internal` (no internet); only the proxy can reach out, and only to hosts in `allowlist.txt`. |
| No credential exfiltration | No secrets mounted; only `../:/work` is writable; nothing to steal and nowhere to send it. |
| No destructive host commands | `cap_drop: [ALL]`, `no-new-privileges`, host FS not mounted (only the project). Add `--user` (the launcher does) for non-root. |
| Hardware access without going wide-open | Per-device passthrough is commented in the compose (uncomment the specific `/dev/ttyACM0`), never `privileged`. |
| Untrusted content containment | Injected instructions can't exfiltrate (no egress), persist (disposable), or escalate (dropped caps). |

## Adding a host

Append a regex line to `proxy/allowlist.txt` and restart the proxy. Keep it tight — every entry widens the attack surface.

## Stronger isolation

For a harder boundary (untrusted third-party components), run the same compose under a microVM runtime (Firecracker/Kata) or a dedicated VM — no change to the workflow above it.

## Note

Full live verification needs Docker. The compose and proxy config are provided as the enforcement layer; validate the topology with `docker compose config` on your host.
