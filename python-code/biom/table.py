#!/usr/bin/env python

"""Core BIOM objects for dense and sparse tables"""
from __future__ import division

import re
from datetime import datetime
from json import dumps
from types import NoneType
from operator import itemgetter, xor, add
from itertools import izip
from collections import defaultdict, Hashable
from numpy import ndarray, asarray, array, newaxis, zeros

__author__ = "Daniel McDonald"
__copyright__ = "Copyright 2012, BIOM-Format Project"
__credits__ = ["Daniel McDonald", "Jai Rideout", "Greg Caporaso", 
               "Jose Clemente", "Justin Kuczynski"]
__license__ = "GPL"
__url__ = "http://biom-format.org"
__version__ = "0.9dev"
__maintainer__ = "Daniel McDonald"
__email__ = "daniel.mcdonald@colorado.edu"
__status__ = "Prototype"

# should these be centralized?
def get_biom_format_version_string():
    """Returns the current Biom file format version."""
    return "Biological Observation Matrix %s" % __version__
 
def get_biom_format_url_string():
    """Returns the current Biom file format description URL."""
    return __url__

def unzip(items):
    """Performs the reverse of zip, i.e. produces separate lists from tuples.

    items should be list of k-element tuples. Will raise exception if any tuples
    contain more items than the first one.

    Conceptually equivalent to transposing the matrix of tuples.

    Returns list of lists in which the ith list contains the ith element of each
    tuple.

    Note: zip expects *items rather than items, such that unzip(zip(*items))
    returns something that compares equal to items.

    Always returns lists: does not check original data type, but will accept
    any sequence.

    Method pulled from PyCogent (http://pycogent.sourceforge.net)
    """
    if items:
        return map(list, zip(*items))
    else:
        return []

def flatten(items):
    """Removes one level of nesting from items.

    items can be any sequence, but flatten always returns a list.

    Method pulled from PyCogent (http://pycogent.sourceforge.net) 
    """
    result = [] 
    for i in items:
        try: 
            result.extend(i)
        except:
            result.append(i)
    return result

def _natsort_key(item):
    """Provides normalized version of item for sorting with digits.

    Method pulled from QIIME (http://qiime.org), based on:
    http://lists.canonical.org/pipermail/kragen-hacks/2005-October/000419.html
    """
    item = str(item)
    try:
        chunks = re.split('(\d+(?:\.\d+)?)', item)
    except TypeError:
        # if item is a tuple or list (i.e., indexable, but not a string)
        # work with the first element
        chunks = re.split('(\d+(?:\.\d+)?)', item[0])
    for ii in range(len(chunks)):
        if chunks[ii] and chunks[ii][0] in '0123456789':
            if '.' in chunks[ii]: numtype = float
            else: numtype = int 
            # wrap in tuple with '0' to explicitly specify numbers come first
            chunks[ii] = (0, numtype(chunks[ii]))
        else:
            chunks[ii] = (1, chunks[ii])
    return (chunks, item)

def natsort(seq):
    """Sort a sequence of text strings in a reasonable order.

    Method pulled from QIIME (http://qiime.org), based on:
    http://lists.canonical.org/pipermail/kragen-hacks/2005-October/000419.html
    """
    alist = list(seq)
    alist.sort(key=_natsort_key)
    return alist

class TableException(Exception):
    pass

class UnknownID(TableException):
    pass

class SparseDict(dict):
    """Support for sparse dicts

    Must specify rows and columns in advance

    Object cannot "grow" in shape

    There is additional overhead on inserts in order to support rapid lookups
    across rows or columns
    """

    def __init__(self, rows, cols, dtype=float):
        self.shape = (rows, cols) 
        self.dtype = dtype # casting is minimal, trust the programmer...
        self._index_rows = [set() for i in range(rows)]
        self._index_cols = [set() for i in range(cols)]

    def __setitem__(self,args,value):
        """Wrap setitem, complain if out of bounds"""
        row,col = args
        in_self_rows, in_self_cols = self.shape

        if row >= in_self_rows or row < 0:
            raise KeyError, "The specified row is out of bounds"
        if col >= in_self_cols or col < 0:
            raise KeyError, "The specified col is out of bounds"

        if value == 0:
            if args in self:
                self._update_internal_indices(args, value)
                del self[args]
            else:
                return
        else:
            self._update_internal_indices(args, value)
            super(SparseDict, self).__setitem__(args, value)

    def __getitem__(self,args):
        """Wrap getitem to handle slices"""
        try:
            row,col = args
        except TypeError:
            raise IndexError, "Must specify (row, col)"

        if isinstance(row, slice): 
            if row.start is None and row.stop is None:
                return self.getCol(col)
            else:
                raise AttributeError, "Can only handle full : slices per axis"
        elif isinstance(col, slice):
            if col.start is None and col.stop is None:
                return self.getRow(row)
            else:
                raise AttributeError, "Can only handle full : slices per axis"
        else:
            # boundary check
            self_rows, self_cols = self.shape
            if row >= self_rows or row < 0:
                raise IndexError, "Row index out of range"
            if col >= self_cols or col < 0:
                raise IndexError, "Col index out of range"

            # return dtype(0) if args don't exist
            if args not in self:
                return self.dtype(0)
            
            return super(SparseDict, self).__getitem__(args)

    def _update_internal_indices(self, args, value):
        """Update internal row,col indices"""
        row,col = args
        if value == 0:
            if args in self:
                self._index_rows[row].remove(args)
                self._index_cols[col].remove(args)
            else:
                return # short circuit, no point in setting 0
        else:
            self._index_rows[row].add(args)
            self._index_cols[col].add(args)

    #def _update_internal_indices_bulk_nonzero(self, row_update, col_update):
    #    """Update internal indices in bulk, assumes all is sane
    #    
    #    row_update : a dict of lists where the nested list contains all row
    #        col pairs that are on the same row
    #        {row_x:[(row_x, col), ...]}
    #    
    #    col_update : a list of lists where the nested list contains all row
    #        col pairs that are on the same col
    #        {col_x:[(row, col_x), ...]} 
    #    """
    #    for row, updates in row_update.items():
    #        self._index_rows[row].update(updates)
    #    for col, updates in col_update.items():
    #        self._index_cols[col].update(updates)

    def getRow(self, row):
        """Returns a row: {((row,col):value}"""
        in_self_rows, in_self_cols = self.shape
        if row >= in_self_rows or row < 0:
            raise IndexError, "The specified row is out of bounds"
    
        new_row = SparseDict(1, in_self_cols)
        
        d = {}
        for r,c in self._index_rows[row]:
            d[(0,c)] = super(SparseDict, self).__getitem__((r,c))
        new_row.update(d)
        return new_row

    def getCol(self, col):
        """Return a col: {((row,col):value}"""
        in_self_rows, in_self_cols = self.shape
        if col >= in_self_cols or col < 0:
            raise IndexError, "The specified col is out of bounds"

        new_col = SparseDict(in_self_rows, 1)

        d = {}
        for r,c in self._index_cols[col]:
            d[(r,0)] = super(SparseDict, self).__getitem__((r,c))
        new_col.update(d)
        return new_col

    def transpose(self):
        """Transpose self"""
        new_self = self.__class__(*self.shape[::-1])
        new_self.update(dict([((c,r),v) for (r,c),v in self.iteritems()]))
        return new_self
    T = property(transpose)

    def update(self, update_dict):
        """Update self"""
        # update does not appear to call self.__setitem__. This is good.
        in_self_rows, in_self_cols = self.shape
    
        # handle zero values different and dont pass them to update
        scrubbed = {}
        #row_updates = {}
        #col_updates = {}
        for (row,col),value in update_dict.items():
            if row >= in_self_rows or row < 0:
                raise KeyError, "The specified row is out of bounds"
            if col >= in_self_cols or col < 0:
                raise KeyError, "The specified col is out of bounds"
            if value == 0:
                self.__setitem__((row,col), 0)
            else:
                scrubbed[(row,col)] = value
               
                # requirements for bulk_nonzero update. might be a smarter way
                # to do it...
                #if row not in row_updates:
                #    row_updates[row] = []
                #if col not in col_updates:
                #    col_updates[col] = []
                #row_updates[row].append((row,col))
                #col_updates[col].append((row,col))

            self._update_internal_indices((row,col), value)
        # possible alternative update method. still not as fast
        #self._update_internal_indices_bulk_nonzero(row_updates,col_updates)

        super(SparseDict, self).update(scrubbed)

