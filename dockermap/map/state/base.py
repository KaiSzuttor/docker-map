# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import itertools
from abc import abstractmethod
import logging

from six import with_metaclass

from ..input import ITEM_TYPE_CONTAINER, ITEM_TYPE_VOLUME, ITEM_TYPE_NETWORK
from ..policy import (CONFIG_FLAG_DEPENDENT, CONTAINER_CONFIG_FLAG_ATTACHED, CONTAINER_CONFIG_FLAG_PERSISTENT,
                      ABCPolicyUtilMeta, PolicyUtil)
from . import (INITIAL_START_TIME, STATE_ABSENT, STATE_PRESENT, STATE_RUNNING, STATE_FLAG_INITIAL,
               STATE_FLAG_RESTARTING, STATE_FLAG_NONRECOVERABLE, STATE_FLAG_OUTDATED,
               ConfigState)
from .utils import merge_dependency_paths


log = logging.getLogger(__name__)


class _ObjectNotFound(object):
    pass


NOT_FOUND = _ObjectNotFound()


class AbstractState(object):
    """
    Abstract base implementation for determining the current state of a single object on the client.

    :param policy: Policy object.
    :type policy: dockermap.map.policy.base.BasePolicy
    :param options: Dictionary of options passed to the state generator.
    :type options: dict
    :param map_name: Container map name.
    :type map_name: unicode | str
    :param container_map: Container map instance.
    :type container_map: dockermap.map.config.main.ContainerMap
    :param client_name: Client name.
    :type client_name: unicode | str
    :param client_config: Client configuration object.
    :type client_config: dockermap.map.config.client.ClientConfiguration
    :param client: Docker client.
    :type client: docker.client.Client
    """
    def __init__(self, policy, options, map_name, container_map, client_name, client_config,
                 client, config_name, config, *args, **kwargs):
        self.policy = policy
        self.options = options
        self.map_name = map_name
        self.container_map = container_map
        self.client_name = client_name
        self.client_config = client_config
        self.client = client
        self.config_name = config_name
        self.config = config
        self.detail = None

    def set_defaults(self, *args, **kwargs):
        """
        Resets the state, so that with adjustments of input parameters the object can be reused without side-effects
        to other objects on the client.
        """
        self.detail = None

    def inspect(self):
        """
        Inspects the object on the client, i.e. makes actual calls to the client to check on the object.
        """
        pass

    def get_state(self):
        """
        Determines and returns the state information.

        :return: State information.
        :type: tuple
        """
        pass


class ContainerBaseState(AbstractState):
    """
    Abstract base implementation for determining the current state of a single container on the client.

    :param policy: Policy object.
    :type policy: dockermap.map.policy.base.BasePolicy
    :param options: Dictionary of options passed to the state generator.
    :type options: dict
    :param map_name: Container map name.
    :type map_name: unicode | str
    :param container_map: Container map instance.
    :type container_map: dockermap.map.config.main.ContainerMap
    :param client_name: Client name.
    :type client_name: unicode | str
    :param client_config: Client configuration object.
    :type client_config: dockermap.map.config.client.ClientConfiguration
    :param client: Docker client.
    :type client: docker.client.Client
    :param config_name: Configuration name.
    :type config_name: unicode | str
    :param config: Configuration object.
    :type config: dockermap.map.config.ConfigurationObject
    :param instance_name: Container instance name or attached alias.
    :type instance_name: unicode | str
    :param config_flags: Config flags on the container.
    :type config_flags: int
    """
    def __init__(self, policy, options, map_name, container_map, client_name, client_config,
                 client, config_name, config, instance_name, config_flags, *args, **kwargs):
        super(ContainerBaseState, self).__init__(policy, options, map_name, container_map, client_name, client_config,
                                                 client, config_name, config, *args, **kwargs)
        self.instance_name = instance_name
        self.config_flags = config_flags
        self.container_name = None

    def set_defaults(self, *args, **kwargs):
        super(ContainerBaseState, self).set_defaults(*args, **kwargs)
        self.instance_name = None
        self.config_flags = 0
        self.container_name = None

    def inspect(self):
        """
        Fetches information about the container from the client.
        """
        super(ContainerBaseState, self).inspect()
        policy = self.policy
        if self.config_flags & CONTAINER_CONFIG_FLAG_ATTACHED:
            if self.container_map.use_attached_parent_name:
                container_name = policy.aname(self.map_name, self.instance_name, self.config_name)
            else:
                container_name = policy.aname(self.map_name, self.instance_name)
        else:
            container_name = policy.cname(self.map_name, self.config_name, self.instance_name)

        self.container_name = container_name
        if container_name in policy.container_names[self.client_name]:
            self.detail = self.client.inspect_container(container_name)
        else:
            self.detail = NOT_FOUND

    def get_state(self):
        c_detail = self.detail
        if c_detail is NOT_FOUND:
            return STATE_ABSENT, 0, {}

        c_status = c_detail['State']
        if c_status['Running']:
            base_state = STATE_RUNNING
            state_flag = 0
        else:
            base_state = STATE_PRESENT
            if c_status['StartedAt'] == INITIAL_START_TIME:
                state_flag = STATE_FLAG_INITIAL
            elif c_status['ExitCode'] in self.options['nonrecoverable_exit_codes']:
                state_flag = STATE_FLAG_NONRECOVERABLE
            else:
                state_flag = 0
            if c_status['Restarting']:
                state_flag |= STATE_FLAG_RESTARTING
        force_update = self.options['force_update']
        if force_update and (ITEM_TYPE_CONTAINER, self.map_name, self.config_name, self.instance_name) in force_update:
            state_flag |= STATE_FLAG_OUTDATED
        return base_state, state_flag, {}


