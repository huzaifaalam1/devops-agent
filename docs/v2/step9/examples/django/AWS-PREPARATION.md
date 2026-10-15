# AWS preparation — review required

This is a local CloudFormation foundation, not a verified deployment.

- Supply every template parameter without a default; select and confirm the deployment account and region separately.
- Build and independently verify a production Linux X86_64 image in ECR. Development npm/runserver images are not production evidence.
- Verify VPC/subnet membership, HTTPS listener protocol, certificate/DNS, ALB security group, unique hostname rule and unused rule priority.
- Verify private-subnet egress (NAT or ECR/S3/logs/secrets endpoints), execution-role access and separate least-privilege task-role trust.
- Review all runtime variables and Secrets Manager mappings. No dotenv values are copied; aws-runtime.json lists names only.
- Verify the readiness route returns 200 with ALB health-check Host headers; authentication must remain intact.
- Review availability, scaling, CPU/memory, outbound rules, log retention and budget before a separate deployment review.
- Use a production WSGI/ASGI server, DEBUG=False, appropriate ALLOWED_HOSTS/CSRF/proxy configuration and a static/media strategy.
- Replace disposable SQLite/PostgreSQL with an explicitly reviewed durable database and backups. Plan migrations separately; no migration command is generated.

The template creates an ECS cluster/service/task, task security group, target group,
host-specific rule on an existing HTTPS listener, and a retained log group.
Existing VPC, private subnets, ALB, DNS/certificate, roles, ECR image and secrets
are required. No resources have been created. No deployment command is supplied.

Secret mapping input example (names only):
```json
{"secret_names": ["DJANGO_SECRET_KEY", "DATABASE_URL"]}
```
Save relevant names in aws-runtime.json before generating. Each name becomes a
required ARN parameter. Existing output files are preserved; do not overwrite
manual edits. Review any edited template with your own infrastructure workflow.

Local schema validation cannot verify image behavior, IAM permissions, resource
existence, network reachability, costs or production readiness.
