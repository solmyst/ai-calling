# Running the bot on a VM (browser test)

Talk to the bot from Chrome on any machine; the bot runs on the VM, so the
latency you hear is the real network + model latency, not your laptop's.

## 1. VM
- Ubuntu 22.04 or 24.04, 2 vCPU / 4 GB RAM is enough.
- Add your SSH public key when creating it.
- Firewall / security group, inbound: **TCP 22, 80, 443** and **UDP 1024-65535**
  (the voice audio is WebRTC over UDP straight to the VM).

## 2. Install (once)
```bash
ssh -A ubuntu@<vm-ip>        # -A forwards your key so the VM can clone from Bitbucket
git clone -b insurance git@bitbucket.org:ovunque/ai-calling-agent.git /tmp/aic
bash /tmp/aic/voicebot/deploy/setup.sh
```

## 3. Keys
Copy your local `voicebot/server/.env` up (it holds the API keys, never in git):
```bash
scp voicebot/server/.env ubuntu@<vm-ip>:/opt/ai-calling/voicebot/server/.env
```

## 4. Start
```bash
bash /opt/ai-calling/voicebot/deploy/start.sh
```
It prints the address, `https://<vm-ip-with-dashes>.sslip.io/` — no domain
needed. Open it in Chrome, allow the mic, press **Connect**.

## Every day
```bash
tail -f /opt/ai-calling/voicebot/server/call.log      # LATENCY / STT LAG lines per turn
sudo systemctl restart voicebot                       # after editing .env
cd /opt/ai-calling && git pull && sudo systemctl restart voicebot   # new code
```

## If Connect spins forever
The page loaded but audio never started: UDP is blocked. Open UDP 1024-65535
inbound on the VM (cloud security group AND `sudo ufw allow 1024:65535/udp` if
ufw is on).
