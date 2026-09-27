# Evidence for F-10 — Proactive "Job Finished" Announcement

## Spike Findings & AssemblyAI API Research
**Research Question:** Does the AssemblyAI Voice Agent Real-Time WebSocket API support client-initiated push speech events (e.g. `reply.create` or `conversation.item.create`) while idle?

**Findings:**
- AssemblyAI Voice Agent WebSocket Protocol (`wss://agents.assemblyai.com/v1/ws`):
  - Client -> Server supported message types: `session.update`, `audio` (PCM chunk), `tool.result`.
  - Server -> Client message types: `session.updated`, `transcript`, `audio`, `tool.call`, `error`.
- Documentation reference: [AssemblyAI Real-time Agent API Documentation](https://www.assemblyai.com/docs/voice-agent)
- **Conclusion:** AssemblyAI WebSocket API does not currently expose a client push event to interrupt idle silence with unprompted synthetic speech without user turn initiation.

## Fallback Architecture & Implementation
Per spec F-10 fallback requirements:
1. **Production Panel Polling (`app/static/production_panel.js`)**:
   - `checkJobCompletions()` compares previous action statuses to newly fetched actions.
   - When an action transitions from `queued`/`running` to `done`, it triggers `BrandStudioAgent.onJobFinished(job)`.

2. **Pending Announcement Queue (`app/static/agent.js`)**:
   - `onJobFinished(job)` constructs announcement text (e.g., `"Your AI video for scene 5 is ready"`).
   - Enqueues into `pending_announcements` queue. Duplicates are suppressed.

3. **Non-Interruptive Turn Integration**:
   - Next call to `buildStepSummary(step, ctx)` includes: `Notifications: Your AI video for scene 5 is ready.`
   - Delivered to Brandy in the prompt / `session.update` for her next turn.
   - Never interrupts the founder mid-utterance.

## Verification Evidence
- Node test harness: `tests/agent_announce.test.js` passed (100% clean exit).
- Pytest integration test: `tests/test_agent_f08.py` passed (5/5 tests passed).

```
ok - onJobFinished creates formatted announcement for scene 5 AI video
ok - buildStepSummary includes pending announcements
ok - addAnnouncement prevents duplicate announcements
ok - clearPendingAnnouncements empties the queue
ok - Production Panel detects job transition from running to done

All F-10 proactive announcement checks passed.
```