def to_sparsedict(values, transpose=False, dtype=float):
    """Tries to returns a populated SparseDict object
    
    NOTE: assumes the max value observed in row and col defines the size of the
    matrix
    """
    # if it is a vector
    if isinstance(values, ndarray) and len(values.shape) == 1:
        if transpose:
            mat = nparray_to_sparsedict(values[:,newaxis], dtype)
        else:
            mat = nparray_to_sparsedict(values, dtype)
        return mat
    # the empty list
    elif isinstance(values, list) and len(values) == 0:
        mat = SparseDict(0,0)
        return mat
    # list of dicts, each representing a row in row order
    elif isinstance(values, list) and isinstance(values[0], dict):
        mat = list_dict_to_sparsedict(values, dtype)
        if transpose:
            mat = mat.T
        return mat
    elif isinstance(values, dict):
        mat = dict_to_sparsedict(values, dtype)
        if transpose:
            mat = mat.T
        return mat
    else:
        raise TableException, "Unknown input type"

def prefer_self(x,y):
    """Merge metadata method, return X if X else Y"""
    return x if x is not None else y

def index_list(l):
    """Takes a list and returns {l[idx]:idx}"""
    return dict([(id_,idx) for idx,id_ in enumerate(l)])

class Table(object):
    """ """
    _biom_type = None
    _biom_matrix_type = None

    def __init__(self, Data, SampleIds, ObservationIds, SampleMetadata=None, 
                 ObservationMetadata=None, TableId=None, **kwargs):
        self.TableId = TableId
        self._data = Data
        self._dtype = Data.dtype

        ### DO WE WANT IMMUTABLE TYPES? or some programitic lie to that effect?
        self.SampleIds = SampleIds
        self.ObservationIds = ObservationIds
        self.SampleMetadata = SampleMetadata
        self.ObservationMetadata = ObservationMetadata
        
        # these will be set by _index_ids()
        self._sample_index = None
        self._obs_index = None
        self._verify_metadata()
        self._cast_metadata()
        self._index_ids()

    def _index_ids(self):
        """Sets lookups {id:index in _data}"""
        self._sample_index = index_list(self.SampleIds)
        self._obs_index = index_list(self.ObservationIds)

    def _conv_to_self_type(self, vals, transpose=False):
        """For converting vectors to a compatible self type"""
        raise NotImplementedError

    def _verify_metadata(self):
        """Obtain some notion of sanity on object construction with inputs"""
        try:
            n_obs, n_samp = self._data.shape
        except:
            n_obs = n_samp = 0

        if n_obs != len(self.ObservationIds):
            raise TableException, \
                    "Number of ObservationIds differs from matrix size!"

        if n_obs != len(set(self.ObservationIds)):
            raise TableException, "Duplicate ObservationIds"

        if n_samp != len(self.SampleIds):
            raise TableException, "Number of SampleIds differs from matrix size!"
        if n_samp != len(set(self.SampleIds)):
            raise TableException, "Duplicate SampleIds"

        if self.SampleMetadata is not None and \
           n_samp != len(self.SampleMetadata):
            raise TableException, "SampleMetadata not in a compatible shape \
                                   with data matrix!"

        if self.ObservationMetadata is not None and \
           n_obs != len(self.ObservationMetadata):
            raise TableException, "ObservationMetadata not in a compatible \
                                   shape with data matrix!"

    def _cast_metadata(self):
        """Casts all metadata to defaultdict to support default values"""
        default_samp_md = []
        default_obs_md = []
   
        # if we have a list of [None], set to None
        if self.SampleMetadata is not None:
            if self.SampleMetadata.count(None) == len(self.SampleMetadata):
                self.SampleMetadata = None

        if self.SampleMetadata is not None:
            for samp_md in self.SampleMetadata:
                d = defaultdict(lambda: None)
    
                if isinstance(samp_md, dict):
                    d.update(samp_md)
                elif samp_md is None:
                    pass
                else:
                    raise TableException, "Unable to cast metadata: %s" % \
                            repr(samp_md)

                default_samp_md.append(d)
            self.SampleMetadata = default_samp_md

        # if we have a list of [None], set to None
        if self.ObservationMetadata is not None:
            none_count = self.ObservationMetadata.count(None)
            if none_count == len(self.ObservationMetadata):
                self.ObservationMetadata = None
        
        if self.ObservationMetadata is not None:
            for obs_md in self.ObservationMetadata:
                d = defaultdict(lambda: None)

                if isinstance(obs_md, dict):
                    d.update(obs_md)
                elif obs_md is None:
                    pass
                else:
                    raise TableException, "Unable to cast metadata: %s" % \
                            repr(obs_md)

                default_obs_md.append(d)
            self.ObservationMetadata = default_obs_md

    def __getitem__(self, args):
        """Passes through to internal matrix"""
        return self._data[args]

    def __setitem__(self, args, value):
        """Passes through to internal matrix"""
        self._data[args] = value

    def reduce(self, f, axis):
        """Reduce over axis with f

        axis can be either 'sample' or 'observation'
        """
        if self.isEmpty():
            raise TableException, "Cannot reduce an empty table"

        # np.apply_along_axis might reduce type conversions here and improve
        # speed. am opting for reduce right now as I think its more readable
        if axis == 'sample':
            return asarray([reduce(f,v) for v in self.iterSampleData()])
        elif axis == 'observation':
            return asarray([reduce(f,v) for v in self.iterObservationData()])
        else:
            raise TableException, "Unknown reduction axis"

    def sum(self, axis='whole'):
        """Returns the sum by axis
        
        axis can be:

        'whole'       : whole matrix sum
        'sample'      : return a vector with a sum for each sample
        'observation' : return a vector with a sum for each observation
        """
        if axis == 'whole':
            return sum(self.reduce(add, 'sample'))
        elif axis == 'sample':
            return self.reduce(add, 'sample')
        elif axis == 'observation':
            return self.reduce(add, 'observation')
        else:
            raise TableException, "Unknown axis %s" % axis
    
    def addObservationMetadata(self, md):
        """Take a dict of metadata and add it

        {observation_id:{dict_of_metadata}}
        """
        if self.ObservationMetadata != None:
            for id_, md_entry in md.items():
                self.ObservationMetadata[self.getObservationIndex(id_)].update(md_entry)
        else:
            self.ObservationMetadata = [md[id_] for id_ in self.ObservationIds]
    
    def addSampleMetadata(self, md):
        """Take a dict of metadata and add it
    
        {sample_id:{dict_of_metadata}}
        """
        if self.SampleMetadata != None:
            for id_, md_entry in md.items():
                self.SampleMetadata[self.getSampleIndex(id_)].update(md_entry)
        else:
            self.SampleMetadata = [md[id_] for id_ in self.SampleIds]

    def getSampleIndex(self, samp_id):
        """Returns the sample index"""
        if samp_id not in self._sample_index:
            raise UnknownID, "SampleId %s not found!" % samp_id
        return self._sample_index[samp_id]

    def getObservationIndex(self, obs_id):
        """Returns the obs index"""
        if obs_id not in self._obs_index:
            raise UnknownID, "ObservationId %s not found!" % obs_id
        return self._obs_index[obs_id]

    def getValueByIds(self, obs_id, samp_id):
        """Return the value in the matrix corresponding to (obs_id, samp_id)"""
        if obs_id not in self._obs_index:
            raise UnknownID, "ObservationId %s not found!" % obs_id
        if samp_id not in self._sample_index:
            raise UnknownID, "SampleId %s not found!" % samp_id

        return self._data[self._obs_index[obs_id], self._sample_index[samp_id]]

    def setValueByIds(self, obs_id, samp_id, val):
        """Set the value in the matrix corresponding to (obs_id, samp_id)"""
        if obs_id not in self._obs_index:
            raise UnknownID, "ObservationId %s not found!" % obs_id
        if samp_id not in self._sample_index:
            raise UnknownID, "SampleId %s not found!" % samp_id

        self._data[self._obs_index[obs_id], self._sample_index[samp_id]] = val

    def __str__(self):
        """Stringify self

        Default str output for a Table is just row/col ids and data values
        """
        return self.delimitedSelf()

    def sampleExists(self, id_):
        """Returns True if sample exists, False otherwise"""
        return id_ in self._sample_index

    def observationExists(self, id_):
        """Returns True if observation exists, False otherwise"""
        return id_ in self._obs_index

    def delimitedSelf(self, delim='\t', header_key=None, header_value=None, 
        metadata_formatter=str):
        """Stringify self in a delimited form
        
        Default str output for the Table is just row/col ids and table data
        without any metadata

        If header_key is not None, try to pull out that key from observation
        metadata. If header_value is not None, use the header_value in the
        output.
        
        metadata_formatter: a function which takes a metadata entry and 
         returns a formatted version that should be written to file
        """
        if self.isEmpty():
            raise TableException, "Cannot delimit self if I don't have data..."

        samp_ids = delim.join(map(str, self.SampleIds))

        # 17hrs of programing straight later...
        if header_key is not None:
            if header_value is None:
                raise TableException, "You need to specify both header_key and header_value"
        if header_value is not None:
            if header_key is None:
                raise TableException, "You need to specify both header_key and header_value"

        if header_value:
            output = ['# Constructed from biom file','#OTU ID%s%s\t%s' % (delim, 
                samp_ids,header_value)]
        else:
            output = ['# Constructed from biom file','#OTU ID%s%s' % (delim, 
                samp_ids)]

        for obs_id, obs_values in zip(self.ObservationIds, self._iter_obs()):
            str_obs_vals = delim.join(map(str, self._conv_to_np(obs_values)))

            if header_key and self.ObservationMetadata is not None:
                md = self.ObservationMetadata[self._obs_index[obs_id]]
                md_out = metadata_formatter(md.get(header_key,None))
                output.append('%s%s%s\t%s' % (obs_id, delim, str_obs_vals, md_out))
            else:
                output.append('%s%s%s' % (obs_id, delim, str_obs_vals))

        return '\n'.join(output)

    def isEmpty(self):
        """Returns true if the table is empty"""
        if not self.SampleIds or not self.ObservationIds:
            return True
        else:
            return False

    def __iter__(self):
        """Defined by subclass"""
        raise NotImplementedError

    def _iter_obs(self):
        """Defined by subclass"""
        raise NotImplementedError

    def _iter_samp(self):
        """Defined by subclass"""
        raise NotImplementedError

    def __eq__(self, other):
        """Equality is determined by the data matrix not metadata or IDs"""
        if self.ObservationIds != other.ObservationIds:
            return False
        if self.SampleIds != other.SampleIds:
            return False
        if self.ObservationMetadata != other.ObservationMetadata:
            return False
        if self.SampleMetadata != other.SampleMetadata:
            return False
        if not self._data_equality(other):
            return False

        return True

    def _data_equality(self,other):
        """Private method to determine equality of data"""
        raise NotImplementedError

    def __ne__(self,other):
        return not (self == other)

    def _conv_to_np(self, v):
        """Convert values of v to numpy arrays"""
        raise NotImplementedError

    # _index objs are in place, can now do sampleData(self, sample_id) and observationData(self, obs_id)
    def sampleData(self, id_, conv_to_np=False):
        """Return observations associated to a sample id"""
        if id_ not in self._sample_index:
            raise UnknownID, "ID %s is not a known sample ID!" % id_
        return self._conv_to_np(self._data[:,self._sample_index[id_]])

    def observationData(self, id_):
        """Return samples associated to a observation id"""
        if id_ not in self._obs_index:
            raise UnknownID, "ID %s is not a known observation ID!" % id_
        return self._conv_to_np(self._data[self._obs_index[id_],:])

    def copy(self):
        """Returns a copy of the Table"""
        #### NEEDS TO BE A DEEP COPY, MIGHT NOT GET METADATA! NEED TEST!
        return self.__class__(self._data.copy(), self.SampleIds[:], 
                self.ObservationIds[:], self.SampleMetadata, 
                self.ObservationMetadata, self.TableId)

    def iterSampleData(self):
        """Yields sample_values"""
        for samp_v in self._iter_samp():
            yield self._conv_to_np(samp_v)

    def iterObservationData(self):
        """Yields observation_values"""
        for obs_v in self._iter_obs():
            yield self._conv_to_np(obs_v)

    def iterSamples(self, conv_to_np=True):
        """Yields (sample_values, sample_id, sample_metadata)

        NOTE: will return None in sample_metadata positions if 
        self.SampleMetadata is set to None
        """
        if self.SampleMetadata is None:
            samp_metadata = [None] * len(self.SampleIds)
        else:
            samp_metadata = self.SampleMetadata

        iterator = izip(self._iter_samp(), self.SampleIds, samp_metadata)
        for samp_v, samp_id, samp_md in iterator:
            if conv_to_np:
                yield (self._conv_to_np(samp_v), samp_id, samp_md)
            else:
                yield (samp_v, samp_id, samp_md)

    def iterObservations(self, conv_to_np=True):
        """Yields (observation_value, observation_id, observation_metadata)

        NOTE: will return None in observation_metadata positions if 
        self.ObservationMetadata is set to None
        """
        if self.ObservationMetadata is None:
            obs_metadata = [None] * len(self.ObservationIds)
        else:
            obs_metadata = self.ObservationMetadata
        
        iterator = izip(self._iter_obs(), self.ObservationIds, obs_metadata)
        for obs_v, obs_id, obs_md in iterator:
            if conv_to_np:
                yield (self._conv_to_np(obs_v), obs_id, obs_md)
            else:
                yield (obs_v, obs_id, obs_md)

    def sortSampleOrder(self, sample_order):
        """Return a new table in sample order"""
        samp_md = []
        vals = []

        for id_ in sample_order:
            cur_idx = self._sample_index[id_]
            vals.append(self[:,cur_idx])
            
            if self.SampleMetadata is not None:
                samp_md.append(self.SampleMetadata[cur_idx])

        if not samp_md:
            samp_md = None

        return self.__class__(self._conv_to_self_type(vals), 
                sample_order[:], self.ObservationIds[:], samp_md, 
                self.ObservationMetadata, self.TableId)

    def sortObservationOrder(self, obs_order):
        """Return a new table in observation order"""
        obs_md = []
        vals = []

        for id_ in obs_order:
            cur_idx = self._obs_index[id_]
            vals.append(self[cur_idx,:])

            if self.ObservationMetadata is not None:
                obs_md.append(self.ObservationMetadata[cur_idx])

        if not obs_md:
            obs_md = None

        return self.__class__(self._conv_to_self_type(vals),
                self.SampleIds[:], obs_order[:], self.SampleMetadata,
                obs_md, self.TableId)

    def sortBySampleId(self, sort_f=natsort):
        """Return a table sorted by sort_f"""
        return self.sortSampleOrder(sort_f(self.SampleIds))

    def sortByObservationId(self, sort_f=natsort):
        """Return a table sorted by sort_f"""
        return self.sortObservationOrder(sort_f(self.ObservationIds))

    # a good refactor in the future is a general filter() method and then
    # specify the axis, like Table.reduce

    # take() is tempting here as well...
    def filterSamples(self, f, invert=False):
        """Filter samples in self based on f
        
        f must accept three variables, the sample values, sample IDs and sample 
        metadata. The function must only return true or false.
        """
        samp_ids = []
        samp_vals = []
        samp_metadata = []

        # builtin filter puts all of this into memory and then return to the for
        # loop. This will impact memory substantially on large sparse matrices
        for s_val, s_id, s_md in self.iterSamples():
            if not xor(f(s_val, s_id, s_md), invert):
                continue

            # there is an implicit converstion to numpy types, want to make 
            # sure to convert back to underlying representation.
            samp_vals.append(self._conv_to_self_type(s_val))
            samp_metadata.append(s_md)
            samp_ids.append(s_id)
    
        # if we don't have any values to keep, throw an exception as we can 
        # create an inconsistancy in which there are observation ids but no
        # matrix data in the resulting table
        if not samp_vals:
            raise TableException, "All samples filtered out!"

        # the additional call to _conv_to_self_type is to convert a list of 
        # vectors to a matrix
        # transpose is necessary as the underlying storage is sample == col
        return self.__class__(self._conv_to_self_type(samp_vals,transpose=True),
                samp_ids[:], self.ObservationIds[:], samp_metadata, 
                self.ObservationMetadata, self.TableId)

    def filterObservations(self, f, invert=False):
        """Filter observations in self based on f
        
        f must accept three variables, the observation values, observation ids
        and observation metadata. The function must only return true or false.
        """
        obs_ids = []
        obs_vals = []
        obs_metadata = []

        # builtin filter puts all of this into memory and then return to the for
        # loop. This will impact memory substantially on large sparse matrices
        for o_val, o_id, o_md in self.iterObservations():
            if not xor(f(o_val, o_id, o_md), invert):
                continue

            # there is an implicit converstion to numpy types, want to make 
            # sure to convert back to underlying representation.
            obs_vals.append(self._conv_to_self_type(o_val))
            obs_metadata.append(o_md)
            obs_ids.append(o_id)

        # if we don't have any values to keep, throw an exception as we can 
        # create an inconsistancy in which there are sample ids but no
        # matrix data in the resulting table
        if not obs_vals:
            raise TableException, "All obs filtered out!"

        return self.__class__(self._conv_to_self_type(obs_vals),self.SampleIds[:],
                obs_ids[:], self.SampleMetadata, obs_metadata, self.TableId)

    def binSamplesByMetadata(self, f):
        """Yields tables by metadata
        
        f is given the sample metadata by row and must return what "bin" the
        sample is part of.
        """
        bins = {}
        # conversion of vector types is not necessary, vectors are not
        # being passed to an arbitrary function
        for samp_v, samp_id, samp_md in self.iterSamples(conv_to_np=False):
            bin = f(samp_md)

            # try to make it hashable...
            if not isinstance(bin, Hashable):
                bin = tuple(bin)

            if bin not in bins:
                bins[bin] = [[], [], []]

            bins[bin][0].append(samp_id)
            bins[bin][1].append(samp_v)
            bins[bin][2].append(samp_md)

        for bin, (samp_ids, samp_values, samp_md) in bins.iteritems():
            data = self._conv_to_self_type(samp_values, transpose=True)
            yield bin, self.__class__(data, samp_ids[:], self.ObservationIds[:], 
                    samp_md, self.ObservationMetadata, self.TableId)

    def binObservationsByMetadata(self, f):
        """Yields tables by metadata
        
        f is given the sample metadata by row and must return what "bin" the
        sample is part of.
        """
        bins = {}
        # conversion of vector types is not necessary, vectors are not
        # being passed to an arbitrary function
        for obs_v, obs_id, obs_md in self.iterObservations(conv_to_np=False):
            bin = f(obs_md)

            # try to make it hashable...
            if not isinstance(bin, Hashable):
                bin = tuple(bin)

            if bin not in bins:
                bins[bin] = [[], [], []]

            bins[bin][0].append(obs_id)
            bins[bin][1].append(obs_v)
            bins[bin][2].append(obs_md)

        for bin, (obs_ids, obs_values, obs_md) in bins.iteritems():
            yield bin, self.__class__(self._conv_to_self_type(obs_values), 
                    self.SampleIds[:], obs_ids[:], self.SampleMetadata,
                    obs_md, self.TableId)

    # it might be desirable in the future to rewrite the transform methods
    # to a general purpose map() and then specify an axis within map
    def transformSamples(self, f):
        """Apply a function to each sample
        
        f is passed a numpy vector and must return a vector
        """
        new_samp_v = []
        for samp_v, samp_id, samp_md in self.iterSamples():
            new_samp_v.append(self._conv_to_self_type(f(samp_v, samp_id, samp_md)))

        return self.__class__(self._conv_to_self_type(new_samp_v, transpose=True), 
                self.SampleIds[:], self.ObservationIds[:], self.SampleMetadata,
                self.ObservationMetadata, self.TableId)

    def transformObservations(self, f):
        """Apply a function to each observation

        f is passed a numpy vector and must return a vector
        """
        new_obs_v = []
        for obs_v, obs_id, obs_md in self.iterObservations():
            new_obs_v.append(self._conv_to_self_type(f(obs_v, obs_id, obs_md)))

        return self.__class__(self._conv_to_self_type(new_obs_v),
                self.SampleIds[:],self.ObservationIds[:],self.SampleMetadata,
                self.ObservationMetadata, self.TableId)

    def normObservationBySample(self):
        """Return new table with relative abundance in each sample"""
        def f(samp_v, samp_id, samp_md):
            return samp_v / float(samp_v.sum())
        return self.transformSamples(f)

    def normSampleByObservation(self):
        """Return new table with relative abundance in each observation"""        
        def f(obs_v,obs_id,obs_md):
            return obs_v / float(obs_v.sum())
        #f = lambda x: x / float(x.sum())
        return self.transformObservations(f)
    
    def normObservationByMetadata(self,obs_metadata_id):
        """Return new table with counts divided by specified metadata value"""        
        def f(obs_v,obs_id,obs_md):
            return obs_v / obs_md[obs_metadata_id]
        return self.transformObservations(f)

    def nonzero(self):
        """Returns types of nonzero locations within the data matrix

        The values returned are (observation_id, sample_id)
        """
        # this is naively implemented. If performance is a concern, private
        # methods can be written to hit against the underlying types directly
        for o_idx, samp_vals in enumerate(self.iterObservationData()):
            for s_idx in samp_vals.nonzero()[0]:
                yield (self.ObservationIds[o_idx], self.SampleIds[s_idx])

    def _union_id_order(self, a, b):
        """Determines merge order for id lists A and B"""
        all_ids = a[:]
        all_ids.extend(b[:])
        new_order = {}
        idx = 0
        for id_ in all_ids:
            if id_ not in new_order:
                new_order[id_] = idx
                idx += 1
        return new_order
    
    def _intersect_id_order(self, a, b):
        """Determines the merge order for id lists A and B"""
        all_b = set(b[:])
        new_order = {}
        idx = 0
        for id_ in a:
            if id_ in all_b:
                new_order[id_] = idx
                idx += 1
        return new_order

    def merge(self, other, Sample='union', Observation='union', merge_f=add,
            sample_metadata_f=prefer_self, observation_metadata_f=prefer_self):
        """Merge two tables together

        The axes, samples and observations, can be controlled independently. 
        Both can either work on 'union' or 'intersection'. 

        merge_f is a function that takes two arguments and returns a value. 
        The method is parameterized so that values can be added or subtracted
        where there is overlap in (sample_id, observation_id) values in the 
        tables

        sample_metadata_f and observation_metadata_f define how to merge
        metadata between tables. The default is to just keep the metadata
        associated to self if self has metadata otherwise take metadata from
        other. These functions are given both metadata dictsand must return 
        a single metadata dict

        NOTE: There is an implicit type conversion to float. Tables using
        strings as the type are not supported. No check is currently in
        place.

        NOTE: The return type is always that of self
        """
        # determine the sample order in the resulting table
        if Sample is 'union':
            new_samp_order = self._union_id_order(self.SampleIds, 
                                                  other.SampleIds) 
        elif Sample is 'intersection':
            new_samp_order = self._intersect_id_order(self.SampleIds,
                                                      other.SampleIds)
        else:
            raise TableException, "Unknown Sample merge type: %s" % Sample
         
        # determine the observation order in the resulting table
        if Observation is 'union':
            new_obs_order = self._union_id_order(self.ObservationIds, 
                                                  other.ObservationIds) 
        elif Observation is 'intersection':
            new_obs_order = self._intersect_id_order(self.ObservationIds,
                                                      other.ObservationIds)
        else:
            raise TableException, "Unknown observation merge type: %s" % Observation
       
        # if we don't have any samples, complain loudly. This is likely from 
        # performing an intersection without overlapping ids
        if not new_samp_order:
            raise TableException, "No samples in resulting table!"
        if not new_obs_order:
            raise TableException, "No observations in resulting table!"

        # helper index lookups
        other_obs_idx = other._obs_index
        self_obs_idx = self._obs_index
        other_samp_idx = other._sample_index
        self_samp_idx = self._sample_index

        # pre-allocate the a list for placing the resulting vectors as the 
        # placement id is not ordered
        vals = [None for i in range(len(new_obs_order))] 
       
        ### POSSIBLE DECOMPOSITION
        # resulting sample ids and sample metadata
        sample_ids = []
        sample_md = []
        for id_,idx in sorted(new_samp_order.items(), key=itemgetter(1)):
            sample_ids.append(id_)

            # if we have sample metadata, grab it
            if self.SampleMetadata is None or not self.sampleExists(id_):
                self_md = None
            else:
                self_md = self.SampleMetadata[self_samp_idx[id_]]
            
            # if we have sample metadata, grab it
            if other.SampleMetadata is None or not other.sampleExists(id_):
                other_md = None
            else:
                other_md = other.SampleMetadata[other_samp_idx[id_]]

            sample_md.append(sample_metadata_f(self_md, other_md))

        ### POSSIBLE DECOMPOSITION
        # resulting observation ids and sample metadata
        obs_ids = []
        obs_md = []
        for id_,idx in sorted(new_obs_order.items(), key=itemgetter(1)):
            obs_ids.append(id_)

            # if we have observation metadata, grab it
            if self.ObservationMetadata is None or \
               not self.observationExists(id_):
                self_md = None
            else:
                self_md = self.ObservationMetadata[self_obs_idx[id_]]

            # if we have observation metadata, grab it
            if other.ObservationMetadata is None or \
                not other.observationExists(id_):
                other_md = None
            else:
                other_md = other.ObservationMetadata[other_obs_idx[id_]]

            obs_md.append(observation_metadata_f(self_md, other_md))

        # length used for construction of new vectors
        vec_length = len(new_samp_order)

        # walk over observations in our new order
        for obs_id, new_obs_idx in new_obs_order.iteritems():
            # create new vector for matrix values
            new_vec = zeros(vec_length, dtype='float')

            # see if the observation exists in other, if so, pull it out.
            # if not, set to the placeholder missing
            if other.observationExists(obs_id):
                other_vec = other.observationData(obs_id)
            else:
                other_vec = None

            # see if the observation exists in self, if so, pull it out.
            # if not, set to the placeholder missing
            if self.observationExists(obs_id):
                self_vec = self.observationData(obs_id)
            else:
                self_vec = None

            ### do we want a sanity check to make sure that self_vec AND 
            ### other_vec are not 'missing'??

            # walk over samples in our new order
            for samp_id, new_samp_idx in new_samp_order.iteritems():
                # pull out each individual sample value. This is expensive, but
                # the vectors are in a different alignment. It is possible that
                # this could be improved with numpy take but needs to handle
                # missing values appropriately
                if self_vec is None or samp_id not in self_samp_idx:
                    self_vec_value = 0
                else:
                    self_vec_value = self_vec[self_samp_idx[samp_id]]

                if other_vec is None or samp_id not in other_samp_idx:
                    other_vec_value = 0
                else: 
                    other_vec_value = other_vec[other_samp_idx[samp_id]]

                # pass both values to our merge_f
                new_vec[new_samp_idx] = merge_f(self_vec_value, 
                                                other_vec_value)

            # convert our new vector to self type as to make sure we don't
            # accidently force a dense representation in memory
            vals[new_obs_idx] = self._conv_to_self_type(new_vec)

        return self.__class__(self._conv_to_self_type(vals), sample_ids[:], 
                obs_ids[:], sample_md, obs_md)

    def getBiomFormatObject(self, generated_by):
        """Returns a dictionary representing the table in Biom format.

        This dictionary can then be easily converted into a JSON string for
        serialization.

        generated_by - a string describing the software used to build the table

        TODO: This method may be very inefficient in terms of memory usage, so
        it needs to be tested with several large tables to determine if
        optimizations are necessary or not (i.e. subclassing JSONEncoder, using
        generators, etc...).
        """
        if self._biom_type is None:
            raise TableException, "Unknown biom type"

        if (not isinstance(generated_by, str) and
            not isinstance(generated_by, unicode)):
            raise TableException, "Must specify a generated_by string"

        # Fill in top-level metadata.
        biom_format_obj = {}
        biom_format_obj["id"] = self.TableId
        biom_format_obj["format"] = get_biom_format_version_string()
        biom_format_obj["format_url"] =\
                get_biom_format_url_string()
        biom_format_obj["generated_by"] = generated_by
        biom_format_obj["date"] = "%s" % datetime.now().isoformat()

        # Determine if we have any data in the matrix, and what the shape of
        # the matrix is.
        try:
            num_rows, num_cols = self._data.shape
        except:
            num_rows = num_cols = 0
        hasData = True if num_rows > 0 and num_cols > 0 else False

        # Default the matrix element type to test to be an integer in case we
        # don't have any data in the matrix to test.
        test_element = 0
        if hasData:
            test_element = self[0,0]

        # Determine the type of elements the matrix is storing.
        if isinstance(test_element, int):
            dtype, matrix_element_type = int, "int"
        elif isinstance(test_element, float):
            dtype, matrix_element_type = float, "float"
        elif isinstance(test_element, str):
            dtype, matrix_element_type = str, "str"
        else:
            raise TableException("Unsupported matrix data type.")

        # Fill in details about the matrix.
        biom_format_obj["type"] = self._biom_type
        biom_format_obj["matrix_type"] = self._biom_matrix_type
        biom_format_obj["matrix_element_type"] = "%s" % matrix_element_type
        biom_format_obj["shape"] = [num_rows, num_cols]

        # Fill in details about the rows in the table and fill in the matrix's
        # data.
        biom_format_obj["rows"] = []
        biom_format_obj["data"] = []
        for obs_index, obs in enumerate(self.iterObservations()):
            biom_format_obj["rows"].append(
                    {"id" : "%s" % obs[1], "metadata" : obs[2]})
            # If the matrix is dense, simply convert the numpy array to a list
            # of data values. If the matrix is sparse, we need to store the
            # data in sparse format, as it is given to us in a numpy array in
            # dense format (i.e. includes zeroes) by iterObservations().
            if self._biom_matrix_type == "dense":
                # convert to python types, JSON doesn't like numpy types
                biom_format_obj["data"].append(map(dtype,obs[0]))
            elif self._biom_matrix_type == "sparse":
                dense_values = list(obs[0])
                sparse_values = []
                for col_index, val in enumerate(dense_values):
                    if float(val) != 0.0:
                        sparse_values.append([obs_index, col_index, val])
                biom_format_obj["data"].extend(sparse_values)

        # Fill in details about the columns in the table.
        biom_format_obj["columns"] = []
        for samp in self.iterSamples():
            biom_format_obj["columns"].append(
                    {"id" : "%s" % samp[1], "metadata" : samp[2]})
        return biom_format_obj

    def getBiomFormatJsonString(self,generated_by):
        """Returns a JSON string representing the table in Biom format."""
        return dumps(self.getBiomFormatObject(generated_by))

    def getBiomFormatPrettyPrint(self):
        """Returns a 'pretty print' format of a biom file

        WARNING: This method displays data values in a columnar format and 
        can be misleading.
        """
        return dumps(self.getBiomFormatObject(), sort_keys=True, indent=4)

