import time
import socket
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from textwrap import dedent
from tornado import gen
from tornado.concurrent import run_on_executor
from traitlets import Any, Integer, List, Unicode, default, Bool

from marathon import MarathonClient
from marathon.models.app import MarathonApp, MarathonHealthCheck
from marathon.models.container import MarathonContainerPortMapping, \
    MarathonContainer, MarathonContainerVolume, MarathonDockerContainer
from marathon.models.constraint import MarathonConstraint
from marathon.exceptions import NotFoundError
from jupyterhub.spawner import Spawner

# Updates the volume name to replace {username} with the actual user at run time
def default_format_volume_name(template, spawner):
    if template is None:
        return None
    return template.format(username=spawner.user.name)


class MarathonSpawner(Spawner):


    # Load the app image
    app_image = Unicode("jupyterhub/singleuser", config=True)

    # The command to run 
    app_cmd = Unicode("jupyter notebook", config=True)

    # This is the prefix in Martahon 
    app_prefix = Unicode(
        "jupyter",
        help=dedent(
            """
            Prefix for app names. The full app name for a particular
            user will be <prefix>/<username>.
            """
        )
    ).tag(config=True)

    user_web_port = Integer(0, help="Port that the Notebook is listening on").tag(config=True)
    user_ssh_port = Integer(0, help="SSH Port that the container is listening on").tag(config=True)
    # zeta_user_file are the users and their custom settings for installation in Zeta Architechure. If this is blank, defaults from Jupyter Hub are used for Mem, CPU, Ports, Image. If this is not blank, we will read from that file
    zeta_user_file = Unicode(
    "",
    help="Path to json file that includes users and per user settings"
    ).tag(config=True)


    no_user_file_fail = Bool(
    True,
    help="Is zeta_user_file is provided, but can't be opened fail. (Default). False loads defaults and tries to spawn"
    ).tag(config=True)

    # Marathon Server
    marathon_host = Unicode(
        u'',
        help="Hostname of Marathon server").tag(config=True)

    custom_env = List(
        [],
        help='Additional ENVs to add to the default. Format is a list of 1 record dictionary. [{key:val}]'
       ).tag(config=True)

    # Constraints in Marathon
    marathon_constraints = List(
        [],
        help='Constraints to be passed through to Marathon').tag(config=True)

    # Shared Notebook location
    shared_notebook_dir = Unicode(
    '', help="Shared Notebook location that users will get a link to in their notebook location - can be blank"
    ).tag(config=True)

    ports = List(
        [8888],
        help='Ports to expose externally'
        ).tag(config=True)

    volumes = List(
        [],
        help=dedent(
            """
            A list in Marathon REST API format for mounting volumes into the docker container.
            [
                {
                    "containerPath": "/foo",
                    "hostPath": "/bar",
                    "mode": "RW"
                }
            ]

            Note that using the template variable {username} in containerPath,
            hostPath or the name variable in case it's an external drive
            it will be replaced with the current user's name.
            """
        )
    ).tag(config=True)

    network_mode = Unicode(
        'BRIDGE',
        help="Enum of BRIDGE or HOST"
        ).tag(config=True)

    hub_ip_connect = Unicode(
        "",
        help="Public IP address of the hub"
        ).tag(config=True)

    hub_port_connect = Integer(
        -1,
        help="Public PORT of the hub"
        ).tag(config=True)

    format_volume_name = Any(
        help="""Any callable that accepts a string template and a Spawner
        instance as parameters in that order and returns a string.
        """
    ).tag(config=True)

    @default('format_volume_name')
    def _get_default_format_volume_name(self):
        return default_format_volume_name

    _executor = None
    @property
    def executor(self):
        cls = self.__class__
        if cls._executor is None:
            cls._executor = ThreadPoolExecutor(1)
        return cls._executor

    def __init__(self, *args, **kwargs):
        super(MarathonSpawner, self).__init__(*args, **kwargs)
        self.marathon = MarathonClient(self.marathon_host)

    @property
    def container_name(self):
        return '/%s/%s' % (self.app_prefix, self.user.name)

    def get_state(self):
        state = super(MarathonSpawner, self).get_state()
        state['container_name'] = self.container_name
        return state

    def load_state(self, state):
        if 'container_name' in state:
            pass

    def get_health_checks(self):
        health_checks = []
        if self.network_mode == "HOST":
            health_checks.append(MarathonHealthCheck(
                protocol='TCP',
                port=self.user_web_port,
                grace_period_seconds=300,
                interval_seconds=60,
                timeout_seconds=20,
                max_consecutive_failures=0
                ))
        else:
            health_checks.append(MarathonHealthCheck(
                protocol='TCP',
                port_index=0,
                grace_period_seconds=300,
                interval_seconds=60,
                timeout_seconds=20,
                max_consecutive_failures=0
                ))

        return health_checks

    def get_volumes(self):
        volumes = []
        for v in self.volumes:
            mv = MarathonContainerVolume.from_json(v)
            mv.container_path = self.format_volume_name(mv.container_path, self)
            mv.host_path = self.format_volume_name(mv.host_path, self)
            if mv.external and 'name' in mv.external:
                mv.external['name'] = self.format_volume_name(mv.external['name'], self)
            volumes.append(mv)
        return volumes

    def get_app_cmd(self):
        retval = self.app_cmd.replace("{username}", self.user.name)
        retval = retval.replace("{userwebport}", str(self.user_web_port))
        retval = retval.replace("{usersshport}", str(self.user_ssh_port))
        return retval


    def get_port_mappings(self):
        port_mappings = []
        if self.network_mode == "BRIDGE":
            for p in self.ports:
                port_mappings.append(
                    MarathonContainerPortMapping(
                        container_port=p,
                        host_port=0,
                        protocol='tcp'
                    )
                )
        return port_mappings

    def get_constraints(self):
        constraints = []
        for c in self.marathon_constraints:
            constraints.append(MarathonConstraint.from_json(c))

    @run_on_executor
    def get_deployment(self, deployment_id):
        deployments = self.marathon.list_deployments()
        for d in deployments:
            if d.id == deployment_id:
                return d
        return None

    @run_on_executor
    def get_deployment_for_app(self, app_name):
        deployments = self.marathon.list_deployments()
        for d in deployments:
            if app_name in d.affected_apps:
                return d
        return None

    def get_ip_and_port(self, app_info):
        assert len(app_info.tasks) == 1
        ip = socket.gethostbyname(app_info.tasks[0].host)
        if self.network_mode == "BRIDGE":
            port = app_info.tasks[0].ports[0]
        else:
            port = self.user_web_port

        return (ip, port)

    @run_on_executor
    def get_app_info(self, app_name):
        try:
            app = self.marathon.get_app(app_name, embed_tasks=True)
        except NotFoundError:
            self.log.info("The %s application has not been started yet", app_name)
            return None
        else:
            return app

    def _public_hub_api_url(self):
        uri = urlparse(self.hub.api_url)
        port = self.hub_port_connect if self.hub_port_connect > 0 else uri.port
        ip = self.hub_ip_connect if self.hub_ip_connect else uri.hostname
        return urlunparse((
            uri.scheme,
            '%s:%s' % (ip, port),
            uri.path,
            uri.params,
            uri.query,
            uri.fragment
            ))

    def get_env(self):
        env = super(MarathonSpawner, self).get_env()
        env.update(dict(
            # Jupyter Hub config
            JPY_USER=self.user.name,
            JPY_COOKIE_NAME=self.user.server.cookie_name,
            JPY_BASE_URL=self.user.server.base_url,
            JPY_HUB_PREFIX=self.hub.server.base_url,
            JPY_USER_WEB_PORT=str(self.user_web_port),
            JPY_USER_SSH_PORT=str(self.user_ssh_port)
        ))

        if self.notebook_dir:
            env['NOTEBOOK_DIR'] = self.notebook_dir

        if self.hub_ip_connect or self.hub_port_connect > 0:
            hub_api_url = self._public_hub_api_url()
        else:
            hub_api_url = self.hub.api_url
        env['JPY_HUB_API_URL'] = hub_api_url

        for x in self.custom_env:
            for k,v in x:
                env[k] = str(v)



        return env

    def update_users(self):
        # No changes if the zeta_user_file is blank
        if self.zeta_user_file != "":
            try:
                j = open(self.zeta_user_file, "r")
                user_file = j.read()
                j.close()
                user_ar = {}
                for x in user_file.split("\n"):
                    if x.strip().find("#") != 0 and x.strip() != "":
                        y = json.loads(x)
                        if y['user'] == self.user.name:
                            user_ar = y
                            break
                if len(user_ar) == 0:
                    self.log.error("Could not find current user %s in zeta_user_file %s - Not Spawning"  % (self.user.name, self.zeta_user_file))
                    if self.no_user_file_fail == True:
                        raise Exception('no_user_file_fail is True, will not go on')

                print("User List identified and loaded, setting values to %s" % user_ar)
                self.cpu_limit = user_ar['cpu_limit']
                self.mem_limit = user_ar['mem_limit']
                self.user_ssh_port = user_ar['user_ssh_port']
                self.user_web_port = user_ar['user_web_port']
                self.network_mode = user_ar['network_mode']
                self.app_image = user_ar['app_image']
                self.marathon_constraints = user_ar['marathon_constraints']
                self.ports.append(self.user_web_port)
                self.ports.append(self.user_ssh_port)
                self.custom_env = self.custom_env + user_ar['custom_env']
                self.volumes = self.volumes + user_ar['volumes']
                print("User List Loaded!")

            # { "user": "username", "cpu_limit": "1", "mem_limit": "2G", "user_ssh_port": 10500, "user_web_port:" 10400, "network_mode": "BRIDGE", "app_image": "$APP_IMG", "marathon_constraints": []}

            except:
                self.log.error("Could not find or open zeta_user_file: %s" % self.zeta_user_file)
                if self.no_user_file_fail == True:
                    raise Exception("Could not open file and config says don't go on")

    @gen.coroutine
    def start(self):
        # First make a quick call to determine if user info was updated
        self.update_users()
        # Go on to start the notebook
        docker_container = MarathonDockerContainer(
            image=self.app_image,
            network=self.network_mode,
            port_mappings=self.get_port_mappings())

        app_container = MarathonContainer(
            docker=docker_container,
            type='DOCKER',
            volumes=self.get_volumes())

        # the memory request in marathon is in MiB
        if hasattr(self, 'mem_limit') and self.mem_limit is not None:
            mem_request = self.mem_limit / 1024.0 / 1024.0
        else:
            mem_request = 1024.0

        app_request = MarathonApp(
            id=self.container_name,
            cmd=self.get_app_cmd(),
            env=self.get_env(),
            cpus=self.cpu_limit,
            mem=mem_request,
            container=app_container,
            constraints=self.get_constraints(),
            health_checks=self.get_health_checks(),
            instances=1
            )

        app = self.marathon.create_app(self.container_name, app_request)
        if app is False or app.deployments is None:
            self.log.error("Failed to create application for %s", self.container_name)
            return None

        while True:
            app_info = yield self.get_app_info(self.container_name)
            if app_info and app_info.tasks_healthy == 1:
                ip, port = self.get_ip_and_port(app_info)
                break
            yield gen.sleep(1)
        return (ip, port)

    @gen.coroutine
    def stop(self, now=False):
        try:
            status = self.marathon.delete_app(self.container_name)
        except:
            self.log.error("Could not delete application %s", self.container_name)
            raise
        else:
            if not now:
                while True:
                    deployment = yield self.get_deployment(status['deploymentId'])
                    if deployment is None:
                        break
                    yield gen.sleep(1)

    @gen.coroutine
    def poll(self):
        deployment = yield self.get_deployment_for_app(self.container_name)
        if deployment:
            for current_action in deployment.current_actions:
                if current_action.action == 'StopApplication':
                    self.log.error("Application %s is shutting down", self.container_name)
                    return 1
            return None

        app_info = yield self.get_app_info(self.container_name)
        if app_info and app_info.tasks_healthy == 1:
            return None
        return 0
