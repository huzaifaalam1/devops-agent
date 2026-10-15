"""Local-only Fargate/CloudFormation preparation; no AWS SDK or cloud execution."""
import difflib
import json
import os
from pathlib import Path
import re
import tempfile

from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.understanding import read_text
from agent.safety import Journal, authorize, check_target, project_lock, repository_fingerprint, sha

FILES=('aws-template.json','aws-readiness.json','AWS-PREPARATION.md')

def encode(value):return json.dumps(value,indent=2,sort_keys=True)+'\n'
def ref(name):return {'Ref':name}
def attr(name,key):return {'Fn::GetAtt':[name,key]}

def secret_names(root):
    path=root/'aws-runtime.json'
    if not path.exists() and not path.is_symlink():return []
    data=json.loads(read_text(root,'aws-runtime.json'))
    if not isinstance(data,dict) or set(data)!={'secret_names'}:
        raise ValueError('aws-runtime.json accepts only secret_names, never secret values.')
    names=data['secret_names']
    if not isinstance(names,list) or len(names)>30 or any(not isinstance(n,str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,63}',n) for n in names) or len(set(names))!=len(names):
        raise ValueError('secret_names must be at most 30 unique uppercase environment variable names.')
    return sorted(names)

def template(port,names):
    parameters={
        'VpcId':{'Type':'AWS::EC2::VPC::Id'},
        'PrivateSubnetIds':{'Type':'List<AWS::EC2::Subnet::Id>','Description':'At least two private subnets in this VPC; provide NAT or required service endpoints.'},
        'AlbSecurityGroupId':{'Type':'AWS::EC2::SecurityGroup::Id'},
        'HttpsListenerArn':{'Type':'String','AllowedPattern':r'arn:aws:elasticloadbalancing:[a-z0-9-]+:[0-9]{12}:listener/app/.+'},
        'Hostname':{'Type':'String','AllowedPattern':r'[a-z0-9][a-z0-9.-]*\.[a-z]{2,}','Description':'Existing DNS name and TLS certificate on the selected HTTPS listener; never a wildcard.'},
        'RulePriority':{'Type':'Number','MinValue':1,'MaxValue':50000,'Description':'Unused listener rule priority; must be checked by the operator.'},
        'ImageUri':{'Type':'String','AllowedPattern':r'[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}','Description':'Prebuilt production Linux X86_64 image in private ECR, pinned by digest.'},
        'ExecutionRoleArn':{'Type':'String','AllowedPattern':r'arn:aws:iam::[0-9]{12}:role/.+','Description':'Existing ecs-tasks trust role with ECR pull, log write and selected secret/KMS permissions.'},
        'TaskRoleArn':{'Type':'String','AllowedPattern':r'arn:aws:iam::[0-9]{12}:role/.+','Description':'Existing least-privilege application role, separate from execution role.'},
        'ContainerPort':{'Type':'Number','Default':port,'MinValue':1,'MaxValue':65535},
        'HealthPath':{'Type':'String','AllowedPattern':r'/[A-Za-z0-9/_.-]*','Description':'An existing unauthenticated readiness route; verify ALB Host-header behavior.'},
    }
    secrets=[]
    for i,name in enumerate(names):
        key=f'RuntimeSecret{i}Arn';parameters[key]={'Type':'String','AllowedPattern':r'arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:.+','Description':f'Existing Secrets Manager secret for {name}; value never appears here.'}
        secrets.append({'Name':name,'ValueFrom':ref(key)})
    container={'Name':'app','Image':ref('ImageUri'),'Essential':True,'PortMappings':[{'ContainerPort':ref('ContainerPort'),'Protocol':'tcp'}],
        'LogConfiguration':{'LogDriver':'awslogs','Options':{'awslogs-group':ref('Logs'),'awslogs-region':ref('AWS::Region'),'awslogs-stream-prefix':'app'}}}
    if secrets:container['Secrets']=secrets
    return {'AWSTemplateFormatVersion':'2010-09-09','Description':'Review-only single HTTP service foundation. Requires production image and existing AWS prerequisites.',
        'Parameters':parameters,'Resources':{
        'Cluster':{'Type':'AWS::ECS::Cluster'},
        'Logs':{'Type':'AWS::Logs::LogGroup','DeletionPolicy':'Retain','UpdateReplacePolicy':'Retain','Properties':{'RetentionInDays':14}},
        'AppSecurityGroup':{'Type':'AWS::EC2::SecurityGroup','Properties':{'GroupDescription':'App ingress only from selected ALB security group','VpcId':ref('VpcId'),
            'SecurityGroupIngress':[{'IpProtocol':'tcp','FromPort':ref('ContainerPort'),'ToPort':ref('ContainerPort'),'SourceSecurityGroupId':ref('AlbSecurityGroupId')}],
            'SecurityGroupEgress':[{'IpProtocol':'-1','CidrIp':'0.0.0.0/0','Description':'Review outbound needs for ECR, logs, secrets and application dependencies.'}]}},
        'Task':{'Type':'AWS::ECS::TaskDefinition','Properties':{'RequiresCompatibilities':['FARGATE'],'NetworkMode':'awsvpc','Cpu':'256','Memory':'512',
            'RuntimePlatform':{'CpuArchitecture':'X86_64','OperatingSystemFamily':'LINUX'},'ExecutionRoleArn':ref('ExecutionRoleArn'),'TaskRoleArn':ref('TaskRoleArn'),'ContainerDefinitions':[container]}},
        'TargetGroup':{'Type':'AWS::ElasticLoadBalancingV2::TargetGroup','Properties':{'VpcId':ref('VpcId'),'Port':ref('ContainerPort'),'Protocol':'HTTP','TargetType':'ip','HealthCheckPath':ref('HealthPath'),'Matcher':{'HttpCode':'200'}}},
        'ListenerRule':{'Type':'AWS::ElasticLoadBalancingV2::ListenerRule','Properties':{'ListenerArn':ref('HttpsListenerArn'),'Priority':ref('RulePriority'),
            'Conditions':[{'Field':'host-header','Values':[ref('Hostname')]}],'Actions':[{'Type':'forward','TargetGroupArn':ref('TargetGroup')}]}},
        'Service':{'Type':'AWS::ECS::Service','DependsOn':['ListenerRule'],'Properties':{'Cluster':ref('Cluster'),'LaunchType':'FARGATE','PlatformVersion':'1.4.0','DesiredCount':1,'TaskDefinition':ref('Task'),
            'DeploymentConfiguration':{'DeploymentCircuitBreaker':{'Enable':True,'Rollback':True}},'HealthCheckGracePeriodSeconds':60,
            'NetworkConfiguration':{'AwsvpcConfiguration':{'AssignPublicIp':'DISABLED','Subnets':ref('PrivateSubnetIds'),'SecurityGroups':[ref('AppSecurityGroup')]}},
            'LoadBalancers':[{'ContainerName':'app','ContainerPort':ref('ContainerPort'),'TargetGroupArn':ref('TargetGroup')}]}}
        },'Outputs':{'ServiceArn':{'Value':ref('Service')},'LogGroup':{'Value':ref('Logs')}}}


def artifacts(root):
    analysis=detect_stack(scan_repo(str(root)));project=analysis['project']
    framework=project.get('framework') or ('Next.js' if 'Next.js app' in analysis.get('detected',[]) else None)
    if project['eligibility']!='eligible' or framework not in {'Next.js','Django'}:
        raise ValueError('AWS preparation requires an eligible single Next.js/npm or Django/pip application; resolve repository blockers first.')
    names=secret_names(root);django=framework=='Django';document=template(8000 if django else 3000,names)
    gaps=['Supply every template parameter without a default; select and confirm the deployment account and region separately.',
        'Build and independently verify a production Linux X86_64 image in ECR. Development npm/runserver images are not production evidence.',
        'Verify VPC/subnet membership, HTTPS listener protocol, certificate/DNS, ALB security group, unique hostname rule and unused rule priority.',
        'Verify private-subnet egress (NAT or ECR/S3/logs/secrets endpoints), execution-role access and separate least-privilege task-role trust.',
        'Review all runtime variables and Secrets Manager mappings. No dotenv values are copied; aws-runtime.json lists names only.',
        'Verify the readiness route returns 200 with ALB health-check Host headers; authentication must remain intact.',
        'Review availability, scaling, CPU/memory, outbound rules, log retention and budget before a separate deployment review.']
    if django:gaps += ['Use a production WSGI/ASGI server, DEBUG=False, appropriate ALLOWED_HOSTS/CSRF/proxy configuration and a static/media strategy.',
        'Replace disposable SQLite/PostgreSQL with an explicitly reviewed durable database and backups. Plan migrations separately; no migration command is generated.']
    else:gaps += ['Verify npm production build/start behavior, build-time NEXT_PUBLIC values, image contents and any writable cache or upload storage.']
    readiness={'schema_version':1,'framework':framework,'path':'ECS Fargate / CloudFormation','artifact_scope':'local preparation only','deployment_ready':False,'cloud_verified':False,
        'required_parameters':[key for key,value in document['Parameters'].items() if 'Default' not in value],
        'runtime_secret_names':names,'unresolved':gaps,'cost_drivers':['Fargate CPU/memory runtime','Existing ALB capacity','NAT/endpoints and data transfer','ECR storage','CloudWatch ingestion/retention','Secrets Manager','External database/storage'],
        'excluded':['Cloud API calls','Image build/push','IAM changes','VPC/ALB/DNS provisioning','Database creation or migrations','Deployment']}
    guide='# AWS preparation — review required\n\nThis is a local CloudFormation foundation, not a verified deployment.\n\n'+ '\n'.join('- '+item for item in gaps)+'\n\nThe template creates an ECS cluster/service/task, task security group, target group,\nhost-specific rule on an existing HTTPS listener, and a retained log group.\nExisting VPC, private subnets, ALB, DNS/certificate, roles, ECR image and secrets\nare required. No resources have been created. No deployment command is supplied.\n\nSecret mapping input example (names only):\n```json\n{"secret_names": ["DJANGO_SECRET_KEY", "DATABASE_URL"]}\n```\nSave relevant names in aws-runtime.json before generating. Each name becomes a\nrequired ARN parameter. Existing output files are preserved; do not overwrite\nmanual edits. Review any edited template with your own infrastructure workflow.\n\nLocal schema validation cannot verify image behavior, IAM permissions, resource\nexistence, network reachability, costs or production readiness.\n'
    return {'aws-template.json':encode(document),'aws-readiness.json':encode(readiness),'AWS-PREPARATION.md':guide},readiness


def propose(path):
    root=Path(path).resolve();plan={'status':'blocked','path':str(root),'changes':[],'preserved':[],'blockers':[],'purpose':'AWS artifacts only; no cloud writes','artifact_paths':list(FILES)}
    try:
        contents,readiness=artifacts(root)
        plan['readiness']=readiness
        for name,content in contents.items():
            target=check_target(root,name)
            if target.exists():
                if read_text(root,name)!=content:raise ValueError(f'{name} already exists with different content; preserve it and reconcile manually.')
                plan['preserved'].append(name);continue
            plan['changes'].append({'path':name,'operation':'create','before_sha256':None,'content':content,'diff':''.join(difflib.unified_diff([],content.splitlines(True),fromfile='/dev/null',tofile='b/'+name))})
        plan['inputs_sha256']=repository_fingerprint(root)
        if not plan['inputs_sha256']:raise ValueError('Repository inputs cannot be snapshotted.')
        plan['status']='ready' if plan['changes'] else 'unchanged';plan['id']=sha(encode(plan).encode())
    except (OSError,ValueError,TypeError) as error:
        plan.update(status='blocked',changes=[],blockers=[str(error)])
    return plan


def apply(plan):
    root=Path(plan['path'])
    with project_lock(root):
        if plan.get('status')!='ready' or propose(root)!=plan:raise ValueError('AWS proposal is stale or blocked; review again.')
        journal=Journal(root,'apply',authorize('apply',explicit=True));journal.snapshot(plan);created=[]
        try:
            for change in plan['changes']:
                target=check_target(root,change['path'])
                # Complete the file before exclusive publication; never replace an existing target.
                fd,temporary=tempfile.mkstemp(prefix='.aws-preparation-',dir=root)
                try:
                    with os.fdopen(fd,'w') as stream:stream.write(change['content']);stream.flush();os.fsync(stream.fileno())
                    os.link(temporary,target);created.append(change['path'])
                finally:Path(temporary).unlink(missing_ok=True)
            result={'success':True,'created':created,'session_id':journal.id,'deployment_ready':False,'notice':'AWS review artifacts written locally. No AWS resources created.'}
            journal.finish('applied',result);return result
        except BaseException:
            journal.finish('failed',{'created':created,'error':'Local artifact write interrupted. Preserve existing files and inspect this journal; no automatic overwrite or cloud operation occurred.'})
            raise


def validate(path):
    root=Path(path).resolve()
    result={'success':False,'deployment_ready':False,'cloud_verified':False,'phase':'aws_artifact_validation'}
    try:
        contents,readiness=artifacts(root)
        for name,expected in contents.items():
            check_target(root,name)
            if read_text(root,name)!=expected:raise ValueError(f'{name} is missing, changed or stale. Automatic validation covers only the exact generated foundation.')
        from importlib.metadata import version
        if version('cfn-lint')!='1.57.2':raise ValueError('Install the pinned aws-validation extra (cfn-lint==1.57.2).')
        from cfnlint.api import lint
        with tempfile.TemporaryDirectory(prefix='aws-schema-') as directory:
            config=Path(directory)/'config.json';config.write_text('{}')
            matches=lint(contents['aws-template.json'],config={'config_file':str(config),'regions':['us-east-1']})
        result.update(success=not matches,validator='cfn-lint 1.57.2',schema_region='us-east-1 (schema check only; not a deployment target)',
            findings=[{'rule':m.rule.id,'message':m.message} for m in matches],readiness=readiness,
            notice='Local artifact schema checks only. Account, permissions, production image and runtime remain unverified.')
    except (OSError,ValueError,ImportError) as error:result['error']=str(error)
    return result
