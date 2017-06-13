# Marathon Spawner (Advanced)
This repo takes the work done at https://github.com/vigsterkr/marathonspawner

And seeks to update, document, and extend it for use in multi-role, multi-tenant environments.  

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
- 
