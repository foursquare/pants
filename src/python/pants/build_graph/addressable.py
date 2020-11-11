# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod

from pants.base.build_file_target_factory import BuildFileTargetFactory


class Addressable(ABC):
    """An ABC for classes which would like instances to be named and exported from BUILD files."""

    class Factory(BuildFileTargetFactory):
        """Captures addressable instances from BUILD file calls."""

        @abstractmethod
        def capture(self, *args, **kwargs):
            """Captures the arguments passed to an addressable alias in a BUILD file.

            :returns: An addressable instance representing the call capture.
            :rtype: :class:`Addressable`
            """

        def __str__(self):
            return "{}(target_types={})".format(type(self).__name__, self.target_types)

    class AddressableInitError(Exception):
        """Indicates a problem capturing arguments to create a new :class:`Addressable`."""

    def __init__(self, addressed_alias, addressed_type):
        self._addressed_alias = addressed_alias
        self._addressed_type = addressed_type

    @property
    def addressed_alias(self):
        """The alias via which this addressable was invoked.

        :rtype: string
        """
        return self._addressed_alias

    @property
    def addressed_type(self):
        """The type this addressable captures calls to and ultimately can `instantiate`.

        :returns: The class of the addressed type this addressable proxies for.
        :rtype: type
        """
        return self._addressed_type

    @property
    def addressed_name(self):
        """This property is inspected by AddressableCallProxy to automatically name Addressables.

        Generally, a subclass will inspect its captured arguments and return, for example, the
        captured `name` parameter.  A value of `None` (the default) causes AddressableCallProxy   to
        skip capturing and naming this instance.
        """
        return None

    def instantiate(self, *args, **kwargs):
        """Realizes the captured addressable call as an instance of the aliased object type.

        :returns: A fully hydrated addressable object.
        """
        return self.addressed_type(*args, **kwargs)