class SparseTable(Table):
    _biom_matrix_type = "sparse"
    def __init__(self, *args, **kwargs):
        super(SparseTable, self).__init__(*args, **kwargs)
   
    def _data_equality(self, other):
        """Two SparseDict matrices are equal if the items are equal"""
        if isinstance(self, other.__class__):
            return sorted(self._data.items()) == sorted(other._data.items())
        
        for s_v, o_v in izip(self.iterSampleData(),other.iterSampleData()):
            if not (s_v == o_v).all():
                return False
    
        return True

    def _conv_to_np(self, v):
        """Converts a vector to a numpy array

        Always returns a row vector for consistancy with numpy iteration over
        arrays
        """
        vals = v.items()

        num_rows, num_cols = v.shape

        if num_rows > num_cols:
            new_v = zeros(num_rows, dtype=self._dtype)
            for (row,col),val in vals:
                new_v[row] = val
        else:
            new_v = zeros(num_cols, dtype=self._dtype)
            for (row,col),val in vals:
                new_v[col] = val
        return new_v

    def _conv_to_self_type(self, vals, transpose=False):
        """For converting vectors to a compatible self type"""
        return to_sparsedict(vals, transpose, self._dtype)

    def __iter__(self):
        """Defined by subclass"""
        return self.iterSamples()

    ### this method is type conversion heavy... but only fix if a burden when
    ### in use
    def _iter_samp(self):
        """Return sample vectors of data matrix vectors"""  
        rows, cols = self._data.shape
        for c in range(cols):
            # this pulls out col vectors but need to convert to the expected row
            # vector
            colvec = self._data.getCol(c)
            yield colvec.T

    def _iter_obs(self):
        """Return observation vectors of data matrix"""
        for r in range(self._data.shape[0]):
            #yield self._data[r,:]
            yield self._data.getRow(r)

