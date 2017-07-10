# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import Counter
import itertools
from operator import itemgetter

import six

from . import ConfigurationObject, CP
from .. import DictMap, DefaultDictMap
from ..input import ITEM_TYPE_CONTAINER, ITEM_TYPE_VOLUME, ITEM_TYPE_NETWORK, bool_if_set, MapConfigId
from .container import ContainerConfiguration
from .host_volume import HostVolumeConfiguration
from .network import NetworkConfiguration


get_map_config = itemgetter(0, 1)


def _get_single_instances(group_items):
    return tuple(di[2] for di in group_items)


def _get_nested_instances(group_items):
    instance_set = set()
    instance_add = instance_set.add
    return tuple(ni
                 for di in group_items
                 for ni in di[2] or (None, )
                 if ni not in instance_set or instance_add(ni))


def expand_groups(config_ids, groups):
    """
    Iterates over a list of container configuration ids, expanding groups of container configurations.

    :param config_ids: List of container configuration ids.
    :type config_ids: collections.Iterable[dockermap.map.input.MapConfigId]
    :param groups: Dictionary of container configuration groups per map.
    :type groups: dict[unicode | str, dockermap.map.DictMap]
    :return: Expanded MapConfigId tuples.
    :rtype: collections.Iterable[dockermap.map.input.MapConfigId]
    """
    for config_id in config_ids:
        group = groups[config_id.map_name].get(config_id.config_name)
        if group is not None:
            for group_item in group:
                if isinstance(group_item, MapConfigId):
                    yield group_item
                elif isinstance(group_item, six.string_types):
                    config_name, __, instance = group_item.partition('.')
                    yield MapConfigId(config_id.map_name, config_name, (instance, ) if instance else config_id.instances)
                else:
                    raise ValueError("Invalid group item. Must be string or MapConfigId tuple; found {0}.".format(
                        type(group_item).__name__))
        else:
            yield config_id


def group_instances(config_ids, single_instances=True, ext_map=None, ext_maps=None):
    """
    Iterates over a list of container configuration ids, grouping instances together. A tuple of instances that matches
    the list of instances in a configuration is replaced with a tuple only containing ``None``.

    :param config_ids: Iterable of container configuration ids or (map, config, instance) tuples.
    :type config_ids: collections.Iterable[dockermap.map.input.MapConfigId] |
      collections.Iterable[tuple[unicode | str, unicode | str, unicode | str]]
    :param single_instances: Whether the instances are a passed as a tuple or as a single string.
    :type single_instances: bool
    :param ext_map: Extended ContainerMap instance for looking up container configurations. Use this only if all
     elements of ``config_ids`` are from the same map.
    :type ext_map: ContainerMap
    :param ext_maps: Dictionary of extended ContainerMap instances for looking up container configurations.
    :type ext_maps: dict[unicode | str, ContainerMap]
    :return: MapConfigId tuples.
    :rtype: collections.Iterable[dockermap.map.input.MapConfigId]
    """
    if not (ext_map or ext_maps):
        raise ValueError("Either a single ContainerMap or a dictionary of them must be provided.")
    _get_instances = _get_single_instances if single_instances else _get_nested_instances

    for map_config, items in itertools.groupby(sorted(config_ids, key=get_map_config), get_map_config):
        map_name, config_name = map_config
        instances = _get_instances(items)
        c_map = ext_map or ext_maps[map_name]
        config = c_map.get_existing(config_name)
        if not config:
            raise KeyError((map_name, config_name))
        if config.instances and (None in instances or len(instances) == len(config.instances)):
            yield MapConfigId(map_name, config_name, (None, ))
        else:
            yield MapConfigId(map_name, config_name, instances)


