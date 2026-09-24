# CallerDesk → AI bot

CallerDesk integrates over SIP. The bot registers on CallerDesk's Asterisk the
same way MicroSIP does, over a site-to-site tunnel. Pipecat has no SIP
transport, so a local Asterisk on the VM handles the SIP side. It passes each
call's audio to `voicebot/server/callerdesk_bridge.py`, which feeds the bot's
existing phone endpoint (`/ws`, the same one the Exotel calls use).

```
CallerDesk Asterisk 192.168.3.11 ──SIP/RTP over the tunnel──> our Asterisk (VM)
   ──AudioSocket tcp 127.0.0.1:9092──> callerdesk_bridge.py ──ws──> bot.py /ws
```

## The two call directions

**Customer → bot (inbound).** The customer rings the CallerDesk number, for
example DID 01206089182. CallerDesk routes the call to our agent number, the
way it would ring a MicroSIP agent. Our Asterisk answers (`[from-callerdesk]`)
and hands the call to the bot. For the bot to know which customer is calling,
CallerDesk has to send the proposal id and phone in SIP headers (see the ask
list below). Without them the bot runs the generic call and can't send the
KYC link.

**Bot → customer (outbound).** Start the call with:

```bash
python callerdesk_bridge.py dial 9876543210 741688
```

Our Asterisk dials the customer through CallerDesk. When they answer, the call
goes to the bot with that proposal and phone, the bot sends the KYC link on
WhatsApp, and the call starts. The dialer or campaign script runs this once per
customer.

## Status on the VM (2026-09-24)

Done on 134.195.138.223 with sudo:
- **Asterisk 18.10:** installed with AudioSocket. `chan_sip` and IAX are
  disabled, so PJSIP owns port 5060. The originals are backed up in
  `/etc/asterisk.orig-20260924`.
- **Configs:** `pjsip.conf`, `extensions.conf` and `manager.conf` are
  installed. The AMI user is `aibot`, with its secret in `voicebot/server/.env`.
- **Bridge:** `callerdesk-bridge` runs as a systemd service, enabled and
  restarting on failure.
- **strongSwan:** installed, with no tunnel configured yet.
- **Firewall:** ufw allows only SSH. Asterisk is not reachable from the
  internet.
- **/dev/null:** was a plain file and has been recreated as the device.
- **Real Asterisk call:**
  `asterisk -rx "channel originate Local/s@ai-bot-test extension s@test-caller"`
  goes Asterisk → AudioSocket → bridge → bot. The bot transcribed both played
  caller lines and answered in 2.0s and 2.8s.
  - Found while testing: Asterisk sends no frames during silence. The bridge
    now fills those gaps, since the STT needs silence to end a turn.

Waiting on CallerDesk. The registration keeps retrying
`sip:AGENT_NUMBER@192.168.3.11` until both of these are done:
1. **Tunnel:** put CallerDesk's parameters into strongSwan
   (`/etc/swanctl/conf.d/callerdesk.conf`). Allow UDP 500/4500 from their
   peer IP only, with `ufw allow from <peer> to any port 500,4500 proto udp`.
2. **Agent number:** replace `AGENT_NUMBER` (3 places) in
   `/etc/asterisk/pjsip.conf`, then run `asterisk -rx "core reload"`.

## Tested

Tested on the VM on 2026-09-24:
- `evals/phone_sim.py` played the part of Asterisk. It sent audio with the
  proposal in the call UUID, and the bot loaded the case and answered three
  spoken turns. First audio came back 2.5–2.8s after the caller stopped.
- `dial` was checked against a fake Asterisk manager (the check is in
  `test_callerdesk_bridge.py`).

Not yet tested: the tunnel and the real SIP leg. Both need the steps below.

## VM admin: needs root

The VM account `anush` has no sudo, Docker or compiler, so an admin has to do
these steps.

1. **Tunnel to CallerDesk.** Install strongSwan (`apt install strongswan`) and
   configure it with the IPsec parameters CallerDesk provides (see the ask
   list). Check it with `ping 192.168.3.11`.
2. **Asterisk.** Run `apt install asterisk` (Ubuntu 22.04 ships 18.x). Then
   confirm AudioSocket is present:
   `asterisk -rx "module show like audiosocket"`.
3. Copy `pjsip.conf`, `extensions.conf` and `manager.conf` from this folder to
   `/etc/asterisk/`.
   - In `pjsip.conf`, replace `AGENT_NUMBER`.
   - In `manager.conf`, replace `CHANGE_ME`.
   - Then run `asterisk -rx "core reload"`.
4. Check the registration: `asterisk -rx "pjsip show registrations"` should
   show `Registered`.

## Then, no root needed

These run as the `anush` user.

5. In `voicebot/server/.env`, set `AMI_USER=aibot` and `AMI_SECRET=<same as
   manager.conf>`. Also set `CALLERDESK_DIAL_PREFIX` if CallerDesk wants a
   leading `0`.
6. Start the bridge:
   `cd ~/ai-calling/voicebot/server && .venv/bin/python callerdesk_bridge.py`.
7. Test outbound: `.venv/bin/python callerdesk_bridge.py dial <your number> 741688`.
8. Test inbound: call the CallerDesk DID and have it routed to our agent.

## Ask the CallerDesk team

1. **Tunnel parameters:**
   - their public peer IP
   - pre-shared key
   - IKE version and phase 1/2 proposals (encryption, hash, DH group, lifetimes)
   - their subnet (which includes 192.168.3.11)

   Our side is the VM, public IP 134.195.138.223. Alternatively, ask whether they
   can allow SIP from 134.195.138.223 directly, which would avoid the tunnel.
2. **Agent numbers:** one per concurrent call. A SIP registration usually
   carries one call at a time, so 5 parallel calls need 5 agents.
3. **Outbound dialing:** is this agent allowed to dial customer numbers out,
   and in what format (`0XXXXXXXXXX`, `91XXXXXXXXXX`, or 10 digits)? Which
   caller ID will customers see?
4. **Inbound metadata:** for calls they route to us, can they add SIP headers
   `X-Proposal-Id` and `X-Customer-Phone`?
5. **Codec and DTMF:** ulaw or alaw? RFC 2833/4733 DTMF?
6. **Recording:** do they record calls on their side? This matters for
   compliance with our own logs.

## In the CallerDesk dashboard

- Create the agent(s) and note their numbers. Those numbers are the SIP
  username and password.
- Route the DID (e.g. 01206089182), or the IVR/queue option for KYC, to those
  agents so inbound calls ring the bot.
- If outbound runs from CallerDesk's own dialer or campaign instead of our
  `dial` command, set the campaign to connect answered calls to the AI agents.
  In that case it must pass the proposal id (point 4 above).
