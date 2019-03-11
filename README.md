# Marathon Spawner (Advanced)
This repo takes the work done at https://github.com/vigsterkr/marathonspawner

And seeks to update, document, and extend it for use in multi-role, multi-tenant environments.  

## Changes since the fork

- Support marathon credentials
- Add `fetch` support
- Improve healthcheck
- Fix issue when using in `HOST` mode

## Features
- Spawn Jupyter Notebook Single User Notebooks in Marathon
- Store them in a cool location
- Set Marathon Memory/CPU Constraints
- Set Mesos Host Constraints
- Create Volumes on containers
- Set Ports for users
- Use Bridge or Host Mode
- Allow custom start commands on single-user

## Challenges
- Creating a system to keep per user configuration information for spawn time
- Create system to check for Notebook locations/notebook config file and create at spawn time if they don't exist
- Currently we custom build a notebook container based on the jupyter/singleuser so that we can put LDAP information and other stuff inside it


# Configuration example

```python
c.JupyterHub.spawner_class = 'marathonspawner.MarathonSpawner'
c.MarathonSpawner.app_prefix = 'jupyter'
c.MarathonSpawner.marathon_host = 'http://leader-001.xxxxx:8080'
c.MarathonSpawner.marathon_user_name = 'admin'
c.MarathonSpawner.marathon_user_password = 'xxxxx'
c.MarathonSpawner.fetch = [{'uri': '/srv/config/docker-gitlab.tar.gz'}]
c.MarathonSpawner.mem_limit = '2G'
c.MarathonSpawner.cpu_limit = 1
c.MarathonSpawner.app_image = 'registry.gitlab.com/xxxx/extra/jupyter/master:5ad67069'
c.MarathonSpawner.app_cmd = '/home/jupyter/.local/bin/jupyter labhub --port $PORT0'
c.MarathonSpawner.volumes = [{'containerPath': '/home/jupyter/notebooks', 'hostPath': '/srv/config/notebooks', 'mode': 'RW' }]
c.MarathonSpawner.network_mode = 'HOST'
```

According your infrastructure, you may add these changes as well:

```python
c.JupyterHub.tornado_settings = {
   'slow_spawn_timeout': 120,
}
```