# -*- coding: utf-8 -*-
from __future__ import unicode_literals


__version__ = '0.8.0.dev0'

DEFAULT_BASEIMAGE = 'tianon/true:latest'
DEFAULT_COREIMAGE = 'busybox:latest'
DEFAULT_HOSTNAME_REPLACEMENT = [
    ('_', '-'),
    ('.', '-'),
]