def expand_instances(config_ids, single_instances=True, ext_map=None, ext_maps=None):
    """
    Iterates over a list of container configuration ids, expanding configured instances if ``None`` is specified.

    :param config_ids: Iterable of container configuration ids or (map, config, instance) tuples.
    :type config_ids: collections.Iterable[dockermap.map.input.MapConfigId] |
      collections.Iterable[tuple[unicode | str, unicode | str, unicode | str]]
    :param single_instances: Whether the instances are a passed as a tuple or as a single string.
    :type single_instances: bool
    :param ext_map: Extended ContainerMap instance for looking up container configurations. Use this only if all
     elements of ``config_ids`` are from the same map.
    :type ext_map: ContainerMap
    :param ext_maps: Dictionary of extended ContainerMap instances for looking up container configurations.
    :type ext_maps: dict[unicode | str, ContainerMap]
    :return: Tuples of map name, container configuration name, and a single instance name (or ``None``).
    :rtype: collections.Iterable[tuple[unicode | str, unicode | str, unicode | str]]
    """
    if not (ext_map or ext_maps):
        raise ValueError("Either a single ContainerMap or a dictionary of them must be provided.")
    _get_instances = _get_single_instances if single_instances else _get_nested_instances

    for map_config, items in itertools.groupby(sorted(config_ids, key=get_map_config), get_map_config):
        map_name, config_name = map_config
        instances = _get_instances(items)
        c_map = ext_map or ext_maps[map_name]
        config = c_map.get_existing(config_name)
        if not config:
            raise KeyError(map_name, config_name)
        if config.instances and None in instances:
            for i in config.instances:
                yield map_name, config_name, i
        else:
            for i in instances:
                yield map_name, config_name, i


class MapIntegrityError(Exception):
    """
    Exception for cases where the configurations are not consistent (e.g. a volume alias is missing on the map).
    """
    @property
    def message(self):
        if self.args:
            return self.args[0]
        return None