class DenseTable(Table):
    _biom_matrix_type = "dense"
    def __init__(self, *args, **kwargs):
        super(DenseTable, self).__init__(*args, **kwargs)

    def _data_equality(self, other):
        """Checks if the data matrices are equal"""
        if isinstance(self, other.__class__):
            return (self._data == other._data).all()
        
        for s_v, o_v in izip(self.iterSampleData(),other.iterSampleData()):
            if not (s_v == o_v).all():
                return False
    
        return True

    def _conv_to_np(self, v):
        """Converts a vector to a numpy array"""
        return asarray(v)

    def _conv_to_self_type(self, vals, transpose=False):
        """For converting vectors to a compatible self type"""
        # expects row vector here...
        if transpose:
            return asarray(vals).T
        else:
            return asarray(vals)

    def __iter__(self):
        """Defined by subclass"""
        return self.iterSamples()

    def _iter_obs(self):
        """Return observations of data matrix"""
        for r in self._data:
            yield r

    def _iter_samp(self):
        """Return samples of data matrix in row vectors"""  
        for c in self._data.T:
            yield c

class OTUTable(object):
    _biom_type = "OTU table"
    pass

class AbundanceTable(object):
    _biom_type = "Abundance table"
    pass

class DenseOTUTable(OTUTable, DenseTable):
    pass

