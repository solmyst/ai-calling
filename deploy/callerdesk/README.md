# CallerDesk → AI bot

CallerDesk's integration is SIP. The bot registers on CallerDesk's Asterisk
the same way MicroSIP does, over a site-to-site tunnel. Pipecat has no SIP
transport, so a local Asterisk on the VM handles the SIP side. It passes each
call's audio to `voicebot/server/callerdesk_bridge.py`, which feeds the bot's
existing phone endpoint (`/ws`, the Exotel protocol).

```
CallerDesk Asterisk 192.168.3.11 ──SIP/RTP over tunnel──> our Asterisk (VM)
   ──AudioSocket tcp 127.0.0.1:9092──> callerdesk_bridge.py ──ws──> bot.py /ws
```

## Tested

The bridge and the bot were tested end to end on the VM on 2026-09-24.
`evals/phone_sim.py` played the part of Asterisk. It sent AudioSocket audio
with proposal 859623 in the UUID. The bot loaded that case's card and answered
three spoken caller lines. First audio came back 2.5–2.8s after the caller
stopped speaking.

Not yet tested: the tunnel and the real SIP leg. Both need the steps below.

## Needs root on the VM (admin)

1. **Tunnel to CallerDesk.** Use strongSwan (`apt install strongswan`) with
   CallerDesk's IPsec parameters: peer IP, PSK, phase 1/2 proposals, and their
   subnet (which includes 192.168.3.11). Check it with `ping 192.168.3.11`.
2. **Asterisk.** Run `apt install asterisk` (Ubuntu 22.04 ships 18.x). Then
   confirm AudioSocket is present:
   `asterisk -rx "module show like audiosocket"`.
3. Copy `pjsip.conf` and `extensions.conf` from this folder to
   `/etc/asterisk/`. Replace `AGENT_NUMBER`. Then run
   `asterisk -rx "core reload"`.
4. Check the registration: `asterisk -rx "pjsip show registrations"` should
   print `Registered`.
5. Start the bridge (no root needed):
   `cd ~/ai-calling/voicebot/server && .venv/bin/python callerdesk_bridge.py`.
6. Make a test call. Inbound: ring the agent from CallerDesk. Outbound:
   `asterisk -rx "channel originate PJSIP/<number>@callerdesk extension s@ai-bot"`.

## Ask CallerDesk

- The IPsec tunnel parameters (above).
- One agent number per concurrent call. A SIP registration usually carries
  only one call at a time.
- Whether the agent account may dial customers out, or whether CallerDesk
  dials and routes answered calls to us.
- For calls they route to us: whether they can put the proposal id in a SIP
  header (`X-Proposal-Id`). Without it, the bot can't tell which customer it is
  talking to.
- Which codec they use (ulaw or alaw) and how they send DTMF.
