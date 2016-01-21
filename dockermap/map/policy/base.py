# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

from six import iteritems

from ... import DEFAULT_COREIMAGE, DEFAULT_BASEIMAGE
from ...functional import resolve_value
from .cache import ContainerCache, ImageCache
from .dep import ContainerDependencyResolver

log = logging.getLogger(__name__)


class BasePolicy(object):
    """
    Abstract base class providing the basic infrastructure for generating actions based on container state.

    :param container_maps: Container maps.
    :type container_maps: dict[unicode | str, dockermap.map.container.ContainerMap]
    :param clients: Dictionary of clients.
    :type clients: dict[unicode | str, dockermap.map.config.ClientConfiguration]
    """
    core_image = DEFAULT_COREIMAGE
    base_image = DEFAULT_BASEIMAGE

    def __init__(self, container_maps, clients):
        self._maps = {
            map_name: map_contents.get_extended_map()
            for map_name, map_contents in iteritems(container_maps)
        }
        self._clients = clients
        self._container_names = ContainerCache(clients)
        self._images = ImageCache(clients)
        self._f_resolver = ContainerDependencyResolver()
        for m in self._maps.values():
            self._f_resolver.update(m)
        self._r_resolver = ContainerDependencyResolver()
        for m in self._maps.values():
            self._r_resolver.update_backward(m)

    @classmethod
    def get_default_client_name(cls):
        """
        Determines a default client name.

        :return: Default client name.
        """
        return '__default__'

    @classmethod
    def cname(cls, map_name, container, instance=None):
        """
        Generates a container name that should be used for creating new containers and checking the status of existing
        containers.

        In this implementation, the format will be ``<map name>.<container name>.<instance>`` name. If no instance is
        provided, it is just ``<map name>.<container name>``.

        :param map_name: Container map name.
        :type map_name: unicode | str
        :param container: Container configuration name.
        :type container: unicode | str
        :param instance: Instance name (optional).
        :type instance: unicode | str
        :return: Container name.
        :rtype: unicode | str
        """
        if instance:
            return '{0}.{1}.{2}'.format(map_name, container, instance)
        return '{0}.{1}'.format(map_name, container)

    @classmethod
    def aname(cls, map_name, attached_name, parent_name=None):
        """
        Generates a container name that should be used for creating new attached volume containers and checking the
        status of existing containers.

        In this implementation, the format will be ``<map name>.<attached>``, or ``<map name>.<parent name>.<attached>``
        if the parent container configuration name is provided.

        :param map_name: Container map name.
        :type map_name: unicode | str
        :param attached_name: Attached container alias.
        :type attached_name: unicode | str
        :param parent_name: Container configuration name that has contains attached container.
        :type parent_name: unicode | str
        :return: Container name.
        :rtype: unicode | str
        """
        if parent_name:
            return '{0}.{1}.{2}'.format(map_name, parent_name, attached_name)
        return '{0}.{1}'.format(map_name, attached_name)

    @classmethod
    def resolve_cname(cls, container_name, includes_map=True):
        """
        The reverse function of :meth:`cname` for resolving a container name into map name, container configuration,
        and instance name. The instance name may be ``None`` if not present. In case the map name is not present
        in the container name, ``includes_map`` should be set to ``False`` for only resolving configuration name and map
        name.

        :param container_name: Container name.
        :type container_name: unicode | str
        :param includes_map: Whether the name includes a map name (e.g. for running containers) or not (e.g. for
         references within the same map).
        :return: Tuple of container map name (optional), container configuration name, and instance.
        :rtype: tuple[unicode | str]
        """
        if includes_map:
            map_name, __, ci_name = container_name.partition('.')
            if not ci_name:
                raise ValueError("Invalid container name: {0}".format(container_name))
            c_name, __, i_name = ci_name.partition('.')
            return map_name, c_name, i_name or None

        c_name, __, i_name = container_name.partition('.')
        return c_name, i_name or None

    @classmethod
    def iname(cls, container_map, image):
        """
        Generates the full image name that should be used when creating a new container.

        This implementation applies the following rules:

        * If the image name starts with ``/``, the following image name is returned.
        * If ``/`` is found anywhere else in the image name, it is assumed to be a repository-prefixed image and
          returned as it is.
        * Otherwise, if the given container map has a repository prefix set, this is prepended to the image name.
        * In any other case, the image name is returned unmodified.

        In any case this method is indifferent to whether a tag is appended or not. Docker by default uses the image
        with the ``latest`` tag.

        :param container_map: Container map object.
        :type container_map: dockermap.map.container.ContainerMap
        :param image: Image name.
        :type image: unicode | str.
        :return: Image name, where applicable prefixed with a repository.
        :rtype: unicode | str
        """
        if '/' in image:
            if image[0] == '/':
                return image[1:]
            return image
        repository = resolve_value(container_map.repository)
        if repository:
            return '{0}/{1}'.format(repository, image)
        return image

    def get_clients(self, c_config, c_map):
        """
        Returns the Docker client objects for a given container configuration or map. If there are no clients specified
        for the configuration, the list defaults to the one globally specified for the given map. If that is not defined
        either, the default client is returned.

        :param c_config: Container configuration object.
        :type c_config: dockermap.map.config.ContainerConfiguration
        :param c_map: Container map instance.
        :type c_map: dockermap.map.container.ContainerMap
        :return: Docker client objects.
        :rtype: tuple[tuple[unicode | str, docker.client.Client, dockermap.map.config.ClientConfiguration]]
        """
        def _get_client(client_name):
            client_config = self._clients[client_name]
            return client_name, client_config.get_client(), client_config

        if c_config.clients:
            return tuple(map(_get_client, c_config.clients))
        if c_map.clients:
            return tuple(map(_get_client, c_map.clients))
        default_name = self.get_default_client_name()
        return _get_client(default_name),

    def get_dependencies(self, map_name, container):
        """
        Generates the list of dependency containers, in reverse order (i.e. the last dependency coming first).

        :param map_name: Container map name.
        :type map_name: unicode | str
        :param container: Container configuration name.
        :type container: unicode | str
        :return: Dependency container map names, container configuration names, and instances.
        :rtype: iterator[(unicode | str, unicode | str, unicode | str)]
        """
        return reversed(self._f_resolver.get_container_dependencies(map_name, container))

    def get_dependents(self, map_name, container):
        """
        Generates the list of dependent containers, in reverse order (i.e. the last dependent coming first).

        :param map_name: Container map name.
        :type map_name: unicode | str
        :param container: Container configuration name.
        :type container: unicode | str
        :return: Dependent container map names, container configuration names, and instances.
        :rtype: iterator[(unicode | str, unicode | str, unicode | str)]
        """
        return reversed(self._r_resolver.get_container_dependencies(map_name, container))

    @property
    def container_maps(self):
        """
        Container maps with container configurations to base actions on.

        :return: Dictionary of container maps.
        :rtype: dict[unicode | str, dockermap.map.container.ContainerMap]
        """
        return self._maps

    @property
    def clients(self):
        """
        Docker client objects and configurations.

        :return: Dictionary of Docker client objects.
        :rtype: dict[unicode | str, dockermap.map.config.ClientConfiguration]
        """
        return self._clients

    @property
    def container_names(self):
        """
        Names of existing containers on each map.

        :return: Dictionary of container names.
        :rtype: dict[unicode | str, dockermap.map.policy.cache.CachedContainerNames]
        """
        return self._container_names

    @property
    def images(self):
        """
        Image information functions.

        :return: Dictionary of image names per client.
        :rtype: dict[unicode | str, dockermap.map.policy.cache.CachedImages]
        """
        return self._images
