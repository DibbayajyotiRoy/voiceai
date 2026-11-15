# AWS demo deploy (always-on)

Public browser and phone demo API at `https://demo-api.dibbayajyoti.com`, running on one Fargate x86_64 task. The task stays online to avoid cold starts.
Production layout is in [full.md](full.md) and is **not** deployed by this stack.

## What gets created (`demo.yaml`, region us-east-1)

- VPC with 2 public subnets, IGW, no NAT, no ALB.
- ECS cluster `voiceai-demo`, Fargate service (`desiredCount 1`, public IP, 0.5 vCPU / 1 GB, x86_64).
- Task: `app` (the Dockerfile image, port 8000) and `caddy` (official Caddy 2, TLS on 80/443,
  reverse-proxies to `localhost:8000`, including Twilio WebSockets).
- EFS (`/data` for Caddy: certs and ACME account), ECR repo `voiceai-demo` (keeps last 5 images).
- Control Lambda `voiceai-demo-control` with a Function URL. The legacy 5-minute idle-stop
  EventBridge rule remains in the template but is disabled.
- Task role: Bedrock invoke on Nova 2 Sonic and per-call report writes. Logs: `/ecs/voiceai-demo`,
  7-day retention. If configured, the execution role can read only the two Twilio secrets.

## Prerequisites

1. AWS CLI credentials for us-east-1 (`aws` or `uvx --from awscli aws`), plus Docker with buildx.
2. Create a Cloudflare API token with DNS edit access for `dibbayajyoti.com` and store it:
   ```bash
   aws secretsmanager create-secret --region us-east-1 --name voiceai/cloudflare-dns-token \
     --secret-string "<cloudflare-token>"
   ```
   The Lambda uses this only to upsert `demo-api` when the task IP changes.
3. Bedrock model access for Nova 2 Sonic (`amazon.nova-2-sonic-v1:0`) enabled in us-east-1.
4. Optional phone calling: a Twilio account and a voice-capable number. Store its credentials:
   ```bash
   aws secretsmanager create-secret --region us-east-1 --name voiceai/twilio-account-sid \
     --secret-string "<twilio-account-sid>"
   aws secretsmanager create-secret --region us-east-1 --name voiceai/twilio-auth-token \
     --secret-string "<twilio-auth-token>"
   ```
   The deploy script discovers these secret ARNs without printing their values. If either is absent,
   the site still deploys and `/api/telephony/incoming` returns 503 until phone calling is configured.

## Deploy

```bash
deploy/aws/deploy-demo.sh
```

The script is idempotent. It refuses to replace a task while a call is active unless `FORCE=1` is
set, creates an artifacts bucket for the Lambda zip, packages and deploys the stack, then builds the
amd64 image and pushes it tagged with the git sha. It prints the control URL at the end.

Check readiness:

```bash
curl "$CONTROL/status"           # starting -> ready, with url
```

The first deployment takes a minute or two: ECS pulls the image, the Lambda upserts the Cloudflare
A record `demo-api` to the new task IP (TTL 60), and Caddy gets or reuses a certificate. Later
deployments still replace the task briefly, but there is no idle or 60-minute shutdown.

## Lifecycle rules

- `desiredCount` remains 1. The idle sweep is disabled and `sweep()` is a no-op when
  `DEMO_ALWAYS_ON=true`.
- Each browser or phone call is still capped at five minutes. Browser and phone sessions share the
  three-call admission limit, so always-on infrastructure does not create unlimited model spend.
- Deploy only with no active calls; task replacement cuts live media.

## Inbound phone calling

After deploying with both Twilio secrets, open the Twilio Console and configure the voice-capable
agent number:

- **A call comes in:** Webhook, HTTP POST
- **URL:** `https://demo-api.dibbayajyoti.com/api/telephony/incoming`

The endpoint validates Twilio's signature and account SID, applies shared admission control, and
returns `<Connect><Stream>` with a single-use stream token. Phone reports contain `transport:
twilio`; caller/callee numbers, audio, and transcripts are not written to DynamoDB.

## Design choices

- **Cert storage: EFS (Standard, multi-AZ) mounted at `/data`.** Caddy keeps its certs there, so a
  restarted task reuses the certificate instead of asking Let's Encrypt again. Without that, each
  start issues a cert for the same name, and Let's Encrypt allows 5 per exact domain per week.
  Standard EFS, not One Zone, because the task can land in either subnet. Storage is a few KB.
