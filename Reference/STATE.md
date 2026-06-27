# STATE.md — current checkpoint (OVERWRITE every session-end; never append)
Updated: 2026-06-25 16:42 · Workstream: VOICE · HEAD: 7bd51e1 (live-tuning ledger doc; verify w/ git)
Current stage: 9 — Video explanation + demo · Status: 🔄
Resume at: await Asaf's specific direction on the video (storyboard `docs/STAGE9_STORYBOARD.md` + `make eval`/`make receipts` toolchain already committed; recorded demo + receipts evidence still owed)
Live-truth (re-verify, don't trust → FACTS.md is source of truth): suite 543 pass / 1 skip / 1 xfail via `make test`; spend $0.81/$50 (live 2/6) via budget ledger; ENV4 import-safe; `make eval` A 0.4 / B 0.2, disclosure 0.8, objection 1.0, compliance 1.0, avg_turns 3.4/2.6; voice = gpt-4o-mini + Deepgram Aura `asteria` TTS + nova-2 STT
Open halts / decisions pending Asaf: video direction; stop the stale-config live servers? (`make serve` :8000 PIDs 19171/20788 + ngrok 19222 `pleading-stomp-referee`); push to origin? (main == origin/main last seen)
Last 3 superseded decisions (tombstones): OpenAI Realtime brain → standard pipeline gpt-4o-mini + Deepgram (2026-06-24); openai/shimmer TTS + gpt-4o → Deepgram Aura `asteria` + gpt-4o-mini latency tune 5.0s→1.7s (2026-06-25); ElevenLabs voice swap → reverted to HEAD f79deb3 (2026-06-25)
Disk-vs-ledger watch: 38 untracked `receipts/` on disk not yet in the ledger (NEW vs ledger; surfaced to Asaf, uninvestigated) + `M receipts/019ef8f2-…json`; `PLAN.md` footer partly stale (cites Realtime / 387–419 green) — reconciliation owed
