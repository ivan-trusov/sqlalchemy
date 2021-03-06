# engine/row.py
# Copyright (C) 2005-2020 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

"""Define row constructs including :class:`.Row`."""


import operator

from .. import util
from ..sql import util as sql_util
from ..util.compat import collections_abc


MD_INDEX = 0  # integer index in cursor.description

# This reconstructor is necessary so that pickles with the C extension or
# without use the same Binary format.
try:
    # We need a different reconstructor on the C extension so that we can
    # add extra checks that fields have correctly been initialized by
    # __setstate__.
    from sqlalchemy.cresultproxy import safe_rowproxy_reconstructor

    # The extra function embedding is needed so that the
    # reconstructor function has the same signature whether or not
    # the extension is present.
    def rowproxy_reconstructor(cls, state):
        return safe_rowproxy_reconstructor(cls, state)


except ImportError:

    def rowproxy_reconstructor(cls, state):
        obj = cls.__new__(cls)
        obj.__setstate__(state)
        return obj


try:
    from sqlalchemy.cresultproxy import BaseRow

    _baserow_usecext = True
except ImportError:
    _baserow_usecext = False

    class BaseRow(object):
        __slots__ = ("_parent", "_data", "_keymap")

        def __init__(self, parent, processors, keymap, data):
            """Row objects are constructed by ResultProxy objects."""

            self._parent = parent

            self._data = tuple(
                [
                    proc(value) if proc else value
                    for proc, value in zip(processors, data)
                ]
            )
            self._keymap = keymap

        def __reduce__(self):
            return (
                rowproxy_reconstructor,
                (self.__class__, self.__getstate__()),
            )

        def _values_impl(self):
            return list(self)

        def __iter__(self):
            return iter(self._data)

        def __len__(self):
            return len(self._data)

        def __hash__(self):
            return hash(self._data)

        def _subscript_impl(self, key, ismapping):
            try:
                rec = self._keymap[key]
            except KeyError:
                rec = self._parent._key_fallback(key)
            except TypeError:
                # the non-C version detects a slice using TypeError.
                # this is pretty inefficient for the slice use case
                # but is more efficient for the integer use case since we
                # don't have to check it up front.
                if isinstance(key, slice):
                    return tuple(self._data[key])
                else:
                    raise

            mdindex = rec[MD_INDEX]
            if mdindex is None:
                self._parent._raise_for_ambiguous_column_name(rec)
            elif not ismapping and mdindex != key and not isinstance(key, int):
                self._parent._warn_for_nonint(key)

            # TODO: warn for non-int here, RemovedIn20Warning when available

            return self._data[mdindex]

        def _get_by_key_impl(self, key):
            return self._subscript_impl(key, False)

        def _get_by_key_impl_mapping(self, key):
            # the C code has two different methods so that we can distinguish
            # between tuple-like keys (integers, slices) and mapping-like keys
            # (strings, objects)
            return self._subscript_impl(key, True)

        def __getattr__(self, name):
            try:
                return self._get_by_key_impl_mapping(name)
            except KeyError as e:
                raise AttributeError(e.args[0])