class ContainerMap(ConfigurationObject):
    """
    Class for merging container configurations, host shared volumes, and volume alias names.

    :param name: Name for this container map.
    :type name: unicode | str
    :param initial: Initial container configurations, host shares, and volumes.
    :type initial: dict
    :param check_integrity: If initial values are given, the container integrity is checked by default at the end of
     this constructor. Setting this to `False` deactivates it.
    :type check_integrity: bool
    :param check_duplicates: Check for duplicate attached volumes during integrity check.
    :type check_duplicates: bool
    :param kwargs: Kwargs with initial container configurations, host shares, and volumes.
    """
    repository = CP()
    host = CP(dict, default=HostVolumeConfiguration, input_func=HostVolumeConfiguration, update=False)
    volumes = CP(dict, default=DictMap, input_func=DictMap)
    clients = CP(list)
    groups = CP(dict, default=DictMap, input_func=DictMap)
    default_domain = CP()
    set_hostname = CP(default=True, input_func=bool_if_set)
    use_attached_parent_name = CP(default=False, input_func=bool_if_set)
    default_tag = CP(default='latest')

    DOCSTRINGS = {
        'repository': "Repository prefix for images. This is prepended to image names used by container "
                      "configurations.",
        'host': "Volume alias assignments of the map.",
        'volumes': "Volume alias assignments of the map.",
        'clients': "Alias names of clients associated with this container map.",
        'groups': "Groups of configured containers.",
        'default_domain': "Value to use as domain name for new containers, unless the client specifies otherwise.",
        'set_hostname': "Whether to set the hostname for new containers. When set to ``False``, uses Docker's default"
                        "autogeneration of hostnames instead.",
        'use_attached_parent_name': "Whether to include the parent name of an attached volume in the attached "
                                    "container name for disambiguation.",
        'default_tag': "Default tag to use for images where it is not specified. Default is ``latest``.",
    }

    def __init__(self, name, initial=None, check_integrity=True, check_duplicates=True, **kwargs):
        self._name = name
        self._extended = False
        self._containers = DefaultDictMap(ContainerConfiguration)
        self._networks = DefaultDictMap(NetworkConfiguration)
        super(ContainerMap, self).__init__(initial, **kwargs)
        if self._containers and check_integrity:
            self.check_integrity(check_duplicates=check_duplicates)

    def __iter__(self):
        return ((c_name, c_config) for c_name, c_config in six.iteritems(self._containers) if not c_config.abstract)

    def update_default_from_dict(self, key, value):
        if key == 'host_root':
            self.host.root = value
        elif key == 'containers':
            for c_name, c_value in six.iteritems(value):
                self._containers[c_name].update_from_dict(c_value)
        elif key == 'networks':
            for n_name, n_value in six.iteritems(value):
                self._networks[n_name].update_from_dict(n_value)
        else:
            self._containers[key].update_from_dict(value)

    def merge_default_from_dict(self, key, value, lists_only=False):
        if key == 'host_root':
            if not lists_only:
                self.host.root = value
        elif key == 'containers':
            for c_name, c_value in six.iteritems(value):
                if c_name in self._containers:
                    self._containers[c_name].merge_from_dict(c_value, lists_only=lists_only)
                else:
                    self._containers[c_name].update_from_dict(c_value)
        elif key == 'networks':
            for n_name, n_value in six.iteritems(value):
                if n_name in self._networks:
                    self._networks[n_name].merge_from_dict(n_value, lists_only=lists_only)
                else:
                    self._networks[n_name].update_from_dict(n_value)
        elif key in self._containers:
            self._containers[key].merge_from_dict(value, lists_only=lists_only)
        else:
            self._containers[key].update_from_dict(value)

    def update_from_dict(self, dct):
        host = dct.get('host')
        if host:
            self._config['host'] = HostVolumeConfiguration(host)
        containers = dct.get('containers')
        if containers:
            self._config['containers'] = containers = DefaultDictMap(ContainerConfiguration)
            containers.update(containers)
        networks = dct.get('networks')
        if networks:
            self._config['networks'] = networks = DefaultDictMap(NetworkConfiguration)
            networks.update(networks)
        super(ContainerMap, self).update_from_dict(dct)

    def update_from_obj(self, obj, copy=False, update_containers=True):
        self._config['host'] = obj.host.copy() if copy else obj.host
        if update_containers:
            for key, value in obj.containers:
                self._containers[key].update_from_obj(value, copy=copy)
        for key, value in obj.networks:
            self._networks[key].update_from_obj(value, copy=copy)
        super(ContainerMap, self).update_from_obj(obj, copy=copy)

    def merge_from_obj(self, obj, lists_only=False):
        for key, value in obj.containers:
            if key in self._containers:
                self._containers[key].merge_from_obj(value, lists_only=lists_only)
            else:
                self._containers[key].update_from_obj(value)
        for key, value in obj.networks:
            if key in self._networks:
                self._networks[key].merge_from_obj(value, lists_only=lists_only)
            else:
                self._networks[key].update_from_obj(value)
        super(ContainerMap, self).merge_from_obj(obj, lists_only=lists_only)

    def get_persistent_items(self):
        """
        Returns attached container items and container configurations that are marked as persistent. Each returned
        item is in the format ``(config name, instance/attached name)``, where the instance name can also be ``None``.

        :return: Lists of attached items.
        :rtype: (list[(unicode | str, unicode | str)], list[unicode | str, unicode | str | NoneType])
        """
        attached_items = [(container, ac)
                          for container, config in self
                          for ac in config.attaches]
        persistent_containers = [(container, ci)
                                 for container, config in self if config.persistent
                                 for ci in config.instances or [None]]
        return attached_items, persistent_containers

    @property
    def name(self):
        """
        Container map name.

        :return: Container map name.
        :rtype: unicode | str
        """
        return self._name

    @property
    def containers(self):
        """
        Container configurations of the map.

        :return: Container configurations.
        :rtype: dict[unicode | str, dockermap.map.config.container.ContainerConfiguration]
        """
        return self._containers

    @containers.setter
    def containers(self, value):
        if isinstance(value, DefaultDictMap) and value.default_factory is ContainerConfiguration:
            self._containers = value
        else:
            self._containers.clear()
            self._containers.update(value)

    @property
    def networks(self):
        """
        Network configurations on the map.

        :return: Network configurations.
        :rtype: dict[unicode | str, dockermap.map.config.network.NetworkConfiguration]
        """
        return self._networks

    @networks.setter
    def networks(self, value):
        if isinstance(value, DefaultDictMap) and value.default_factory is NetworkConfiguration:
            self._networks = value
        else:
            self._networks.clear()
            self._networks.update(value)

    def dependency_items(self, reverse=False):
        """
        Generates all containers' dependencies, i.e. an iterator on tuples in the format
        ``(container_name, used_containers)``, whereas the used containers are a set, and can be empty.

        :return: Container dependencies.
        :rtype: iterator
        """
        def _get_used_item_np(u):
            v = u.volume
            c, __, i = v.partition('.')
            a = attached.get(c)
            if a:
                return self._name, a, None
            return self._name, c, i or None

        def _get_used_item_ap(u):
            v = u.volume
            c, __, i = v.partition('.')
            a = ext_map.get_existing(c)
            if i in a.attaches:
                return self._name, c, None
            return self._name, c, i or None

        def _get_linked_item(l):
            c, __, i = l.container.partition('.')
            if i:
                return self._name, c, i
            return self._name, c, None

        if self._extended:
            ext_map = self
        else:
            ext_map = self.get_extended_map()

        if not self.use_attached_parent_name:
            attached = {attaches: c_name
                        for c_name, c_config in ext_map
                        for attaches in c_config.attaches}
            used_func = _get_used_item_np
        else:
            used_func = _get_used_item_ap

        def _get_dep_set(config):
            used_set = set(map(used_func, config.uses))
            linked_set = set(map(_get_linked_item, config.links))
            d_set = used_set | linked_set
            nw = config.network
            if isinstance(nw, tuple):
                d_set.add((self._name, ) + nw)
            return d_set

        if reverse:
            # Consolidate dependents.
            for c_name, c_config in ext_map:
                dep_set = set(map(get_map_config, _get_dep_set(c_config)))
                yield (self._name, c_name, (None, )), dep_set
        else:
            # Group instances, or replace with None where all of them are used.
            for c_name, c_config in ext_map:
                dep_set = _get_dep_set(c_config)
                try:
                    instance_set = set(group_instances(dep_set, ext_map=ext_map))
                except KeyError as e:
                    raise KeyError("Dependency {0[0]}.{0[1]} for {1}.{2} not found.".format(e.args[0], self._name, c_name))
                yield (self._name, c_name), instance_set

    def get(self, item):
        """
        Returns a container configuration from the map; if it does not yet exist, an initial config is created and
        returned (to avoid this, use :meth:`get_existing` instead). `item` can be any valid Docker container name.

        :param item: Container name.
        :type item: unicode | str
        :return: A container configuration.
        :rtype: ContainerConfiguration
        """
        return self._containers[item]

    def get_existing(self, item):
        """
        Same as :meth:`get`, except for that non-existing container configurations will not be created; ``None`` is
        returned instead in this case.

        :param item: Container name.
        :type item: unicode | str
        :return: A container configuration
        :rtype: ContainerConfiguration
        """
        return self._containers.get(item)

    def get_network(self, name):
        """
        Returns a network configuration from the map; if it does not yet exist, an initial config is created and
        returned (to avoid this, use :meth:`get_existing_network` instead). `name` can be any valid network name.

        :param name: Network name.
        :type name: unicode | str
        :return: A network configuration.
        :rtype: NetworkConfiguration
        """
        return self._networks[name]

    def get_existing_network(self, name):
        """
        Same as :meth:`get_network`, except for that non-existing network configurations will not be created; ``None``
        is returned instead in this case.

        :param name: Network name.
        :type name: unicode | str
        :return: A network configuration.
        :rtype: NetworkConfiguration
        """
        return self._networks.get(name)

    def get_extended(self, config):
        """
        Generates a configuration that includes all inherited values.

        :param config: Container configuration.
        :type config: ContainerConfiguration
        :return: A merged (shallow) copy of all inherited configurations merged with the container configuration.
        :rtype: ContainerConfiguration
        """
        if not config.extends or self._extended:
            return config
        extended_config = ContainerConfiguration()
        for ext_name in config.extends:
            ext_cfg_base = self._containers.get(ext_name)
            if not ext_cfg_base:
                raise KeyError(ext_name)
            ext_cfg = self.get_extended(ext_cfg_base)
            extended_config.merge_from_obj(ext_cfg)
        extended_config.merge_from_obj(config)
        return extended_config

    def get_extended_map(self):
        """
        Creates a copy of this map which includes all non-abstract configurations in their extended form.

        :return: Copy of this map.
        :rtype: ContainerMap
        """
        map_copy = self.__class__(self.name)
        map_copy.update_from_obj(self, copy=True, update_containers=False)
        for c_name, c_config in self:
            map_copy._containers[c_name] = self.get_extended(c_config)
        map_copy._extended = True
        return map_copy

    def check_integrity(self, check_duplicates=True):
        """
        Checks the integrity of the container map. This means, that
        * every shared container (instance name) and attached volume should only exist once (can be deactivated);
        * every container declared as `used` needs to have at least a shared volume or a host bind;
        * every host bind declared under `binds` needs to be shared from the host;
        * every volume alias used in `attached` and `binds` needs to be associated with a path in `volumes`;
        * every container referred to in `links` needs to be defined;
        * every container named in `extended` is available.

        :param check_duplicates: Check for duplicate attached volumes.
        :type check_duplicates: bool
        """
        def _get_instance_names(c_name, instances):
            if instances:
                return ['{0}.{1}'.format(c_name, instance) for instance in instances]
            return [c_name]

        def _get_container_items(c_name, c_config):
            instance_names = _get_instance_names(c_name, c_config.instances)
            group_ref_names = instance_names[:]
            if c_config.instances:
                group_ref_names.append(c_name)
            shared = instance_names[:] if c_config.shares or c_config.binds or c_config.uses else []
            bind = [b.volume for b in c_config.binds if not isinstance(b.volume, tuple)]
            link = [l.container for l in c_config.links]
            uses = [u.volume for u in c_config.uses]
            if isinstance(c_config.network, tuple):
                if c_config.network[1]:
                    network = '{0}.{1}'.format(*c_config.network)
                else:
                    network = c_config.network[0]
            else:
                network = None
            if self.use_attached_parent_name:
                attaches = [(c_name, a) for a in c_config.attaches]
            else:
                attaches = c_config.attaches
            return instance_names, group_ref_names, uses, attaches, shared, bind, link, network

        all_instances, all_grouprefs, all_used, all_attached, all_shared, all_binds, all_links, all_networks = zip(*[
            _get_container_items(k, v) for k, v in self.get_extended_map()
        ])
        if self.use_attached_parent_name:
            all_attached_names = tuple('{0}.{1}'.format(c_name, a)
                                       for c_name, a in itertools.chain.from_iterable(all_attached))
        else:
            all_attached_names = tuple(itertools.chain.from_iterable(all_attached))

        ref_set = set(itertools.chain.from_iterable(all_grouprefs))
        group_set = set(self.groups.keys())
        ambiguous_names = group_set & ref_set
        if ambiguous_names:
            ambiguous_str = ', '.join(ambiguous_names)
            raise MapIntegrityError("Names are used both for container configurations (or instances) and for container "
                                    "groups: {0}.".format(ambiguous_str))
        group_referenced = set(itertools.chain.from_iterable(self.groups.values()))
        missing_refs = group_referenced - ref_set
        if missing_refs:
            missing_ref_str = ', '.join(missing_refs)
            raise MapIntegrityError("Container configurations or certain instances are referenced by groups, but are "
                                    "not defined: {0}.".format(missing_ref_str))
        volume_shared = tuple(itertools.chain.from_iterable(all_shared)) + all_attached_names
        if check_duplicates:
            duplicated = [name for name, count in six.iteritems(Counter(volume_shared)) if count > 1]
            if duplicated:
                dup_str = ', '.join(duplicated)
                raise MapIntegrityError("Duplicated attached volumes found with name(s): {0}.".format(dup_str))
        used_set = set(itertools.chain.from_iterable(all_used))
        shared_set = set(volume_shared)
        missing_shares = used_set - shared_set
        if missing_shares:
            missing_share_str = ', '.join(missing_shares)
            raise MapIntegrityError("No shared or attached volumes found for used volume(s): {0}.".format(missing_share_str))
        binds_set = set(itertools.chain.from_iterable(all_binds))
        host_set = set(self.host.keys())
        missing_binds = binds_set - host_set
        if missing_binds:
            missing_mapped_str = ', '.join(missing_binds)
            raise MapIntegrityError("No host share found for mapped volume(s): {0}.".format(missing_mapped_str))
        if self.use_attached_parent_name:
            volume_set = binds_set.union(a[1] for a in itertools.chain.from_iterable(all_attached))
        else:
            volume_set = binds_set.union(all_attached_names)
        named_set = set(self.volumes.keys())
        missing_names = volume_set - named_set
        if missing_names:
            missing_names_str = ', '.join(missing_names)
            raise MapIntegrityError("No volume name-path-assignments found for volume(s): {0}.".format(missing_names_str))
        instance_set = set(itertools.chain.from_iterable(all_instances))
        linked_set = set(itertools.chain.from_iterable(all_links))
        missing_links = linked_set - instance_set
        if missing_links:
            missing_links_str = ', '.join(missing_links)
            raise MapIntegrityError("No container instance found for link(s): {0}.".format(missing_links_str))
        network_set = set(filter(None, all_networks))
        missing_networks = network_set - instance_set
        if missing_networks:
            missing_networks_str = ', '.join(missing_networks)
            raise MapIntegrityError("No container instance found for the following network reference(s): {0}".format(missing_networks_str))
