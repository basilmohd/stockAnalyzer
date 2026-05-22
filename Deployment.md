# AWS EC2 Deployment Plan — Portfolio Agent (ap-south-1 Mumbai)

## TL;DR

Deploy to **AWS EC2 t3.small** (2 vCPU, 2GB RAM, ~$8-10/month) in ap-south-1 because your workload is I/O-bound (API calls, scheduler waits) not CPU-intensive. Run both processes as systemd services, self-hosted Redis on the same instance, daily SQLite backups to S3, and use ACM + Route53 for HTTPS. Total deployment time: ~2 hours.

---

## Instance Selection: Why t3.small?

### Resource Analysis

| Component | Usage | Peak | Rationale |
|-----------|-------|------|-----------|
| CPU | Scheduler (idle wait), FastAPI (I/O wait), pandas-ta (3-5 min bursts) | ~30-40% during signal generation | Burstable (t3) sufficient; never sustained high CPU |
| Memory | FastAPI (~150MB) + APScheduler (~100MB) + Redis (~80MB) + Python libs | ~1.2-1.5 GB | 2GB safe buffer; t3.micro (1GB) too tight |
| Disk | SQLite DB (~50-100 MB) + logs (1 GB 7-day rotation) + application | ~2-3 GB used | 30GB root volume sufficient |
| Network | API calls to Kite, Anthropic, Telegram, NewsAPI (bursty) | <100 Mbps | Burstable up to 5 Gbps is more than enough |

### Why NOT t3.micro?
- 1 GB RAM is cutting it with pandas, numpy, yfinance, both processes + Redis
- Risk of OOM kills during heavy indicator computation → service crashes
- Save only $2-3/month, not worth operational risk

### Why NOT t3.medium/large?
- 4+ GB RAM overkill for this workload
- You're not doing heavy ML or batch processing
- Scale up later if needed (easy with systemd restarts)

**Decision: t3.small (2 vCPU, 2 GB RAM, burstable) is the sweet spot.**

---

## Deployment Steps: 7 Phases (~2 hours)

### Phase 1: AWS Account & Network Setup (30 min)

1. **Create EC2 instance** in ap-south-1
   - AMI: Ubuntu 24.04 LTS (latest stable)
   - Instance type: t3.small
   - Root volume: 30 GB gp3
   - Tag: `Name=portfolio-agent`

2. **Create Elastic IP** and attach to instance
   - Needed for stable Telegram/Kite webhook callbacks
   - No monthly charge when attached to running instance

3. **Create Security Group** with these rules:
   - **Inbound:**
     - Port 443 (HTTPS) from 0.0.0.0/0 (Telegram + browser)
     - Port 22 (SSH) from YOUR_DEVELOPER_IP/32 only
   - **Outbound:** Allow all (for API calls to external services)

4. **Route53: Create A record**
   - Point `webhook.yourdomain.com` → Elastic IP
   - Needed for ACM certificate validation

5. **ACM Certificate**
   - Request public certificate for `webhook.yourdomain.com`
   - Validate via DNS (Route53 auto-fill)
   - Wait for approval (~5 min)

---

### Phase 2: EC2 Environment Setup (30 min)

6. **SSH into instance**
   ```bash
   ssh -i your-key.pem ubuntu@ELASTIC_IP

7. Update system & install dependencies
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    redis-server redis-tools curl wget git build-essential libssl-dev

8.  