class NetworkBaseState(AbstractState):
    def __init__(self, *args, **kwargs):
        super(NetworkBaseState, self).__init__(*args, **kwargs)
        self.network_name = None

    def set_defaults(self, *args, **kwargs):
        self.network_name = None

    def inspect(self):
        """
        Inspects the network state.
        """
        network_name = self.network_name = self.policy.nname(self.map_name, self.config_name)
        if network_name in self.policy.network_names[self.client_name]:
            self.detail = self.client.inspect_network(network_name)
        else:
            self.detail = NOT_FOUND

    def get_state(self):
        if self.detail is NOT_FOUND:
            return STATE_ABSENT, 0, {}
        force_update = self.options['force_update']
        if force_update and (ITEM_TYPE_NETWORK, self.map_name, self.config_name, None) in force_update:
            state_flag = STATE_FLAG_OUTDATED
        else:
            state_flag = 0
        return STATE_PRESENT, state_flag, {}


class AbstractStateGenerator(with_metaclass(ABCPolicyUtilMeta, PolicyUtil)):
    """
    Abstract base implementation for an state generator, which determines the current state of containers on the client.
    """
    container_state_class = ContainerBaseState
    network_state_class = NetworkBaseState

    nonrecoverable_exit_codes = (-127, -1)
    force_update = None
    policy_options = ['nonrecoverable_exit_codes', 'force_update']

    def get_container_state(self, map_name, c_map, client_name, client_config, client, config_name, c_config,
                            instance_name, config_flags, *args, **kwargs):
        return self.container_state_class(self._policy, self.get_options(), map_name, c_map, client_name,
                                          client_config, client, config_name, c_config, instance_name, config_flags,
                                          *args, **kwargs)

    def get_network_state(self, map_name, c_map, client_name, client_config, client, config_name, n_config,
                          *args, **kwargs):
        return self.network_state_class(self._policy, self.get_options(), map_name, c_map, client_name,
                                        client_config, client, config_name, n_config, *args, **kwargs)

    def generate_config_states(self, config_type, map_name, config_name, instance_name, is_dependency=False):
        """
        Generates the actions on a single item, which can be either a dependency or a explicitly selected
        container.

        :param config_type: Configuration type.
        :type config_type: unicode | str
        :param map_name: Container map name.
        :type map_name: unicode | str
        :param config_name: Container configuration name.
        :type config_name: unicode | str
        :param instance_name: Instance name. Can be ``[None]``
        :type instance_name: unicode | str | NoneType
        :param is_dependency: Whether the state check is on a dependency or dependent container.
        :type is_dependency: bool
        :return: Generator for container state information.
        :rtype: collections.Iterable[dockermap.map.state.ContainerConfigStates]
        """
        c_map = self._policy.container_maps[map_name]
        c_flags = CONFIG_FLAG_DEPENDENT if is_dependency else 0

        if config_type == ITEM_TYPE_CONTAINER:
            config = c_map.get_existing(config_name)
            if not config:
                raise KeyError("Container configuration '{0}' not found on map '{1}'.".format(config_name, map_name))
            clients = self._policy.get_clients(c_map, config)
            if config.persistent:
                c_flags |= CONTAINER_CONFIG_FLAG_PERSISTENT
            state_func = self.get_container_state
        elif config_type == ITEM_TYPE_VOLUME:
            config = c_map.get_existing(config_name)
            if not config:
                raise KeyError("Container configuration '{0}' not found on map '{1}'.".format(config_name, map_name))
            clients = self._policy.get_clients(c_map, config)
            # TODO: Change for actual volumes.
            c_flags |= CONTAINER_CONFIG_FLAG_ATTACHED
            state_func = self.get_container_state
        elif config_type == ITEM_TYPE_NETWORK:
            config = c_map.get_existing_network(config_name)
            if not config:
                raise KeyError("Network configuration '{0}' not found on map '{1}'.".format(config_name, map_name))
            clients = self._policy.get_clients(c_map)
            state_func = self.get_network_state
        else:
            raise ValueError("Invalid configuration type.", config_type)

        for client_name, client_config in clients:
            client = client_config.get_client()
            c_state = state_func(map_name, c_map, client_name, client_config, client, config_name, config,
                                 instance_name, c_flags)
            c_state.inspect()
            # Extract base state, state flags, and extra info.
            state_info = ConfigState(client_name, map_name, config_type, config_name, instance_name, c_flags,
                                     *c_state.get_state())
            log.debug("Configuration state information: %s", state_info)
            yield state_info

    @abstractmethod
    def get_states(self, config_ids):
        """
        To be implemented by subclasses. Generates state information for the selected containers.

        :param config_ids: MapConfigId tuple.
        :type config_ids: list[dockermap.map.input.MapConfigId]
        :return: Iterator over container configuration states.
        :rtype: collections.Iterable[dockermap.map.state.ContainerConfigStates]
        """
        pass

    @property
    def policy(self):
        """
        Policy object instance to generate actions for.

        :return: Policy object instance.
        :rtype: BasePolicy
        """
        return self._policy

    @policy.setter
    def policy(self, value):
        self._policy = value


