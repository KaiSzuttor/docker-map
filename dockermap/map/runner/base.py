# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
from collections import namedtuple

from docker.utils import create_host_config
from six import text_type

from ...functional import resolve_value
from ..action import (ACTION_CREATE, ACTION_START, ACTION_RESTART, ACTION_STOP, ACTION_REMOVE, ACTION_KILL, ACTION_WAIT)
from ..input import NotSet
from ..policy.utils import extract_user, update_kwargs, init_options, get_volumes, get_host_binds, get_port_bindings
from .attached import AttachedPreparationMixin
from .cmd import ExecMixin
from .signal_stop import SignalMixin
from . import AbstractRunner

ActionConfig = namedtuple('ActionConfig', ['container_map', 'config_name', 'container_config', 'client_name',
                                           'client_config', 'instance_name'])

log = logging.getLogger(__name__)


class BaseRunnerMixin(object):
    attached_action_method_names = [
        (ACTION_CREATE, 'create_attached'),
        (ACTION_START, 'start_attached'),
        (ACTION_RESTART, 'restart_attached'),
        (ACTION_STOP, 'stop_attached'),
        (ACTION_REMOVE, 'remove_attached'),
        (ACTION_KILL, 'kill_attached'),
        (ACTION_WAIT, 'wait_attached'),
    ]
    instance_action_method_names = [
        (ACTION_CREATE, 'create_instance'),
        (ACTION_START, 'start_instance'),
        (ACTION_RESTART, 'restart_instance'),
        (ACTION_STOP, 'stop_instance'),
        (ACTION_REMOVE, 'remove_instance'),
        (ACTION_KILL, 'kill_instance'),
        (ACTION_WAIT, 'wait_instance'),
    ]

    def create_attached(self, client, config, a_name, **kwargs):
        c_kwargs = self.get_attached_create_kwargs(config, a_name, kwargs=kwargs)
        return client.create_container(**c_kwargs)

    def start_attached(self, client, config, a_name, **kwargs):
        if config.client_config.get('use_host_config'):
            res = client.start(a_name)
        else:
            c_kwargs = self.get_attached_host_config_kwargs(config, a_name, kwargs=kwargs)
            res = client.start(**c_kwargs)
        self.prepare_attached(client, config, a_name)
        return res

    def restart_attached(self, client, config, a_name, **kwargs):
        c_kwargs = self.get_restart_kwargs(config, a_name, kwargs=kwargs)
        return client.restart(**c_kwargs)

    def stop_attached(self, client, config, a_name, **kwargs):
        c_kwargs = self.get_stop_kwargs(config, a_name, kwargs=kwargs)
        return client.stop(**c_kwargs)

    def remove_attached(self, client, config, a_name, **kwargs):
        c_kwargs = self.get_remove_kwargs(config, a_name, kwargs=kwargs)
        return client.remove_container(**c_kwargs)

    def kill_attached(self, client, config, a_name, **kwargs):
        return client.kill(a_name, **kwargs)

    def wait_attached(self, client, config, a_name, **kwargs):
        c_kwargs = self.get_wait_kwargs(config, a_name, **kwargs)
        return client.wait(a_name, **c_kwargs)

    def create_instance(self, client, config, c_name, **kwargs):
        c_kwargs = self.get_create_kwargs(config, c_name, kwargs=kwargs)
        return client.create_container(**c_kwargs)

    def start_instance(self, client, config, c_name, **kwargs):
        if config.client_config.get('use_host_config'):
            return client.start(c_name)
        c_kwargs = self.get_host_config_kwargs(config, c_name, kwargs=kwargs)
        return client.start(**c_kwargs)

    def restart_instance(self, client, config, c_name, **kwargs):
        c_kwargs = self.get_restart_kwargs(config, c_name, kwargs=kwargs)
        return client.restart(**c_kwargs)

    def stop_instance(self, client, config, c_name, **kwargs):
        c_kwargs = self.get_stop_kwargs(config, c_name, kwargs=kwargs)
        return client.stop(**c_kwargs)

    def remove_instance(self, client, config, c_name, **kwargs):
        c_kwargs = self.get_remove_kwargs(config, c_name, kwargs=kwargs)
        return client.remove_container(**c_kwargs)

    def kill_instance(self, client, config, c_name, **kwargs):
        return client.kill(c_name, **kwargs)

    def wait_instance(self, client, config, c_name, **kwargs):
        c_kwargs = self.get_wait_kwargs(config, c_name, **kwargs)
        return client.wait(c_name, **c_kwargs)


