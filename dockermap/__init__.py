# -*- coding: utf-8 -*-
from __future__ import unicode_literals


__version__ = '1.0.0'

DEFAULT_BASEIMAGE = 'tianon/true:latest'
DEFAULT_COREIMAGE = 'busybox:latest'
DEFAULT_HOSTNAME_REPLACEMENT = [
    ('_', '-'),
    ('.', '-'),
]
DEFAULT_PRESET_NETWORKS = 'host', 'bridge', 'none'
