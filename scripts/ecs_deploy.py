"""Deploy the POC using the infra-owned ECS service as the configuration template.

GitHub Actions owns application task revisions; Terraform must ignore changes to
the service's task_definition. No database or provider secret values reach CI.
"""
import copy
import json
import os
import subprocess
import tempfile


TASK_FIELDS = {'family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions',
               'volumes', 'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory',
               'pidMode', 'ipcMode', 'proxyConfiguration', 'inferenceAccelerators',
               'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection'}


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
    if set(containers) != {'api', 'worker'}:
        raise ValueError('Expected containers named api and worker.')
    for container in containers.values():
        container['image'] = image
        container['essential'] = True
        container.pop('entryPoint', None)
    containers['api']['command'] = ['uvicorn', 'routing_guides.api:app', '--host', '0.0.0.0', '--port', '8000']
    containers['worker']['command'] = ['python', '-m', 'routing_guides.worker']
    if migration:
        result['family'] += '-migration'
        api = containers['api']
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


def deploy(cluster, name, image):
    current_service = service(cluster, name)
    if current_service.get('deploymentController', {}).get('type', 'ECS') != 'ECS':
        raise ValueError('An ECS rolling deployment service is required.')
    original = current_service['taskDefinition']
    task = aws('describe-task-definition', '--task-definition', original)['taskDefinition']
    production = definition(task, image)
    migration = definition(task, image, migration=True)
    migration_arn = aws('register-task-definition', payload=migration)['taskDefinition']['taskDefinitionArn']
    request = {'cluster': cluster, 'taskDefinition': migration_arn, 'launchType': 'FARGATE',
               'networkConfiguration': current_service['networkConfiguration'], 'count': 1,
               'platformVersion': current_service.get('platformVersion', 'LATEST')}
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
    if service(cluster, name)['taskDefinition'] != original:
        raise RuntimeError('Service changed during migration; refusing to overwrite another deployment.')
    arn = aws('register-task-definition', payload=production)['taskDefinition']['taskDefinitionArn']
    aws('update-service', '--cluster', cluster, '--service', name, '--task-definition', arn,
        '--desired-count', str(max(1, current_service.get('desiredCount', 1))))
    aws('wait', 'services-stable', '--cluster', cluster, '--services', name)
    final = service(cluster, name)
    if final['taskDefinition'] != arn or final.get('runningCount', 0) < 1:
        raise RuntimeError('Deployment did not stay on the requested revision; check rollback events.')
    print('Deployed:', arn)


if __name__ == '__main__':
    deploy(os.environ['ECS_CLUSTER'], os.environ['ECS_SERVICE'], os.environ['IMAGE'])
