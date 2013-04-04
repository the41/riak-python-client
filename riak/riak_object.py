"""
Copyright 2010 Rusty Klophaus <rusty@basho.com>
Copyright 2010 Justin Sheehy <justin@basho.com>
Copyright 2009 Jay Baird <jay@mochimedia.com>

This file is provided to you under the Apache License,
Version 2.0 (the "License"); you may not use this file
except in compliance with the License.  You may obtain
a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""
from riak import RiakError
from riak.util import deprecated


class RiakObject(object):
    """
    The RiakObject holds meta information about a Riak object, plus the
    object's data.
    """
    def __init__(self, client, bucket, key=None):
        """
        Construct a new RiakObject.

        :param client: A RiakClient object.
        :type client: :class:`RiakClient <riak.client.RiakClient>`
        :param bucket: A RiakBucket object.
        :type bucket: :class:`RiakBucket <riak.bucket.RiakBucket>`
        :param key: An optional key. If not specified, then the key
         is generated by the server when :func:`store` is called.
        :type key: string
        """
        try:
            if isinstance(key, basestring):
                key = key.encode('ascii')
        except UnicodeError:
            raise TypeError('Unicode keys are not supported.')

        if key is not None and len(key) == 0:
            raise ValueError('Key name must either be "None"'
                             ' or a non-empty string.')

        self.client = client
        self.bucket = bucket
        self.key = key
        self._data = None
        self._encoded_data = None
        self.vclock = None
        self.charset = None
        self.content_type = 'application/json'
        self.content_encoding = None
        self.usermeta = {}
        self.indexes = set()
        self.links = []
        self.siblings = []
        self.exists = False

    def __hash__(self):
        return hash((self.key, self.bucket, self.vclock))

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return hash(self) == hash(other)
        else:
            return False

    def __ne__(self, other):
        if isinstance(other, self.__class__):
            return hash(self) != hash(other)
        else:
            return True

    def _get_data(self):
        if self._encoded_data is not None and self._data is None:
            self._data = self._deserialize(self._encoded_data)
            self._encoded_data = None
        return self._data

    def _set_data(self, value):
        self._encoded_data = None
        self._data = value

    data = property(_get_data, _set_data, doc="""
        The data stored in this object, as Python objects. For the raw
        data, use the `encoded_data` property. If unset, accessing
        this property will result in decoding the `encoded_data`
        property into Python values. The decoding is dependent on the
        `content_type` property and the bucket's registered decoders.
        :type mixed """)

    def get_encoded_data(self):
        deprecated("`get_encoded_data` is deprecated, use the `encoded_data`"
                   " property")
        return self.encoded_data

    def set_encoded_data(self, value):
        deprecated("`set_encoded_data` is deprecated, use the `encoded_data`"
                   " property")
        self.encoded_data = value

    def _get_encoded_data(self):
        if self._data is not None and self._encoded_data is None:
            self._encoded_data = self._serialize(self._data)
            self._data = None
        return self._encoded_data

    def _set_encoded_data(self, value):
        self._data = None
        self._encoded_data = value

    encoded_data = property(_get_encoded_data, _set_encoded_data, doc="""
        The raw data stored in this object, essentially the encoded
        form of the `data` property. If unset, accessing this property
        will result in encoding the `data` property into a string. The
        encoding is dependent on the `content_type` property and the
        bucket's registered encoders.
        :type basestring""")

    def _serialize(self, value):
        encoder = self.bucket.get_encoder(self.content_type)
        if encoder:
            return encoder(value)
        elif isinstance(value, basestring):
            return value.encode()
        else:
            raise TypeError('No encoder for non-string data '
                            'with content type "{0}"'.
                            format(self.content_type))

    def _deserialize(self, value):
        decoder = self.bucket.get_decoder(self.content_type)
        if decoder:
            return decoder(value)
        else:
            raise TypeError('No decoder for content type "{0}"'.
                            format(self.content_type))

    def add_index(self, field, value):
        """
        Tag this object with the specified field/value pair for
        indexing.

        :param field: The index field.
        :type field: string
        :param value: The index value.
        :type value: string or integer
        :rtype: RiakObject
        """
        if field[-4:] not in ("_bin", "_int"):
            raise RiakError("Riak 2i fields must end with either '_bin'"
                            " or '_int'.")

        self.indexes.add((field, value))

        return self

    def remove_index(self, field=None, value=None):
        """
        Remove the specified field/value pair as an index on this
        object.

        :param field: The index field.
        :type field: string
        :param value: The index value.
        :type value: string or integer
        :rtype: RiakObject
        """
        if not field and not value:
            self.indexes.clear()
        elif field and not value:
            for index in [x for x in self.indexes if x[0] == field]:
                self.indexes.remove(index)
        elif field and value:
            self.indexes.remove((field, value))
        else:
            raise RiakError("Cannot pass value without a field"
                            " name while removing index")

        return self

    remove_indexes = remove_index

    def add_link(self, obj, tag=None):
        """
        Add a link to a RiakObject.

        :param obj: Either a RiakObject or 3 item link tuple consisting
            of (bucket, key, tag).
        :type obj: mixed
        :param tag: Optional link tag. Defaults to bucket name. It is ignored
            if ``obj`` is a 3 item link tuple.
        :type tag: string
        :rtype: RiakObject
        """
        if isinstance(obj, tuple):
            newlink = obj
        else:
            newlink = (obj.bucket.name, obj.key, tag)

        self.links.append(newlink)
        return self

    def store(self, w=None, dw=None, pw=None, return_body=True,
              if_none_match=False):
        """
        Store the object in Riak. When this operation completes, the
        object could contain new metadata and possibly new data if Riak
        contains a newer version of the object according to the object's
        vector clock.

        :param w: W-value, wait for this many partitions to respond
         before returning to client.
        :type w: integer
        :param dw: DW-value, wait for this many partitions to
         confirm the write before returning to client.
        :type dw: integer

        :param pw: PW-value, require this many primary partitions to
                   be available before performing the put
        :type pw: integer
        :param return_body: if the newly stored object should be
                            retrieved
        :type return_body: bool
        :param if_none_match: Should the object be stored only if
                              there is no key previously defined
        :type if_none_match: bool
        :rtype: RiakObject """
        if (self.siblings and not self._data
                and not self._encoded_data and not self.vclock):
            raise RiakError("Attempting to store an invalid object,"
                            "store one of the siblings instead")

        if self.key is None:
            result = self.client.put_new(
                self, w=w, dw=dw, pw=pw,
                return_body=return_body,
                if_none_match=if_none_match)
            self._populate(result)
        else:
            result = self.client.put(self, w=w, dw=dw, pw=pw,
                                     return_body=return_body,
                                     if_none_match=if_none_match)
            if result is not None and result != ('', []):
                self._populate(result)

        return self

    def reload(self, r=None, pr=None, vtag=None):
        """
        Reload the object from Riak. When this operation completes, the
        object could contain new metadata and a new value, if the object
        was updated in Riak since it was last retrieved.

        :param r: R-Value, wait for this many partitions to respond
         before returning to client.
        :type r: integer
        :rtype: RiakObject
        """

        result = self.client.get(self, r=r, pr=pr, vtag=vtag)
        if result and result != ('', []):
            self._populate(result)
        else:
            self.clear()

        return self

    def delete(self, rw=None, r=None, w=None, dw=None, pr=None, pw=None):
        """
        Delete this object from Riak.

        :param rw: RW-value. Wait until this many partitions have
            deleted the object before responding. (deprecated in Riak
            1.0+, use R/W/DW)
        :type rw: integer
        :param r: R-value, wait for this many partitions to read object
         before performing the put
        :type r: integer
        :param w: W-value, wait for this many partitions to respond
         before returning to client.
        :type w: integer
        :param dw: DW-value, wait for this many partitions to
         confirm the write before returning to client.
        :type dw: integer
        :param pr: PR-value, require this many primary partitions to
                   be available before performing the read that
                   precedes the put
        :type pr: integer
        :param pw: PW-value, require this many primary partitions to
                   be available before performing the put
        :type pw: integer
        :rtype: RiakObject
        """

        self.client.delete(self, rw=rw, r=r, w=w, dw=dw, pr=pr, pw=pw)
        self.clear()
        return self

    def clear(self):
        """
        Reset this object.

        :rtype: RiakObject
        """
        self.headers = []
        self.links = []
        self.data = None
        self.exists = False
        self.siblings = []
        return self

    def _populate(self, result):
        """
        Populate the object based on the return from get.

        If None returned, then object is not found
        If a tuple of vclock, contents then one or more
        whole revisions of the key were found
        If a list of vtags is returned there are multiple
        sibling that need to be retrieved with get.
        """
        if result is None or result is self:
            return self
        elif type(result) is RiakObject:
            self.clear()
            self.__dict__ = result.__dict__.copy()
        else:
            raise RiakError("do not know how to handle type %s" % type(result))

    def get_sibling(self, i, r=None, pr=None):
        """
        Retrieve a sibling by sibling number.

        :param i: Sibling number.
        :type i: integer
        :param r: R-Value. Wait until this many partitions
            have responded before returning to client.
        :type r: integer
        :rtype: RiakObject.
        """
        if isinstance(self.siblings[i], RiakObject):
            return self.siblings[i]
        else:
            # Run the request...
            vtag = self.siblings[i]
            obj = RiakObject(self.client, self.bucket, self.key)
            obj.reload(r=r, pr=pr, vtag=vtag)

            # And make sure it knows who its siblings are
            self.siblings[i] = obj
            obj.siblings = self.siblings
            return obj

    def add(self, *args):
        """
        Start assembling a Map/Reduce operation.
        A shortcut for :func:`RiakMapReduce.add`.

        :rtype: RiakMapReduce
        """
        mr = RiakMapReduce(self.client)
        mr.add(self.bucket.name, self.key)
        return mr.add(*args)

    def link(self, *args):
        """
        Start assembling a Map/Reduce operation.
        A shortcut for :func:`RiakMapReduce.link`.

        :rtype: RiakMapReduce
        """
        mr = RiakMapReduce(self.client)
        mr.add(self.bucket.name, self.key)
        return mr.link(*args)

    def map(self, *args):
        """
        Start assembling a Map/Reduce operation.
        A shortcut for :func:`RiakMapReduce.map`.

        :rtype: RiakMapReduce
        """
        mr = RiakMapReduce(self.client)
        mr.add(self.bucket.name, self.key)
        return mr.map(*args)

    def reduce(self, *args):
        """
        Start assembling a Map/Reduce operation.
        A shortcut for :func:`RiakMapReduce.reduce`.

        :rtype: RiakMapReduce
        """
        mr = RiakMapReduce(self.client)
        mr.add(self.bucket.name, self.key)
        return mr.reduce(*args)

from riak.mapreduce import RiakMapReduce