class SparseOTUTable(OTUTable, SparseTable):
    pass

class DenseAbundanceTable(AbundanceTable, DenseTable):
    pass

class SparseAbundanceTable(AbundanceTable, SparseTable):
    pass

def list_list_to_nparray(data, dtype=float):
    """Convert a list of lists into a nparray

    [[value, value, ..., value], ...]
    """
    return asarray(data, dtype=float)

def list_list_to_sparsedict(data, dtype=float):
    """Convert a list of lists into a sparsedict

    [[row, col, value], ...]
    """
    d = dict([((r,c),dtype(v)) for r,c,v in data if v != 0])
    n_rows = 0
    n_cols = 0
    for (r,c) in d:
        if r >= n_rows:
            n_rows = r + 1 # deal with 0-based indexes
        if c >= n_cols:
            n_cols = c + 1

    mat = SparseDict(n_rows, n_cols)
    mat.update(d)
    return mat

def nparray_to_sparsedict(data, dtype=float):
    """Convert a numpy array to a dict"""
    if len(data.shape) == 1:
        mat = SparseDict(1, data.shape[0])
        
        for idx,v in enumerate(data):
            if v != 0:
                mat[(0,idx)] = dtype(v)
    else:
        mat = SparseDict(*data.shape)
        for row_idx, row in enumerate(data):
            for col_idx, value in enumerate(row):
                if value != 0:
                    mat[(row_idx, col_idx)] = dtype(value)
    return mat
    