class DockerClientRunner(BaseRunnerMixin, AttachedPreparationMixin, ExecMixin, SignalMixin, AbstractRunner):
    def get_hostname(self, config, container_name):
        """
        Generates a host name from the container name and the client configuration name.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name.
        :type container_name: unicode | str
        :return: Container host name.
        :rtype: unicode | str
        """
        if config.client_name == self._policy.get_default_client_name():
            return container_name
        return '{0}-{1}'.format(container_name, config.client_name)

    def get_domainname(self, config):
        """
        Provides a domain name for the container, either from the client configuration or the container map default.

        :param config: Configuration.
        :type config: ActionConfig
        :return: Container domain name.
        :rtype: unicode | str
        """
        return resolve_value(config.client_config.get('domainname', config.container_map.default_domain))

    def get_create_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to create a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        client_config = config.client_config
        container_map = config.container_map
        container_config = config.container_config
        c_kwargs = dict(
            name=container_name,
            image=self._policy.iname(container_map, container_config.image or config.config_name),
            volumes=get_volumes(container_map, container_config),
            user=extract_user(container_config.user),
            ports=[resolve_value(port_binding.exposed_port)
                   for port_binding in container_config.exposes if port_binding.exposed_port],
            hostname=self.get_hostname(config, container_name) if container_map.set_hostname else None,
            domainname=self.get_domainname(config),
        )
        if container_config.network == 'disabled':
            c_kwargs['network_disabled'] = True
        hc_extra_kwargs = kwargs.pop('host_config', None) if kwargs else None
        if client_config.get('use_host_config'):
            hc_kwargs = self.get_host_config_kwargs(config, None, kwargs=hc_extra_kwargs)
            if hc_kwargs:
                c_kwargs['host_config'] = create_host_config(**hc_kwargs)
        update_kwargs(c_kwargs, init_options(container_config.create_options), kwargs)
        return c_kwargs

    def get_host_config_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to set up the HostConfig or start a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id. Set ``None`` when included in kwargs for ``create_container``.
        :type container_name: unicode | str | NoneType
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        def volume_str(u):
            vol = cname(map_name, u.volume)
            if u.readonly:
                return '{0}:ro'.format(vol)
            return vol

        container_map = config.container_map
        container_config = config.container_config
        client_config = config.client_config
        map_name = container_map.name
        aname = self._policy.aname
        cname = self._policy.cname
        volumes_from = list(map(volume_str, config.container_config.uses))
        if container_map.use_attached_parent_name:
            volumes_from.extend([aname(map_name, attached, config.config_name)
                                 for attached in container_config.attaches])
        else:
            volumes_from.extend([aname(map_name, attached)
                                 for attached in container_config.attaches])
        c_kwargs = dict(
            links=[(cname(map_name, l_name), alias) for l_name, alias in container_config.links],
            binds=get_host_binds(container_map, container_config, config.instance_name),
            volumes_from=volumes_from,
            port_bindings=get_port_bindings(container_config, client_config),
            version=client_config.version,
        )
        network_mode = container_config.network
        if isinstance(network_mode, tuple):
            c_kwargs['network_mode'] = 'container:{0}'.format(cname(map_name, *network_mode))
        elif isinstance(network_mode, text_type):
            c_kwargs['network_mode'] = network_mode
        if container_name:
            c_kwargs['container'] = container_name
        update_kwargs(c_kwargs, init_options(container_config.host_config), kwargs)
        return c_kwargs

    def get_attached_create_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to create an attached container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        path = resolve_value(config.container_map.volumes[config.instance_name])
        user = extract_user(config.container_config.user)
        c_kwargs = dict(
            name=container_name,
            image=self._policy.base_image,
            volumes=[path],
            user=user,
            network_disabled=True,
        )
        hc_extra_kwargs = kwargs.pop('host_config', None) if kwargs else None
        if config.client_config.get('use_host_config'):
            hc_kwargs = self.get_attached_host_config_kwargs(config, None, kwargs=hc_extra_kwargs)
            if hc_kwargs:
                c_kwargs['host_config'] = create_host_config(**hc_kwargs)
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_attached_host_config_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to set up the HostConfig or start an attached container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id. Set ``None`` when included in kwargs for ``create_container``.
        :type container_name: unicode | str | NoneType
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(version=config.client_config.version)
        if container_name:
            c_kwargs['container'] = container_name
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_restart_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to restart a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(container=container_name)
        stop_timeout = config.container_config.stop_timeout
        if stop_timeout is NotSet:
            timeout = config.client_config.get('stop_timeout')
            if timeout is not None:
                c_kwargs['timeout'] = timeout
        else:
            c_kwargs['timeout'] = stop_timeout
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_wait_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to wait for a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(container=container_name)
        timeout = config.client_config.get('wait_timeout')
        if timeout is not None:
            c_kwargs['timeout'] = timeout
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_stop_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to stop a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(
            container=container_name,
        )
        stop_timeout = config.container_config.stop_timeout
        if stop_timeout is NotSet:
            timeout = config.client_config.get('stop_timeout')
            if timeout is not None:
                c_kwargs['timeout'] = timeout
        else:
            c_kwargs['timeout'] = stop_timeout
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_remove_kwargs(self, config, container_name, kwargs=None):
        """
        Generates keyword arguments for the Docker client to remove a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(container=container_name)
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_exec_create_kwargs(self, config, container_name, exec_cmd, exec_user, kwargs=None):
        """
        Generates keyword arguments for the Docker client to set up the HostConfig or start a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :param exec_cmd: Command to be executed.
        :type exec_cmd: unicode | str
        :param exec_user: User to run the command.
        :type exec_user: unicode | str
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(
            container=container_name,
            cmd=resolve_value(exec_cmd),
        )
        if exec_user is not None:
            c_kwargs['user'] = resolve_value(exec_user)
        elif config.container_config.user is not NotSet:
            c_kwargs['user'] = extract_user(config.container_config.user)
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def get_exec_start_kwargs(self, config, container_name, exec_id, kwargs=None):
        """
        Generates keyword arguments for the Docker client to set up the HostConfig or start a container.

        :param config: Configuration.
        :type config: ActionConfig
        :param container_name: Container name or id.
        :type container_name: unicode | str
        :param kwargs: Additional keyword arguments to complement or override the configuration-based values.
        :type kwargs: dict | NoneType
        :param exec_id: Id of the exec instance.
        :type exec_id: long
        :return: Resulting keyword arguments.
        :rtype: dict
        """
        c_kwargs = dict(exec_id=exec_id)
        update_kwargs(c_kwargs, kwargs)
        return c_kwargs

    def run_actions(self, attached_actions, instance_actions, **kwargs):
        """

        :param attached_actions:
        :type attached_actions: list[dockermap.map.action.InstanceAction]
        :param instance_actions:
        :type instance_actions: list[dockermap.map.action.InstanceAction]
        :param kwargs:
        :return:
        """
        aname = self._policy.aname
        for action in attached_actions:
            a_method = self.attached_methods.get(action.action_type)
            if not a_method:
                raise ValueError("Invalid action for attached containers: {0}", action.action_type)
            client_config = self._policy.clients[action.client_name]
            client = client_config.get_client()
            c_map = self._policy.container_maps[action.map_name]
            c_config = c_map.get_existing(action.config_name)
            a_parent_name = action.config_name if c_map.use_attached_parent_name else None
            container_name = aname(action.map_name, action.instance_name, parent_name=a_parent_name)
            action_config = ActionConfig(c_map, action.config_name, c_config,
                                         action.client_name, client_config,
                                         action.instance_name)
            res = a_method(client, action_config, container_name, **action.extra_data)
            if res is not None:
                yield res

        cname = self._policy.cname
        for action in instance_actions:
            c_method = self.instance_methods.get(action.action_type)
            if not c_method:
                raise ValueError("Invalid action for instance containers: {0}", action.action_type)
            client_config = self._policy.clients[action.client_name]
            client = client_config.get_client()
            c_map = self._policy.container_maps[action.map_name]
            c_config = c_map.get_existing(action.config_name)
            container_name = cname(action.map_name, action.config_name, action.instance_name)
            action_config = ActionConfig(c_map, action.config_name, c_config,
                                         action.client_name, client_config,
                                         action.instance_name)
            c_kwargs = action.extra_data.copy()
            c_kwargs.update(kwargs)
            res = c_method(client, action_config, container_name, **c_kwargs)
            if res is not None:
                yield res