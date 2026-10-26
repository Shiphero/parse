"""Deploy the POC using the infra-owned ECS service as the configuration template.

GitHub Actions owns application task revisions; Terraform must ignore changes to
the service's task_definition. No database or provider secret values reach CI.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile


TASK_FIELDS = {'family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions',
               'volumes', 'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory',
               'pidMode', 'ipcMode', 'proxyConfiguration', 'inferenceAccelerators',
               'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection'}

# The dedicated migration role's RunTask policy permits this exact family.
MIGRATION_FAMILY = 'parse-migration'


def aws(*args, payload=None):
    command = ['aws', 'ecs', *args, '--output', 'json', '--no-cli-pager']
    if payload is None:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    else:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
            json.dump(payload, file)
            file.flush()
            result = subprocess.run([*command, '--cli-input-json', 'file://' + file.name],
                                    check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def definition(current, image, migration=False):
    if '@sha256:' not in image:
        raise ValueError('Deploy an immutable ECR image digest.')
    result = {key: copy.deepcopy(value) for key, value in current.items() if key in TASK_FIELDS}
    if result.get('networkMode') != 'awsvpc' or 'FARGATE' not in result.get('requiresCompatibilities', []):
        raise ValueError('This deployment expects a Fargate awsvpc task.')
    if result.get('runtimePlatform', {}).get('cpuArchitecture', 'X86_64') != 'X86_64':
        raise ValueError('The workflow builds linux/amd64; use an X86_64 task definition.')
    containers = {c['name']: c for c in result['containerDefinitions']}
    api_name = 'parse' if 'parse' in containers else 'api'
    if set(containers) != {api_name, 'worker'}:
        raise ValueError('Expected an api (or parse) container and a worker container.')
    for container in containers.values():
        container['image'] = image
        container['essential'] = True
        container.pop('entryPoint', None)
    containers[api_name]['command'] = ['uvicorn', 'routing_guides.api:app', '--host', '0.0.0.0', '--port', '8000']
    containers['worker']['command'] = ['python', '-m', 'routing_guides.worker']
    if migration:
        result['family'] = MIGRATION_FAMILY
        api = containers[api_name]
        api['command'] = ['python', '-m', 'routing_guides.bootstrap']
        for key in ('healthCheck', 'dependsOn', 'portMappings'):
            api.pop(key, None)
        result['containerDefinitions'] = [api]
    return result


def service(cluster, name):
    response = aws('describe-services', '--cluster', cluster, '--services', name)
    if response.get('failures') or len(response.get('services', [])) != 1:
        raise RuntimeError('ECS service not found. Provision the service with Terraform first.')
    return response['services'][0]


def prepare(cluster, name, image, task_definition_file=None):
    """Use the deployment role to inspect the service and register the migration definition."""
    current_service = service(cluster, name)
    if current_service.get('deploymentController', {}).get('type', 'ECS') != 'ECS':
        raise ValueError('An ECS rolling deployment service is required.')
    original = current_service['taskDefinition']
    task = aws('describe-task-definition', '--task-definition', original)['taskDefinition']
    if task_definition_file:
        configured = json.loads(Path(task_definition_file).read_text())
        if configured.get('family') != task.get('family'):
            raise ValueError('The configured task family must match the service task family.')
        task = configured
    production = definition(task, image)
    migration = definition(task, image, migration=True)
    ports = {(container['name'], port['containerPort'])
             for container in production['containerDefinitions']
             for port in container.get('portMappings', [])}
    for target in current_service.get('loadBalancers', []):
        if (target['containerName'], target['containerPort']) not in ports:
            raise ValueError('Service load balancer mapping does not match the task. '
                             'Match the ALB container name and port to the task before deploying.')
    migration_arn = aws('register-task-definition', payload=migration)['taskDefinition']['taskDefinitionArn']
    request = {'cluster': cluster, 'taskDefinition': migration_arn, 'launchType': 'FARGATE',
               'networkConfiguration': current_service['networkConfiguration'], 'count': 1,
               'platformVersion': current_service.get('platformVersion', 'LATEST')}
    return {'cluster': cluster, 'service': name, 'original_task_definition': original,
            'desired_count': max(1, current_service.get('desiredCount', 1)),
            'production': production, 'migration_request': request, 'migration_succeeded': False}


def migrate(plan):
    """Use only RunTask, DescribeTasks and StopTask with the dedicated migration role."""
    plan['migration_succeeded'] = False
    cluster = plan['cluster']
    request = plan['migration_request']
    started = aws('run-task', payload=request)
    if started.get('failures') or len(started.get('tasks', [])) != 1:
        raise RuntimeError('Migration task could not start. Check ECS task events.')
    migration_task = started['tasks'][0]['taskArn']
    print('Migration task:', migration_task, flush=True)
    try:
        aws('wait', 'tasks-stopped', '--cluster', cluster, '--tasks', migration_task)
    except BaseException:
        aws('stop-task', '--cluster', cluster, '--task', migration_task, '--reason', 'Migration wait interrupted')
        raise
    stopped = aws('describe-tasks', '--cluster', cluster, '--tasks', migration_task)
    tasks = stopped.get('tasks', [])
    containers = tasks[0].get('containers', []) if tasks else []
    if len(containers) != 1 or containers[0].get('exitCode') != 0:
        raise RuntimeError('Migration failed. Service was not updated; inspect the migration task logs.')
    plan['migration_succeeded'] = True


def deploy(plan):
    """Switch back to the deployment role; never update a service before migration success."""
    if plan.get('migration_succeeded') is not True:
        raise RuntimeError('A successful migration is required before deployment.')
    cluster, name = plan['cluster'], plan['service']
    if service(cluster, name)['taskDefinition'] != plan['original_task_definition']:
        raise RuntimeError('Service changed during migration; refusing to overwrite another deployment.')
    arn = aws('register-task-definition', payload=plan['production'])['taskDefinition']['taskDefinitionArn']
    aws('update-service', '--cluster', cluster, '--service', name, '--task-definition', arn,
        '--desired-count', str(plan['desired_count']))
    aws('wait', 'services-stable', '--cluster', cluster, '--services', name)
    final = service(cluster, name)
    if final['taskDefinition'] != arn or final.get('runningCount', 0) < 1:
        raise RuntimeError('Deployment did not stay on the requested revision; check rollback events.')
    print('Deployed:', arn)


def save_plan(path, plan):
    """Keep phase handoff data on the ephemeral runner, never in workflow outputs."""
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temporary:
        try:
            json.dump(plan, temporary)
            temporary.flush()
            os.replace(temporary.name, path)
        finally:
            Path(temporary.name).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'migrate', 'deploy'))
    parser.add_argument('--state', type=Path, required=True, help='Runner-local phase handoff file')
    args = parser.parse_args(argv)
    if args.phase == 'prepare':
        args.state.unlink(missing_ok=True)
        plan = prepare(os.environ['ECS_CLUSTER'], os.environ['ECS_SERVICE'], os.environ['IMAGE'],
                       os.environ.get('TASK_DEFINITION_FILE'))
        save_plan(args.state, plan)
    else:
        plan = json.loads(args.state.read_text())
        if args.phase == 'migrate':
            # A failed retry must not leave an earlier success receipt usable by deploy.
            plan['migration_succeeded'] = False
            save_plan(args.state, plan)
            migrate(plan)
            save_plan(args.state, plan)
        else:
            deploy(plan)


if __name__ == '__main__':
    main()