def list_nparray_to_sparsedict(data, dtype=float):
    """Takes a list of numpy arrays and creates a dict"""
    mat = SparseDict(len(data), len(data[0]))
    for row_idx, row in enumerate(data):
        if len(row.shape) != 1:
            raise TableException, "Cannot convert non-1d vectors!"
        if len(row) != mat.shape[1]:
            raise TableException, "Row vector isn't the correct length!"

        for col_idx, val in enumerate(row):
            mat[row_idx, col_idx] = dtype(val)
    return mat

def list_dict_to_sparsedict(data, dtype=float):
    """Takes a list of dict {(0,col):val} and creates a full dict"""
    if isinstance(data[0], SparseDict):
        if data[0].shape[0] > data[0].shape[1]:
            is_col = True
            n_cols = len(data)
            n_rows = data[0].shape[0]
        else:
            is_col = False
            n_rows = len(data)
            n_cols = data[0].shape[1]
    else:
        all_keys = flatten([d.keys() for d in data])
        n_rows = max(all_keys, key=itemgetter(0))[0] + 1
        n_cols = max(all_keys, key=itemgetter(1))[1] + 1
        if n_rows > n_cols:
            is_col = True
            n_cols = len(data)
        else:
            is_col = False
            n_rows = len(data)
    
    mat = SparseDict(n_rows, n_cols)
    for row_idx,row in enumerate(data):
        for (foo,col_idx),val in row.items():
            if is_col:
                mat[foo,row_idx] = dtype(val)
            else:
                mat[row_idx,col_idx] = dtype(val)

    return mat

