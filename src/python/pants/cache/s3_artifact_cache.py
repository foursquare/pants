# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from ConfigParser import ConfigParser, NoSectionError
from textwrap import dedent

import boto3
from botocore import exceptions
from botocore.config import Config
from botocore.vendored.requests import ConnectionError, Timeout
from botocore.vendored.requests.packages.urllib3.exceptions import ClosedPoolError
from six.moves.urllib.parse import urlparse

from pants.cache.artifact_cache import ArtifactCache, NonfatalArtifactCacheError, UnreadableArtifact
from pants.util.memo import memoized, memoized_property


logger = logging.getLogger(__name__)

_NETWORK_ERRORS = [
  ConnectionError, Timeout, ClosedPoolError,
  exceptions.EndpointConnectionError, exceptions.ChecksumError
]

# NOTE(mateo): Boto2 has a different set of configs/variables, this likely supports boto3 only.
_BOTO3_ENVS = {
  'profile': 'aws_profile',
  'access_key': 'aws_access_key_id',
  'secret_key': 'aws_secret_access_key',
}

# Used if the cache_setup options do not define a config_file option.
_BOTO3_CONFIG_DEFAULT_KWARGS = dict(connect_timeout=4, read_timeout=4)

# TODO: Read size is exposed both here and the restful client, should be wired as an option.
_READ_SIZE_BYTES = 4 * 1024 * 1024


class S3ConfigException(Exception):
  """Indicate a problem parsing or finding the config files for the s3 connection."""


@memoized
def _connect_to_s3(creds_file, config_file, profile_name):
  # Downgrading the boto logging since it spams the logs.
  # TODO(mateo): Wire a boto logging option.
  boto3.set_stream_logger(name='boto3.resources', level=logging.WARN)
  boto3.set_stream_logger(name='botocore', level=logging.WARN)
  auth_kwargs = {}
  if creds_file:
    config = ConfigParser()
    config.read(creds_file)
    try:
      auth_kwargs['aws_access_key_id'] = config.get(profile_name, 'aws_access_key_id')
      auth_kwargs['aws_secret_access_key'] = config.get(profile_name, 'aws_secret_access_key')
    except NoSectionError as e:
      # Actually raise here, since in this case we know that the user has passed a misconfigured
      # option or input and that would be surprisingly unapplied.
      raise S3ConfigException(dedent(
        """
        Credentials file appears malformed. Should approximate:

        [<profile>]
        aws_access_key_id = <access_key>
        aws_secret_access_key = <secret_key>

        """
      ))
  # If no cred_file is passed, we allow Boto to attempt to consume from its respected
  # environmental variables and/or traditional credential locations.
  session = boto3.Session(**auth_kwargs)
  config = config_file or Config(**_BOTO3_CONFIG_DEFAULT_KWARGS)
  return session.resource('s3', config=config)


def iter_content(body):
  while True:
    chunk = body.read(_READ_SIZE_BYTES)
    if not chunk:
      break
    yield chunk


def _not_found_error(e):
  if not isinstance(e, exceptions.ClientError):
    return False
  return e.response['Error']['Code'] in ('404', 'NoSuchKey')


def _network_error(e):
  return any(isinstance(e, cls) for cls in _NETWORK_ERRORS)

_NOT_FOUND = 0
_NETWORK = 1
_UNKNOWN = 2


def _log_and_classify_error(e, verb, cache_key):
  if _not_found_error(e):
    logger.debug('Not Found During {0} {1}'.format(verb, cache_key))
    return _NOT_FOUND
  if _network_error(e):
    logger.debug('Failed to {0} (network) {1}: {2}'.format(verb, cache_key, str(e)))
    return _NETWORK
  logger.debug('Failed to {0} (client) {1}: {2}'.format(verb, cache_key, str(e)))
  return _UNKNOWN


class S3ArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts on S3."""

  def __init__(self, creds_file, config_file, profile_name, artifact_root, s3_url, local):
    """
    :param str creds_file: Path that holds AWS credentials as understood by Boto.
    :param str config_file: Path that holds Boto config file.
    :param str profile_name: Specifies a profile set in the creds file for use byBoto.
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param str s3_url: URL of the form s3://bucket/path/to/store/artifacts.
    :param BaseLocalArtifactCache local: local cache instance for storing and creating artifacts.
    """
    super(S3ArtifactCache, self).__init__(artifact_root)
    url = urlparse(s3_url)
    self._creds_file = creds_file
    self._config_file = config_file
    self._path = url.path
    if self._path.startswith('/'):
      self._path = self._path[1:]
    self._localcache = local
    self._bucket = url.netloc
    self.profile_name = profile_name

  @memoized_property
  def creds_file(self):
    if self._creds_file and not os.path.isfile(self._creds_file):
      raise S3ConfigException(
        "Could not find passed AWS credentials file: {}".format(self._creds_file)
      )
    return self._creds_file

  @memoized_property
  def config_file(self):
    if self._config_file and not os.path.isfile(self._config_file):
      raise S3ConfigException(
        "Could not find passed Boto config file: {}".format(self._config_file)
      )
    return self._config_file

  @memoized_property
  def connection(self):
    return _connect_to_s3(self.creds_file, self.config_file, self.profile_name)

  def try_insert(self, cache_key, paths):
    logger.debug('Insert {0}'.format(cache_key))
    # Delegate creation of artifacts to the local cache
    with self._localcache.insert_paths(cache_key, paths) as tarfile:
      with open(tarfile, 'rb') as infile:
        # Upload artifact to the remote cache.
        try:
          response = self._get_object(cache_key).put(Body=infile)
          response_status = response['ResponseMetadata']['HTTPStatusCode']
          if response_status < 200 or response_status >= 300:
            raise NonfatalArtifactCacheError('Failed to PUT (http error) {0}: {1}'.format(
              cache_key, response_status))
        except Exception as e:
          raise NonfatalArtifactCacheError(
            'Failed to PUT (core error) {0}: {1}'.format(cache_key, str(e)))

  def has(self, cache_key):
    logger.debug('Has {0}'.format(cache_key))
    if self._localcache.has(cache_key):
      return True
    try:
      self._get_object(cache_key).load()
      return True
    except Exception as e:
      _log_and_classify_error(e, 'HEAD', cache_key)
      return False

  def use_cached_files(self, cache_key, results_dir=None):
    logger.debug('GET {0}'.format(cache_key))
    if self._localcache.has(cache_key):
      return self._localcache.use_cached_files(cache_key, results_dir)

    s3_object = self._get_object(cache_key)
    try:
      get_result = s3_object.get()
    except Exception as e:
      _log_and_classify_error(e, 'GET', cache_key)
      return False

    # Delegate storage and extraction to local cache
    body = get_result['Body']
    try:      
      return self._localcache.store_and_use_artifact(
        cache_key, iter_content(body), results_dir)
    except Exception as e:
      result = _log_and_classify_error(e, 'GET', cache_key)
      if result == _UNKNOWN:
        return UnreadableArtifact(cache_key, e)
      return False
    finally:
      body.close()

  def delete(self, cache_key):
    logger.debug("Delete {0}".format(cache_key))
    self._localcache.delete(cache_key)
    try:
      self._get_object(cache_key).delete()
    except Exception as e:
      _log_and_classify_error(e, 'DELETE', cache_key)

  def _get_object(self, cache_key):
    return self.connection.Object(self._bucket, self._path_for_key(cache_key))

  def _path_for_key(self, cache_key):
    return '{0}/{1}/{2}.tgz'.format(self._path, cache_key.id, cache_key.hash)