class Row(BaseRow, collections_abc.Sequence):
    """Represent a single result row.

    The :class:`.Row` object represents a row of a database result.  It is
    typically associated in the 1.x series of SQLAlchemy with the
    :class:`.ResultProxy` object, however is also used by the ORM for
    tuple-like results as of SQLAlchemy 1.4.

    The :class:`.Row` object seeks to act as much like a Python named
    tuple as possible.   For mapping (i.e. dictionary) behavior on a row,
    such as testing for containment of keys, refer to the :attr:`.Row._mapping`
    attribute.

    .. seealso::

        :ref:`coretutorial_selecting` - includes examples of selecting
        rows from SELECT statements.

        :class:`.LegacyRow` - Compatibility interface introduced in SQLAlchemy
        1.4.

    .. versionchanged:: 1.4

        Renamed ``RowProxy`` to :class:`.Row`.  :class:`.Row` is no longer a
        "proxy" object in that it contains the final form of data within it,
        and now acts mostly like a named tuple.  Mapping-like functionality is
        moved to the :attr:`.Row._mapping` attribute, but will remain available
        in SQLAlchemy 1.x series via the :class:`.LegacyRow` class that is used
        by :class:`.ResultProxy`.   See :ref:`change_4710_core` for background
        on this change.

    """

    __slots__ = ()

    @property
    def _mapping(self):
        """Return a :class:`.RowMapping` for this :class:`.Row`.

        This object provides a consistent Python mapping (i.e. dictionary)
        interface for the data contained within the row.   The :class:`.Row`
        by itself behaves like a named tuple, however in the 1.4 series of
        SQLAlchemy, the :class:`.LegacyRow` class is still used by Core which
        continues to have mapping-like behaviors against the row object
        itself.

        .. seealso::

            :attr:`.Row._fields`

        .. versionadded:: 1.4

        """

        return RowMapping(self)

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]

    def __getstate__(self):
        return {"_parent": self._parent, "_data": self._data}

    def __setstate__(self, state):
        self._parent = parent = state["_parent"]
        self._data = state["_data"]
        self._keymap = parent._keymap

    def _op(self, other, op):
        return (
            op(tuple(self), tuple(other))
            if isinstance(other, Row)
            else op(tuple(self), other)
        )

    __hash__ = BaseRow.__hash__

    def __lt__(self, other):
        return self._op(other, operator.lt)

    def __le__(self, other):
        return self._op(other, operator.le)

    def __ge__(self, other):
        return self._op(other, operator.ge)

    def __gt__(self, other):
        return self._op(other, operator.gt)

    def __eq__(self, other):
        return self._op(other, operator.eq)

    def __ne__(self, other):
        return self._op(other, operator.ne)

    def __repr__(self):
        return repr(sql_util._repr_row(self))

    @util.deprecated_20(
        ":meth:`.Row.keys`",
        alternative="Use the namedtuple standard accessor "
        ":attr:`.Row._fields`, or for full mapping behavior use  "
        "row._mapping.keys() ",
    )
    def keys(self):
        """Return the list of keys as strings represented by this
        :class:`.Row`.

        This method is analogous to the Python dictionary ``.keys()`` method,
        except that it returns a list, not an iterator.

        .. seealso::

            :attr:`.Row._fields`

            :attr:`.Row._mapping`

        """
        return [k for k in self._parent.keys if k is not None]

    @property
    def _fields(self):
        """Return a tuple of string keys as represented by this
        :class:`.Row`.

        This attribute is analogous to the Python named tuple ``._fields``
        attribute.

        .. versionadded:: 1.4

        .. seealso::

            :attr:`.Row._mapping`

        """
        return tuple([k for k in self._parent.keys if k is not None])

    def _asdict(self):
        """Return a new dict which maps field names to their corresponding
        values.

        This method is analogous to the Python named tuple ``._asdict()``
        method, and works by applying the ``dict()`` constructor to the
        :attr:`.Row._mapping` attribute.

        .. versionadded:: 1.4

        .. seealso::

            :attr:`.Row._mapping`

        """
        return dict(self._mapping)

    def _replace(self):
        raise NotImplementedError()

    @property
    def _field_defaults(self):
        raise NotImplementedError()


