# Production layout (NOT deployed by this repo)

This is the reference shape for a production deployment. The DEMO stack in `demo.yaml`
does not use any of it. Nothing here has been built or run.

- **Ingress:** ALB (HTTPS, ACM cert) to ECS Fargate tasks on port 8000. WAF in front.
- **Compute:** ECS Fargate service per API/worker. Target-tracking autoscaling on CPU and ALB
  request count, min 2 tasks across 2 AZs.
- **Database:** RDS PostgreSQL with pgvector (the knowledge store in `deploy/db/001_knowledge.sql`).
  Multi-AZ, encrypted, backups on. Connection string from Secrets Manager.
- **Object storage:** S3 for knowledge sources, with a bucket policy limited to the task role.
- **Secrets:** Secrets Manager for DB, OpenRouter, Vercel and other keys. Injected through the
  task definition `secrets:` block, not environment files.
- **WebRTC:** TURN server (coturn on Fargate or a managed TURN service) for clients behind strict
  NAT. Without it the demo's open UDP range is the only media path.
- **Media and voice tier:** STT/TTS gRPC services (`services/stt`, `services/tts`) on GPU
  instances, separate from the API.
- **Delivery:** CodePipeline (source, CodeBuild image build to ECR, deploy to ECS with blue/green
  through CodeDeploy). See the aws-deployment skill for the pipeline shape.
- **Observability:** CloudWatch logs (retention set per env), OTel traces to Logfire, Prometheus
  `/metrics` scraped by the platform.
- **Cost controls:** budgets and alarms per environment; scale-to-min off-hours only where the
  SLA allows.
