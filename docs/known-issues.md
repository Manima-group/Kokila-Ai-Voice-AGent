# Known issues and open items

| ID | Severity | Issue | Next step |
|---|---|---|---|
| KI-01 | high | Most mandatory modules are not implemented (see implementation-status.md) | Continue the build |
| KI-02 | high | No live provider has been verified. Reasoning/Realtime/LiveKit request shapes follow vendor docs but are untested with real keys | Supply keys; run contract tests |
| KI-03 | medium | Docker base images use tags, not digests. Images were not built in the dev container (no daemon) | Resolve digests; build in CI |
| KI-04 | medium | GitHub Actions are referenced by tag, not SHA. CI hasn't run on GitHub yet | Pin SHAs; enable branch protection |
| KI-05 | medium | CSP allows `'unsafe-inline'` scripts (Next.js inline runtime) | Move to nonce-based CSP |
| KI-06 | medium | Session/policy change events are published to Redis but not streamed to browsers (no SSE/WebSocket) | Add an event stream endpoint |
| KI-07 | low | Theme is provisional; Manima Hub parity is unverified | Obtain Hub tokens |
| KI-08 | low | Language detection is script-based only; Roman Telugu/Hindi rely on the model | Evaluate a classifier (§16) |
| KI-09 | low | The browser "played characters" count uses speech boundary events, which some voices don't emit | Use realtime playback offsets |