class LegacyRow(Row):
    """A subclass of :class:`.Row` that delivers 1.x SQLAlchemy behaviors
    for Core.

    The :class:`.LegacyRow` class is where most of the Python mapping
    (i.e. dictionary-like)
    behaviors are implemented for the row object.  The mapping behavior
    of :class:`.Row` going forward is accessible via the :class:`.Row._mapping`
    attribute.

    .. versionadded:: 1.4 - added :class:`.LegacyRow` which encapsulates most
       of the deprecated behaviors of :class:`.Row`.

    """

    def __contains__(self, key):
        return self._parent._contains(key, self)

    def __getitem__(self, key):
        return self._get_by_key_impl(key)

    @util.deprecated(
        "1.4",
        "The :meth:`.LegacyRow.has_key` method is deprecated and will be "
        "removed in a future release.  To test for key membership, use "
        "the :attr:`Row._mapping` attribute, i.e. 'key in row._mapping`.",
    )
    def has_key(self, key):
        """Return True if this :class:`.LegacyRow` contains the given key.

        Through the SQLAlchemy 1.x series, the ``__contains__()`` method of
        :class:`.Row` (or :class:`.LegacyRow` as of SQLAlchemy 1.4)  also links
        to :meth:`.Row.has_key`, in that an expression such as ::

            "some_col" in row

        Will return True if the row contains a column named ``"some_col"``,
        in the way that a Python mapping works.

        However, it is planned that the 2.0 series of SQLAlchemy will reverse
        this behavior so that ``__contains__()`` will refer to a value being
        present in the row, in the way that a Python tuple works.

        .. seealso::

            :ref:`change_4710_core`

        """

        return self._parent._has_key(key)

    @util.deprecated(
        "1.4",
        "The :meth:`.LegacyRow.items` method is deprecated and will be "
        "removed in a future release.  Use the :attr:`Row._mapping` "
        "attribute, i.e., 'row._mapping.items()'.",
    )
    def items(self):
        """Return a list of tuples, each tuple containing a key/value pair.

        This method is analogous to the Python dictionary ``.items()`` method,
        except that it returns a list, not an iterator.

        """

        return [(key, self[key]) for key in self.keys()]

    @util.deprecated(
        "1.4",
        "The :meth:`.LegacyRow.iterkeys` method is deprecated and will be "
        "removed in a future release.  Use the :attr:`Row._mapping` "
        "attribute, i.e., 'row._mapping.keys()'.",
    )
    def iterkeys(self):
        """Return a an iterator against the :meth:`.Row.keys` method.

        This method is analogous to the Python-2-only dictionary
        ``.iterkeys()`` method.

        """
        return iter(self._parent.keys)

    @util.deprecated(
        "1.4",
        "The :meth:`.LegacyRow.itervalues` method is deprecated and will be "
        "removed in a future release.  Use the :attr:`Row._mapping` "
        "attribute, i.e., 'row._mapping.values()'.",
    )
    def itervalues(self):
        """Return a an iterator against the :meth:`.Row.values` method.

        This method is analogous to the Python-2-only dictionary
        ``.itervalues()`` method.

        """
        return iter(self)

    @util.deprecated(
        "1.4",
        "The :meth:`.LegacyRow.values` method is deprecated and will be "
        "removed in a future release.  Use the :attr:`Row._mapping` "
        "attribute, i.e., 'row._mapping.values()'.",
    )
    def values(self):
        """Return the values represented by this :class:`.Row` as a list.

        This method is analogous to the Python dictionary ``.values()`` method,
        except that it returns a list, not an iterator.

        """

        return self._values_impl()


BaseRowProxy = BaseRow
RowProxy = Row


class ROMappingView(
    collections_abc.KeysView,
    collections_abc.ValuesView,
    collections_abc.ItemsView,
):
    __slots__ = (
        "_mapping",
        "_items",
    )

    def __init__(self, mapping, items):
        self._mapping = mapping
        self._items = items

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return "{0.__class__.__name__}({0._mapping!r})".format(self)

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, item):
        return item in self._items

    def __eq__(self, other):
        return list(other) == list(self)

    def __ne__(self, other):
        return list(other) != list(self)


class RowMapping(collections_abc.Mapping):
    """A ``Mapping`` that maps column names and objects to :class:`.Row` values.

    The :class:`.RowMapping` is available from a :class:`.Row` via the
    :attr:`.Row._mapping` attribute and supplies Python mapping (i.e.
    dictionary) access to the  contents of the row.   This includes support
    for testing of containment of specific keys (string column names or
    objects), as well as iteration of keys, values, and items::

        for row in result:
            if 'a' in row._mapping:
                print("Column 'a': %s" % row._mapping['a'])

            print("Column b: %s" % row._mapping[table.c.b])


    .. versionadded:: 1.4 The :class:`.RowMapping` object replaces the
       mapping-like access previously provided by a database result row,
       which now seeks to behave mostly like a named tuple.

    """

    __slots__ = ("row",)

    def __init__(self, row):
        self.row = row

    def __getitem__(self, key):
        return self.row._get_by_key_impl_mapping(key)

    def __iter__(self):
        return (k for k in self.row._parent.keys if k is not None)

    def __len__(self):
        return len(self.row)

    def __contains__(self, key):
        return self.row._parent._has_key(key)

    def items(self):
        """Return a view of key/value tuples for the elements in the
        underlying :class:`.Row`.

        """
        return ROMappingView(self, [(key, self[key]) for key in self.keys()])

    def keys(self):
        """Return a view of 'keys' for string column names represented
        by the underlying :class:`.Row`.

        """
        return ROMappingView(
            self, [k for k in self.row._parent.keys if k is not None]
        )

    def values(self):
        """Return a view of values for the values represented in the
        underlying :class:`.Row`.

        """
        return ROMappingView(self, self.row._values_impl())
