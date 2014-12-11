# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import six


def extract_user(user):
    """
    Extract the user for running a container from the following possible input formats:

    * Integer (UID)
    * User name string
    * Tuple of ``user, group``
    * String in the format ``user:group``

    :param user: User name, uid, user-group tuple, or user:group string.
    :type user: int or tuple or unicode
    :return: User name or id.
    :rtype: unicode
    """
    if not user and user != 0 and user != '0':
        return None
    if isinstance(user, tuple):
        return user[0]
    if isinstance(user, int):
        return six.text_type(user)
    return user.partition(':')[0]


def update_kwargs(kwargs, *updates):
    """
    Utility function for merging multiple keyword arguments, depending on their type:

    * Non-existent keys are added.
    * Existing lists are extended (the kwargs entry should be a list, whereas the following updates can also be tuples).
    * Nested dictionaries are updated, overriding previous key-value assignments.
    * Other items are simply overwritten (just like in a regular dictionary update).

    Lists/tuples and dictionaries are (shallow-)copied before adding. This function does not recurse.

    :param kwargs: Base keyword arguments.
    :type kwargs: dict
    :param updates: Dictionaries to update ``kwargs`` with.
    :type updates: tuple[dict]
    :return: A merged dictionary of keyword arguments.
    :rtype: dict
    """
    for update in updates:
        if not update:
            continue
        for key, u_item in six.iteritems(update):
            if not u_item:
                continue
            kw_item = kwargs.get(key)
            if isinstance(u_item, (tuple, list)):
                if kw_item:
                    kw_item.extend(u_item)
                else:
                    kwargs[key] = u_item[:]
            elif isinstance(u_item, dict):
                if kw_item:
                    kw_item.update(u_item)
                else:
                    kwargs[key] = u_item.copy()
            else:
                kwargs[key] = u_item


def init_options(options):
    """
    Initialize ``create_options`` or  ``start_options`` of a container configuration. If ``options`` is a callable, it
    is run to initialize the values, otherwise it simply returns ``options`` or an empty dictionary.

    :param options: Options as a dictionary.
    :type options: callable or dict
    :return: Initial keyword arguments.
    :rtype: dict
    """
    if options:
        if callable(options):
            return options()
        return options
    return dict()


def get_host_binds(container_map, config, instance):
    """
    Generates the dictionary of host volumes of a container configuration.

    :param container_map: Container map.
    :type container_map: dockermap.map.container.ContainerMap
    :param config: Container configuration.
    :type config: dockermap.map.config.ContainerConfiguration
    :param instance: Instance name. Pass ``None`` if not applicable.
    :type instance: unicode
    :return: Dictionary of shared volumes with host volumes and the read-only flag.
    :rtype: dict
    """
    def _gen_binds():
        for alias, readonly in config.binds:
            share = container_map.host.get(alias, instance)
            if share:
                bind = dict(bind=container_map.volumes[alias], ro=readonly)
                yield share, bind

    return dict(_gen_binds())