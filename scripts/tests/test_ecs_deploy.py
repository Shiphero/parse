import copy
import json
import sys
import tempfile
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
    def test_first_deployment_replaces_placeholder_and_migrates_before_service_update(self):
        template = Path(__file__).resolve().parents[2] / 'deploy/dev-task-definition.json'
        current = {'taskDefinition': 'placeholder', 'desiredCount': 0,
                   'networkConfiguration': {'awsvpcConfiguration': {'subnets': ['subnet-existing']}},
                   'loadBalancers': [{'containerName': 'parse', 'containerPort': 8000}]}
        calls, registrations = [], []
        phase = 'prepare'
        allowed = {'prepare': {'describe-services', 'describe-task-definition', 'register-task-definition'},
                   'migrate': {'run-task', 'wait', 'describe-tasks', 'stop-task'},
                   'deploy': {'describe-services', 'register-task-definition', 'update-service', 'wait'}}

        def aws(*args, payload=None):
            self.assertIn(args[0], allowed[phase], f'{phase} used an operation outside its role')
            calls.append(args[0])
            if args[0] == 'describe-services':
                return {'services': [dict(current)]}
            if args[0] == 'describe-task-definition':
                return {'taskDefinition': {'family': 'dev-parse', 'containerDefinitions': []}}
            if args[0] == 'register-task-definition':
                registrations.append(payload)
                return {'taskDefinition': {'taskDefinitionArn': payload['family']}}
            if args[0] == 'run-task':
                self.assertEqual(payload['networkConfiguration'], current['networkConfiguration'])
                return {'tasks': [{'taskArn': 'migration-task'}]}
            if args[0] == 'describe-tasks':
                return {'tasks': [{'containers': [{'exitCode': 0}]}]}
            if args[0] == 'update-service':
                self.assertEqual(args[-2:], ('--desired-count', '1'))
                current.update(taskDefinition='dev-parse', runningCount=1)
            return {}

        with patch.object(deploy, 'aws', side_effect=aws):
            plan = deploy.prepare('cluster', 'service', IMAGE, template)
            phase = 'migrate'
            deploy.migrate(plan)
            phase = 'deploy'
            deploy.deploy(plan)

        self.assertLess(calls.index('describe-tasks'), calls.index('update-service'))
        migration, production = registrations
        self.assertEqual(migration['family'], 'parse-migration')
        self.assertEqual(len(migration['containerDefinitions']), 1)
        self.assertEqual(migration['containerDefinitions'][0]['command'],
                         ['python', '-m', 'routing_guides.bootstrap'])
        self.assertNotIn('healthCheck', migration['containerDefinitions'][0])
        self.assertNotIn('portMappings', migration['containerDefinitions'][0])
        self.assertEqual(migration['volumes'], production['volumes'])
        for container in production['containerDefinitions']:
            self.assertEqual(container['image'], IMAGE)
            self.assertEqual(container['mountPoints'][0]['containerPath'], '/data')
            self.assertEqual({secret['name'] for secret in container['secrets']},
                             {'DATABASE_URL', 'ANTHROPIC_API_KEY', 'JEV_API_KEY'})
            self.assertTrue(all(secret['valueFrom'].startswith('arn:aws:ssm:')
                                for secret in container['secrets']))

    def test_wrong_family_or_alb_target_fails_before_any_aws_mutation(self):
        for wrong_family in (False, True):
            with self.subTest(wrong_family=wrong_family):
                current = {'taskDefinition': 'old',
                           'loadBalancers': [{'containerName': 'placeholder', 'containerPort': 80}]}
                configured = task()
                if wrong_family:
                    configured['family'] = 'another-service'
                with patch.object(Path, 'read_text', return_value=json.dumps(configured)), \
                     patch.object(deploy, 'aws', side_effect=[{'services': [current]},
                                                            {'taskDefinition': task()}]) as aws:
                    with self.assertRaisesRegex(ValueError, 'family' if wrong_family else 'load balancer'):
                        deploy.prepare('cluster', 'service', IMAGE, 'template.json')
                self.assertEqual([call.args[0] for call in aws.call_args_list],
                                 ['describe-services', 'describe-task-definition'])

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
            plan = deploy.prepare('cluster', 'service', IMAGE)
            with self.assertRaisesRegex(RuntimeError, 'Migration failed'):
                deploy.migrate(plan)
            with self.assertRaisesRegex(RuntimeError, 'successful migration'):
                deploy.deploy(plan)
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
                plan = deploy.prepare('cluster', 'service', IMAGE)
                deploy.migrate(plan)
                if rolled_back:
                    with self.assertRaisesRegex(RuntimeError, 'requested revision'):
                        deploy.deploy(plan)
                else:
                    deploy.deploy(plan)
            self.assertLess(calls.index('describe-tasks'), calls.index('update-service'))
            self.assertEqual([c['image'] for c in registrations[-1]['containerDefinitions']], [IMAGE, IMAGE])

    def test_deploy_without_migration_receipt_makes_no_aws_calls(self):
        for receipt in (None, False, 'true'):
            with self.subTest(receipt=receipt), patch.object(deploy, 'aws') as aws:
                with self.assertRaisesRegex(RuntimeError, 'successful migration'):
                    deploy.deploy({'migration_succeeded': receipt})
                aws.assert_not_called()

    def test_service_change_during_migration_blocks_registration_and_update(self):
        plan = {'cluster': 'cluster', 'service': 'service', 'original_task_definition': 'original',
                'migration_succeeded': True}
        with patch.object(deploy, 'aws', return_value={'services': [{'taskDefinition': 'changed'}]}) as aws:
            with self.assertRaisesRegex(RuntimeError, 'Service changed'):
                deploy.deploy(plan)
            aws.assert_called_once_with('describe-services', '--cluster', 'cluster', '--services', 'service')

    def test_interrupted_migration_stops_its_task_without_service_operations(self):
        plan = {'cluster': 'cluster', 'migration_request': {'taskDefinition': 'parse-migration:1'}}
        with patch.object(deploy, 'aws', side_effect=[{'tasks': [{'taskArn': 'migration-task'}]},
                                                    TimeoutError('wait expired'), {}]) as aws:
            with self.assertRaises(TimeoutError):
                deploy.migrate(plan)
            self.assertFalse(plan['migration_succeeded'])
            self.assertEqual([call.args[0] for call in aws.call_args_list], ['run-task', 'wait', 'stop-task'])
            self.assertIn('migration-task', aws.call_args.args)

    def test_phase_handoff_is_persisted_and_failed_retry_invalidates_old_success(self):
        plan = {'cluster': 'cluster', 'service': 'service', 'migration_succeeded': False}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'plan.json'
            with patch.dict('os.environ', ECS_CLUSTER='cluster', ECS_SERVICE='service', IMAGE=IMAGE), \
                 patch.object(deploy, 'prepare', return_value=plan):
                deploy.main(['prepare', '--state', str(state)])
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)

            def succeed(plan):
                plan['migration_succeeded'] = True

            with patch.object(deploy, 'migrate', side_effect=succeed):
                deploy.main(['migrate', '--state', str(state)])
            with patch.object(deploy, 'deploy') as update:
                deploy.main(['deploy', '--state', str(state)])
                self.assertTrue(update.call_args.args[0]['migration_succeeded'])

            with patch.object(deploy, 'migrate', side_effect=RuntimeError('migration failed')):
                with self.assertRaisesRegex(RuntimeError, 'migration failed'):
                    deploy.main(['migrate', '--state', str(state)])
            self.assertFalse(json.loads(state.read_text())['migration_succeeded'])
            with patch.object(deploy, 'aws') as aws:
                with self.assertRaisesRegex(RuntimeError, 'successful migration'):
                    deploy.main(['deploy', '--state', str(state)])
                aws.assert_not_called()
