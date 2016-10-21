# #######
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.
'''
    nfvo_packager.reader
    ~~~~~~~~~~~~~~~~~~~~
    CSAR interface for reading CSAR packages
'''

import logging
import os
from shutil import rmtree
from glob import glob
from tempfile import mkstemp, mkdtemp
import mimetypes
import hashlib
from base64 import b64decode
from pprint import pformat
import zipfile
import yaml
import requests

from nfvo_packager import constants

logging.basicConfig(level=logging.DEBUG)


class CSARReader(object):
    '''
        TOSCA Cloud Service Archive (CSAR) reader. This class
        is a helper for reading, validating, and extracting information
        from CSAR v1.1 ZIP files (locally or remotely).
    '''
    def __init__(self, source, is_external=False, logger=None):
        self.log = logger or logging.getLogger('csar.reader')
        self.log.debug('CSARReader(%s, %s)', source, is_external)
        self.csar = {
            'source': source,
            'external': is_external,
            'local': None,
            'destination': None,
            'metadata': None,
            'artifacts': None
        }
        self._retrieve()
        self._extract()
        self._validate()

    def __del__(self):
        '''
            Deletes temporary files and folders
        '''
        if self.csar.get('local') and \
           self.csar.get('source') and \
           self.csar['local'] != os.path.normpath(self.csar['source']) and \
           os.path.isfile(self.csar['local']):
            self.log.debug('Removing temporary file: %s', self.csar['local'])
            os.remove(self.csar['local'])
        if self.csar.get('destination') and \
           os.path.isdir(self.csar['destination']):
            self.log.debug('Removing temporary directory: %s',
                           self.csar['destination'])
            rmtree(self.csar['destination'])

    @property
    def has_metadata_file(self):
        '''Returns True if a metadata file exists'''
        return os.path.isfile(os.path.join(self.path, constants.META_FILE))

    @property
    def metadata(self):
        '''Returns CSAR metadata'''
        return self.csar.get('metadata', dict())

    @property
    def artifacts(self):
        '''Returns CSAR artifacts'''
        return self.metadata.get('artifacts', dict())

    @property
    def path(self):
        '''Returns the root (extracted) CSAR directory path'''
        return self.csar.get('destination')

    @property
    def author(self):
        '''Returns the CSAR package author'''
        return self.metadata.get(constants.META_CREATED_BY_KEY) or \
            self.metadata.get(constants.META_TMPL_AUTHOR_KEY)

    @property
    def version(self):
        '''Returns the CSAR version'''
        return self.metadata.get(constants.META_CSAR_VERSION_KEY) or \
            self.metadata.get(constants.META_TMPL_VERSION_KEY)

    @property
    def metadata_file_version(self):
        '''Returns the CSAR metadata file version'''
        return self.metadata.get(constants.META_FILE_VERSION_KEY)

    @property
    def template_name(self):
        '''Returns the CSAR template name'''
        return self.metadata.get(constants.META_TMPL_NAME_KEY)

    @property
    def entry_definitions(self):
        '''Returns the Entry-Definitions (relative) path'''
        return self.metadata.get(constants.META_ENTRY_DEFINITIONS_KEY)

    @property
    def entry_definitions_yaml(self):
        '''Returns the TOSCA entry definitions YAML contents'''
        with open(os.path.join(self.path,
                               self.entry_definitions), 'r') as mfile:
            return yaml.load(mfile)
        return dict()

    def _retrieve(self):
        '''
            Fetches a CSAR package (remote or local)
        '''
        if not self.csar['external']:
            self.log.debug('CSAR is local; normalizing path')
            self.csar['local'] = os.path.normpath(self.csar['source'])
            self.log.debug('CSAR local path is: %s', self.csar['local'])
            return
        # Get a temporary file
        self.log.debug('Generating temporary file')
        tmp_hndl, tmp_filename = mkstemp()
        self.log.debug('Temporary file is: %s', tmp_filename)
        # Download the archive
        self.log.debug('Starting remote CSAR download')
        req = requests.get(self.csar['source'], stream=True)
        for chunk in req.iter_content(chunk_size=1024):
            if chunk:
                os.write(tmp_hndl, chunk)
        self.log.debug('Remote CSAR downloaded; closing temporary file')
        os.close(tmp_hndl)
        # Update the CSAR definition
        self.csar['local'] = tmp_filename

    def _extract(self):
        '''
            Extracts a CSAR package
        '''
        if not self.csar['local']:
            raise RuntimeError('Missing CSAR file')
        if not zipfile.is_zipfile(self.csar['local']):
            raise RuntimeError('CSAR file is not in ZIP format')
        # Get a temporary directory to use
        self.log.debug('Generating temporary directory')
        tmp_dirname = mkdtemp()
        self.log.debug('Temporary directory is: %s', tmp_dirname)
        # Extract ZIP file to temporary directory
        self.log.debug('Extracting CSAR contents')
        zfile = zipfile.ZipFile(self.csar['local'])
        zfile.extractall(tmp_dirname)
        self.log.debug('CSAR contents successfully extracted')
        # Update the CSAR definition
        self.csar['destination'] = tmp_dirname

    def _validate(self):
        '''
            Validates a CSAR package
        '''
        csar_root = self.csar.get('destination')
        # Check for a CSAR contents folder
        if not csar_root or not os.path.isdir(csar_root):
            raise RuntimeError('Missing CSAR contents')
        # Validate metadata
        if self.has_metadata_file:
            self._validate_metadata_file()
        else:
            self._validate_metadata_inline()
        # Validate entry definitions
        self._validate_entry_definitions()
        # Validate artifacts
        self._validate_artifacts()

    def _validate_metadata_file(self):
        '''
            Validates CSAR metadata file
        '''
        # Check for metadata
        csar_metafile = os.path.join(self.path, constants.META_FILE)
        self.log.debug('CSAR metadata file: %s', csar_metafile)
        # Check the expected files/folders exist
        if not csar_metafile or not os.path.isfile(csar_metafile):
            raise RuntimeError('Missing CSAR metadata file')
        # Validate metadata YAML
        metadata = dict()
        self.log.debug('Attempting to parse CSAR metadata YAML')
        with open(csar_metafile, 'r') as mfile:
            metadata = yaml.load(mfile)
        self.log.debug('CSAR metadata:\n%s', pformat(metadata))
        # Validate metadata specification
        if constants.META_FILE_VERSION_KEY not in metadata:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_FILE_VERSION_KEY)
        if str(metadata[constants.META_FILE_VERSION_KEY]) != '1.0':
            raise RuntimeError('Metadata "%s" must be 1.0' %
                               constants.META_FILE_VERSION_KEY)
        if constants.META_CSAR_VERSION_KEY not in metadata:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_CSAR_VERSION_KEY)
        if str(metadata[constants.META_CSAR_VERSION_KEY]) != '1.1':
            raise RuntimeError('Metadata "%s" must be 1.1' %
                               constants.META_CSAR_VERSION_KEY)
        if constants.META_CREATED_BY_KEY not in metadata or \
           not metadata[constants.META_CREATED_BY_KEY]:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_CREATED_BY_KEY)
        if constants.META_ENTRY_DEFINITIONS_KEY not in metadata or \
           not metadata[constants.META_ENTRY_DEFINITIONS_KEY]:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_ENTRY_DEFINITIONS_KEY)
        # Update the CSAR definition
        self.csar['metadata'] = metadata

    def _validate_metadata_inline(self):
        '''
            Validates CSAR inline metadata
        '''
        # Get a list of all definition files in the root folder
        root_defs = list()
        self.log.debug('Searching for TOSCA template file with metadata')
        for ext in ['yaml', 'yml']:
            root_defs.extend(glob('%s/*.%s' % (self.path, ext)))
        # Make sure there's only one
        if len(root_defs) is not 1:
            raise RuntimeError(
                'Exactly 1 YAML file must exist in the CSAR root directory')
        # Validate metadata YAML
        def_data = dict()
        self.log.debug('Attempting to parse CSAR metadata YAML')
        with open(root_defs[0], 'r') as def_file:
            def_data = yaml.load(def_file)
        # Validate metadata specification
        metadata = def_data.get('metadata')
        if not metadata:
            raise RuntimeError('Missing metadata section')
        if constants.META_TMPL_VERSION_KEY not in metadata:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_TMPL_VERSION_KEY)
        if str(metadata[constants.META_TMPL_VERSION_KEY]) != '1.1':
            raise RuntimeError('Metadata "%s" must be 1.1' %
                               constants.META_TMPL_VERSION_KEY)
        if constants.META_TMPL_AUTHOR_KEY not in metadata or \
           not metadata[constants.META_TMPL_AUTHOR_KEY]:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_TMPL_AUTHOR_KEY)
        if constants.META_TMPL_NAME_KEY not in metadata or \
           not metadata[constants.META_TMPL_NAME_KEY]:
            raise RuntimeError('Missing metadata "%s"' %
                               constants.META_TMPL_NAME_KEY)
        # Update the CSAR definition
        metadata[constants.META_ENTRY_DEFINITIONS_KEY] = root_defs[0]
        self.csar['metadata'] = metadata

    def _validate_entry_definitions(self):
        '''
            Validates entry definitions
        '''
        self.log.debug('CSAR entry definitions: %s', self.entry_definitions)
        if not self.has_metadata_file:
            self.log.debug('Using inline metadata; skipping...')
            return
        if not os.path.isfile(os.path.join(self.path,
                                           self.entry_definitions)):
            raise RuntimeError('"%s" points to "%s", but the file '
                               'does not exist' % (
                                   constants.META_ENTRY_DEFINITIONS_KEY,
                                   self.entry_definitions))

    def _validate_artifacts(self):
        '''
            Validates artifacts
        '''
        self.log.debug('Searching for user-defined MIME types')
        mtypes = glob(os.path.join(self.path, constants.META_MIMETYPES_GLOB))
        self.log.debug('Loading %s user-defined MIME types', len(mtypes))
        mimetypes.init(mtypes or None)
        self.log.debug('Checking for artifacts')
        if not self.artifacts:
            self.log.debug('No artifacts declared')
            return
        # Iterate through each artifacts
        for name, artifact in self.artifacts.iteritems():
            self._validate_artifact(name, artifact)

    def _validate_artifact(self, name, artifact):
        '''
            Validates a single artifact
        '''
        self.log.debug('Validating artifact: %s', name)
        self.log.debug('Checking if artifact file exists')
        path = os.path.join(self.path, name)
        if not os.path.isfile(path):
            raise RuntimeError('Artifact "%s" delcared, but file does '
                               'not exist' % name)
        # Validate the content-type
        if 'content-type' not in artifact:
            raise RuntimeError('Artifact missing "content-type"')
        self.log.debug('Artifact content-type: %s', artifact['content-type'])
        tstype = artifact['content-type'].split('/')
        if len(tstype) < 2:
            raise RuntimeError('Artifact content-type must comply with the '
                               '"type/subtype" structure')
        if not tstype[-1].startswith('vnd.'):
            self.log.warn('Artifact content-type subtype should start '
                          'with "vnd."')
        # Validate content-type as a known MIME type
        self.log.debug('Checking content-type against known MIME types')
        if len([{x: y} for x, y in mimetypes.types_map.iteritems()
                if y == artifact['content-type']]) < 1:
            self.log.warn('Could not match artifact content-type '
                          'with any known MIME type')
        # Validate the artifact MIME type against the content-type
        self.log.debug('Checking artifact MIME type against content-type')
        mtype = mimetypes.guess_type(path)[0]
        if mtype is None:
            self.log.warn('Could not match artifact to a known MIME type')
        if mtype != artifact['content-type']:
            self.log.warn('Artifact content-type does not match the '
                          'artifacts MIME type')
        # Validate the signature / digest
        if 'signature' in artifact:
            sig = artifact['signature']
            algo = sig.get('algorithm')
            digest = sig.get('digest')
            if not algo:
                raise RuntimeError(
                    'Artifact signature delcared, but no algorithm was found')
            if not digest:
                raise RuntimeError(
                    'Artifact signature delcared, but no digest was found')
            # Decode base64 encoded digest
            self.log.debug('Decoding base64-encoded artifact digest')
            digest = b64decode(digest).strip()
            self.log.debug('Decoded artifact digest: %s', digest)
            # Calculate hash of the actual artifact
            self.log.debug('Calculating %s digest of artifact %s', algo, name)
            adigest = hashlib.new(algo, open(path, 'rb').read()).hexdigest()
            self.log.debug('Calculated artifact digest: %s', adigest)
            # Compare digests
            if digest != adigest:
                raise RuntimeError('Artifact digest mismatch')
