# AWS foundation decision

Date: 2026-10-14. Scope: local artifact preparation, not deployment.

Use **Amazon ECS on Fargate with JSON CloudFormation**, for one HTTP container
behind an existing HTTPS Application Load Balancer. Require an existing VPC,
private subnets, ALB/listener/security group, DNS/certificate, execution and task
roles, ECR image and any runtime secrets. This first slice does not provision
account infrastructure. Those dependencies are named parameters, not guessed IDs.
Support is limited to the standard commercial AWS partition and Linux X86_64.

Fargate keeps host management outside the application workflow and accommodates
both supported application families through a production container image. EC2
would add host patching and capacity management; EKS adds a cluster and Kubernetes
operations beyond this release. App Runner would be simpler for some HTTP apps,
but ECS exposes the network, task, identity and load-balancer contracts explicitly,
which better fits this foundation's review requirements. This is a scope decision,
not a claim that Fargate is always the least expensive option.

CloudFormation provides an AWS-native, reviewable document and packaged local
resource schemas via cfn-lint. JSON avoids another template language/toolchain.
Terraform could be appropriate later; supporting two formats now would duplicate
validation and maintenance. We generate no deployment shell commands or cloud API
actions, and do not use credentials merely to prepare or validate artifacts.

## Template contract

- ECS cluster, Fargate task/service, log group, app security group, IP target group
  and a host-specific rule on a user-selected existing HTTPS listener.
- `awsvpc`, no public task IP, ALB-security-group-only ingress, explicit outbound
  access requiring operator review, and an existing private subnet arrangement.
- Image pinned by SHA-256 digest in private ECR; production Linux X86_64 image,
  port and health route need independent verification. No development Dockerfile
  is promoted to production by this feature.
- Initial capacity: one task, 0.25 vCPU/512 MiB; deployment circuit breaker and
  14-day retained logs. These are explicit review defaults, not an HA/SLA claim.
- Separate existing execution and application roles. No IAM resource is generated.
  Optional Secrets Manager mappings use environment variable names from the local
  `aws-runtime.json`; each ARN is a required parameter without a default.
- No database or volume is generated. Durable database, backups, migrations,
  uploads/static assets, scaling and production server configuration stay explicit
  prerequisites. Local SQLite and disposable Postgres are not durable cloud storage.

Reusing an ALB needs care: verify HTTPS, VPC membership, security group, certificate,
DNS and an unused priority, and ensure the hostname rule does not shadow an existing
application. Local schema checks cannot inspect those facts. Private task subnets
need NAT or suitable ECR/S3/CloudWatch/Secrets Manager access. Review all costs:
Fargate runtime, ALB capacity, NAT/endpoints, data transfer, ECR, logs, secrets and
external persistence. No spending occurs through this feature.

## Official references checked

- [Fargate task networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html): awsvpc networking and dependency connectivity.
- [CloudFormation ECS task definition](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ecs-taskdefinition.html): Fargate network/task schema.
- [ECS load-balancer configuration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecs-service-loadbalancer.html): IP target groups with awsvpc tasks.
- [Execution-role responsibilities](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html): image pull, logging, secret retrieval and applicable KMS permissions, distinct from application identity.
- [Secret references](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecs-taskdefinition-secret.html): names and source ARNs, not plaintext values.
- [Private-subnet egress](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/networking-outbound.html): outbound access options and NAT considerations.
- [cfn-lint](https://github.com/aws-cloudformation/cfn-lint): local schema validation is best-effort and cannot prove deployment success.
- [Fargate pricing drivers](https://aws.amazon.com/fargate/pricing/): CPU/memory/storage runtime charges; no fixed price estimate is inferred here.