def dict_to_nparray(data, dtype=float):
    """Takes a dict {(row,col):val} and creates a numpy matrix"""
    rows, cols = zip(*data) # unzip
    mat = zeros((max(rows) + 1, max(cols) + 1), dtype=dtype)

    for (row,col),val in data.items():
        mat[row,col] = val

    return mat

def dict_to_sparsedict(data, dtype=float):
    """takes a dict {(row,col):val} and creates a SparseDict"""
    n_rows = max(data.keys(), key=itemgetter(0))[0] + 1
    n_cols = max(data.keys(), key=itemgetter(1))[1] + 1
    mat = SparseDict(n_rows, n_cols)
    mat.update(data)
    return mat

def list_dict_to_nparray(data, dtype=float):
    """Takes a list of dicts {(0,col):val} and creates an numpy matrix

    Expects each dict to represent a row vector
    """
    n_rows = len(data)
    n_cols = max(flatten([d.keys() for d in data]), key=itemgetter(1))[1] + 1

    mat = zeros((n_rows, n_cols), dtype=dtype)
    
    for row_idx, row in enumerate(data):
        for (foo,col_idx),val in row.items():
            mat[row_idx, col_idx] = val

    return mat

def table_factory(data, sample_ids, observation_ids, sample_metadata=None, 
                  observation_metadata=None, table_id=None, 
                  constructor=SparseOTUTable, **kwargs):
    """Construct a table

    Attempts to make 'data' sane with respect to the constructor type through
    various means of juggling. Data can be: 
    
        numpy.array       
        list of numpy.array vectors 
        sparse dict representation 
        list of sparse dict representation vectors
    """
    if 'dtype' in kwargs:
        dtype = kwargs['dtype']
    else:
        dtype = float

    if constructor._biom_matrix_type is 'sparse':
        # if we have a numpy array
        if isinstance(data, ndarray):
            data = nparray_to_sparsedict(data, dtype)

        # if we have a list of numpy vectors
        elif isinstance(data, list) and isinstance(data[0], ndarray):
            data = list_nparray_to_sparsedict(data, dtype)

        # if we have a dict representation
        elif isinstance(data, dict) and not isinstance(data, SparseDict):
            data = dict_to_sparsedict(data, dtype)

        elif isinstance(data, SparseDict):
            pass

        # if we have a list of dicts
        elif isinstance(data, list) and isinstance(data[0], dict):
            data = list_dict_to_sparsedict(data, dtype)

        # if we have a list of lists (like inputs from json biom)
        elif isinstance(data, list) and isinstance(data[0], list):
            data = list_list_to_sparsedict(data, dtype)

        else:
            raise TableException, "Cannot handle data!"
    
    elif constructor._biom_matrix_type is 'dense':
        # if we have a numpy array
        if isinstance(data, ndarray):
            pass

        # if we have a list of numpy vectors
        elif isinstance(data, list) and isinstance(data[0], ndarray):
            data = asarray(data, dtype)

        # if we have a dict representation
        elif isinstance(data, dict):
            data = dict_to_nparray(data, dtype)

        # if we have a list of dicts
        elif isinstance(data, list) and isinstance(data[0], dict):
            data = list_dict_to_nparray(data, dtype)

        # if we have a list of lists (ie input from json biom)
        elif isinstance(data, list) and isinstance(data[0], list):
            data = list_list_to_nparray(data, dtype)

        else:
            raise TableException, "Cannot handle data!"
    else:
        raise TableException, "Constructor type specifies an unknown matrix " +\
                              "type: %s" % constructor._biom_matrix_type

    return constructor(data, sample_ids, observation_ids, 
            SampleMetadata=sample_metadata,
            ObservationMetadata=observation_metadata,
            TableId=table_id, **kwargs)