import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ecs_deploy as deploy

IMAGE = '123456789012.dkr.ecr.us-east-1.amazonaws.com/parse@sha256:' + 'a' * 64


def task():
    return {'family': 'parse', 'networkMode': 'awsvpc', 'requiresCompatibilities': ['FARGATE'],
            'taskDefinitionArn': 'old', 'revision': 4, 'runtimePlatform': {'cpuArchitecture': 'X86_64'},
            'volumes': [{'name': 'documents', 'efsVolumeConfiguration': {'fileSystemId': 'fs-example'}}],
            'containerDefinitions': [dict(name=name, image='old', healthCheck={'command': ['CMD', 'health']},
                secrets=[{'name': 'DATABASE_URL', 'valueFrom': 'secret-arn'}],
                mountPoints=[{'sourceVolume': 'documents', 'containerPath': '/data'}],
                portMappings=[{'containerPort': 8000}], dependsOn=[]) for name in ('api', 'worker')]}


class DeploymentTests(unittest.TestCase):
    def test_migration_is_single_process_with_shared_storage_and_secret_references(self):
        original = task()
        before = copy.deepcopy(original)
        result = deploy.definition(original, IMAGE, migration=True)
        self.assertEqual(original, before)
        self.assertNotIn('revision', result)
        self.assertEqual(len(result['containerDefinitions']), 1)
        container = result['containerDefinitions'][0]
        self.assertEqual(container['command'], ['python', '-m', 'routing_guides.bootstrap'])
        self.assertEqual(container['secrets'], original['containerDefinitions'][0]['secrets'])
        self.assertEqual(result['volumes'], original['volumes'])
        self.assertNotIn('dependsOn', container)
        self.assertNotIn('healthCheck', container)

    def test_migration_failure_never_updates_service(self):
        calls = []
        service = {'taskDefinition': 'old', 'networkConfiguration': {}, 'desiredCount': 1}

        def aws(*args, **kwargs):
            calls.append(args[0])
            return {'describe-services': {'services': [service]},
                    'describe-task-definition': {'taskDefinition': task()},
                    'register-task-definition': {'taskDefinition': {'taskDefinitionArn': 'migration'}},
                    'run-task': {'tasks': [{'taskArn': 'migration-task'}]},
                    'wait': {}, 'describe-tasks': {'tasks': [{'containers': [{'exitCode': 1}]}]}}[args[0]]

        with patch.object(deploy, 'aws', side_effect=aws):
            with self.assertRaisesRegex(RuntimeError, 'Migration failed'):
                deploy.deploy('cluster', 'service', IMAGE)
        self.assertNotIn('update-service', calls)

    def test_success_updates_both_containers_only_after_migration_and_detects_rollback(self):
        for rolled_back in (False, True):
            calls, registrations = [], []
            service = {'taskDefinition': 'old', 'networkConfiguration': {}, 'desiredCount': 1, 'runningCount': 1}

            def aws(*args, payload=None):
                calls.append(args[0])
                if args[0] == 'describe-services': return {'services': [dict(service)]}
                if args[0] == 'describe-task-definition': return {'taskDefinition': task()}
                if args[0] == 'register-task-definition':
                    registrations.append(payload)
                    return {'taskDefinition': {'taskDefinitionArn': payload['family']}}
                if args[0] == 'run-task': return {'tasks': [{'taskArn': 'migration-task'}]}
                if args[0] == 'describe-tasks': return {'tasks': [{'containers': [{'exitCode': 0}]}]}
                if args[0] == 'update-service': service['taskDefinition'] = 'old' if rolled_back else 'parse'
                return {}

            with patch.object(deploy, 'aws', side_effect=aws):
                if rolled_back:
                    with self.assertRaisesRegex(RuntimeError, 'requested revision'):
                        deploy.deploy('cluster', 'service', IMAGE)
                else:
                    deploy.deploy('cluster', 'service', IMAGE)
            self.assertLess(calls.index('describe-tasks'), calls.index('update-service'))
            self.assertEqual([c['image'] for c in registrations[-1]['containerDefinitions']], [IMAGE, IMAGE])