- **WebRTC UDP 1024-65535 open to 0.0.0.0/0.** aiortc picks random UDP ports, so the whole
  ephemeral range is open. This is the cost of having no TURN server. Tighten it once the app
  pins a port range. Twilio media uses secure WebSockets on TCP 443 instead.
- **Caddy image via ECR Public mirror** (`public.ecr.aws/docker/library/caddy:2`) to avoid Docker
  Hub anonymous pull limits from Fargate IPs. Override with the `CaddyImage` parameter.

## Cost estimate (us-east-1, approximate, check current pricing)

| Item | Monthly baseline | Usage |
|---|---:|---|
| Fargate x86_64 0.5 vCPU / 1 GB, always on | about $18.25 | same |
| Public IPv4 on the task | about $3.65 | same |
| EFS, ECR (about 8 GB for 5 images), logs | about $1 | log volume |
| Secrets Manager | $0.40 per secret | same |
| Lambda + disabled sweep | free tier | request volume |
| Cloudflare DNS | free | free |
| Nova 2 Sonic | $0 idle | per-audio-minute, see Bedrock pricing |
| Twilio | $0 idle | number rental, calls, and media; see Twilio pricing |

Always-on Fargate plus its public IP is about **$22/month**, before storage and usage.

## Superadmin summary (`GET /admin/summary`)

Per-call history, totals and AWS spend for the demo, served by the control Function URL.

Read the admin token (generated by CloudFormation, stored in `voiceai/admin-token`):

```bash
aws secretsmanager get-secret-value --secret-id voiceai/admin-token --query SecretString --output text --region us-east-1
```

Call it with the token as a bearer header:

```bash
curl -H "Authorization: Bearer $(aws secretsmanager get-secret-value --secret-id voiceai/admin-token --query SecretString --output text --region us-east-1)" "$CONTROL/admin/summary"
```

The response has `backend`, `totals` (calls, minutes, est cost, p50/p95 per-turn ms), the 100 most
recent `calls`, and `aws_cost` (month to date, last 30 days, top 8 services). `aws_cost` is
**account-wide**: no cost-allocation tag is set up, so it includes everything else in the account.
If Cost Explorer is unavailable, `aws_cost.source` is `unavailable` and `error` says why.

Cost notes:

- Cost Explorer charges **$0.01 per request**. The Lambda caches `aws_cost` for 6 hours, so the
  admin page costs at most about $0.02 per 6 hours (two requests per refresh).
- DynamoDB table `voiceai-demo-calls` is on-demand (PAY_PER_REQUEST). At demo volume it is
  effectively free. Rows expire through the `ttl` attribute.
- The admin token is cached in the Lambda. After rotating the secret, wait for a Lambda cold start
  (or redeploy) before the new value is accepted.

## Traffic events and public reports

- `POST $CONTROL/track` stores page views, call starts and completions, and share or open events
  in DynamoDB `voiceai-demo-events` (rows expire after 180 days). It needs the header
  `X-Track-Secret`, and it returns 401 without the right value.
- `GET $CONTROL/report/{share_id}` is public and cached for an hour. It serves one finished call by
  the random hex suffix of its `call_id` (GSI `share_id-index` on `voiceai-demo-calls`).
- `/admin/summary` adds a `traffic` block: page views, unique visitors, calls, shares by channel,
  UTM sources, per-country counts and the last 500 located events. Raw IP addresses are never
  stored.

Read the track secret:

```bash
aws secretsmanager get-secret-value --secret-id voiceai/track-secret --query SecretString --output text --region us-east-1
```

Set the same value as the site server environment variable `TRACK_SECRET` (server-side only, never
`NEXT_PUBLIC_*`). Without it the frontend cannot send events.

## Teardown

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name voiceai-demo
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name voiceai-demo
aws s3 rb s3://voiceai-demo-artifacts-<account-id> --force
aws secretsmanager delete-secret --region us-east-1 --secret-id voiceai/cloudflare-dns-token # optional
aws secretsmanager delete-secret --region us-east-1 --secret-id voiceai/twilio-account-sid   # optional
aws secretsmanager delete-secret --region us-east-1 --secret-id voiceai/twilio-auth-token    # optional
```

Also remove the `demo-api` A record in Cloudflare. The stack does not delete it.
The ECR repo is emptied on delete (`EmptyOnDelete`).

## Tests

```bash
uv run python -m pytest deploy/aws/control -q
```