class SingleStateGenerator(AbstractStateGenerator):
    def get_states(self, config_ids):
        """
        Generates state information for the selected containers.

        :param config_ids: List of MapConfigId tuples.
        :type config_ids: list[dockermap.map.input.MapConfigId]
        :return: Return values of created main containers.
        :rtype: collections.Iterable[dockermap.map.state.ContainerConfigStates]
        """
        return itertools.chain.from_iterable(self.generate_config_states(*config_id)
                                             for config_id in config_ids)


class AbstractDependencyStateGenerator(with_metaclass(ABCPolicyUtilMeta, AbstractStateGenerator)):
    @abstractmethod
    def get_dependency_path(self, config_id):
        """
        To be implemented by subclasses (or using :class:`ForwardActionGeneratorMixin` or
        :class:`ReverseActionGeneratorMixin`). Should provide an iterable of objects to be handled before the explicitly
        selected container configuration.

        :param config_id: MapConfigId tuple.
        :type config_id: dockermap.map.input.MapConfigId
        :return: Iterable of dependency objects in tuples of configuration type, map name, container (config) name, instances.
        :rtype: list[tuple]
        """
        pass

    def _get_all_states(self, config_id, dependency_path):
        log.debug("Following dependency path for %(map_name)s.%(config_name)s.", config_id)
        for d_type, d_map_name, d_config_name, d_instance in dependency_path:
            log.debug("Dependency path at %s %s.%s, instance %s.", d_type, d_map_name, d_config_name, d_instance)
            for state in self.generate_config_states(d_type, d_map_name, d_config_name, d_instance, is_dependency=True):
                yield state
        log.debug("Processing state for %(config_type)s %(map_name)s.%(config_name)s, instance %(instance)s.", config_id)
        for state in self.generate_config_states(*config_id):
            yield state

    def get_states(self, config_ids):
        """
        Generates state information for the selected container and its dependencies / dependents.

        :param config_ids: MapConfigId tuples.
        :type config_ids: list[dockermap.map.input.MapConfigId]
        :return: Return values of created main containers.
        :rtype: itertools.chain[dockermap.map.state.ContainerConfigStates]
        """
        dependency_paths = merge_dependency_paths(
            (config_id, self.get_dependency_path(config_id))
            for config_id in config_ids
        )
        return itertools.chain.from_iterable(self._get_all_states(config_id, dependency_path)
                                             for config_id, dependency_path in dependency_paths)


class DependencyStateGenerator(AbstractDependencyStateGenerator):
    def get_dependency_path(self, config_id):
        return self._policy.get_dependencies(config_id)


class DependentStateGenerator(AbstractDependencyStateGenerator):
    def get_dependency_path(self, config_id):
        return self._policy.get_dependents(config_id)
