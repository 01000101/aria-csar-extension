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
    nfvo_packager.writer
    ~~~~~~~~~~~~~~~~~~~~
    CSAR interface for creating CSAR packages
'''

import logging
import os
import shutil
from tempfile import mkstemp, mkdtemp
from pprint import pformat
import zipfile
import yaml
import hashlib
import hmac

from nfvo_packager import constants
from nfvo_packager.reader import CSARReader

logging.basicConfig(level=logging.DEBUG)


class CSARWriter(object):
    '''
        TOSCA Cloud Service Archive (CSAR) writer. This class
        is a helper for building CSAR v1.1 ZIP packages.

    :param str source: Path to the root directory to use
    :param str entry: Relative (from root directory) path to the definitions
                      entry file.
    '''
    def __init__(self, source, entry='tosca_elk.yaml',
                 author='TOSCA', output='./build.csar.zip',
                 logger=None):
        self.log = logger or logging.getLogger('csar.writer')
        self.log.debug('CSARWriter(%s, %s)', source, entry)
        self.csar = {
            # User-supplied source data
            'source': source,
            # Relative definitions entry point
            'entry': entry,
            # Working CSAR data
            'local': None,
            # Final CSAR file destination path
            'destination': output,
            # Working metadata
            'metadata': {
                'TOSCA-Meta-File-Version': '1.0',
                'CSAR-Version': '1.1',
                'Created-By': author,
                'Entry-Definitions': entry
            }
        }
        self._validate_pre()
        # ZIPs the contents if a directory was provided
        # copies ZIP file if a non-CSAR ZIP file was provided
        self._zip()
        # Create metadata file
        self.create_metadata()
        # Move the archive to the user-specified destination
        self.log.debug('Copying CSAR to destination path: %s'
                       % self.archive)
        shutil.copy(self.csar['local'], self.archive)
        # Validate non-CSAR data
        self.reader = CSARReader(self.archive)

    @property
    def archive(self):
        '''Returns the (compressed) CSAR path'''
        return self.csar.get('destination')

    @property
    def metadata(self):
        '''Returns CSAR metadata'''
        return self.csar.get('metadata', dict())

    @property
    def artifacts(self):
        '''Returns CSAR artifacts'''
        return self.metadata.get('artifacts', dict())

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
    def entry_definitions(self):
        '''Returns the Entry-Definitions (relative) path'''
        return self.metadata.get(constants.META_ENTRY_DEFINITIONS_KEY)

    def _zip(self):
        '''
            Creates, or copies, a ZIP file of the non-CSAR data
        '''
        # Get a temporary file
        self.log.debug('Generating temporary file')
        tmp_hndl, tmp_filename = mkstemp('.csar.zip')
        self.log.debug('Temporary file is: %s', tmp_filename)
        os.close(tmp_hndl)
        # Copy ZIP to ZIP
        if os.path.isfile(self.csar['source']) and \
           self.csar['source'].endswith('.zip'):
            self.log.debug('Copying ZIP file from "%s" to "%s"' % (
                self.csar['source'], tmp_filename))
            shutil.copy(self.csar['source'], tmp_filename)
        elif os.path.isdir(self.csar['source']):
            self.log.debug('Compressing root directory to ZIP')
            ziph = zipfile.ZipFile(tmp_filename, 'w', zipfile.ZIP_DEFLATED)
            for _root, _dirs, files in os.walk(self.csar['source']):
                for _file in files:
                    self.log.debug('Writing to archive: %s',
                                   os.path.relpath(os.path.join(_root, _file),
                                                   self.csar['source']))
                    ziph.write(os.path.join(_root, _file),
                               os.path.relpath(os.path.join(_root, _file),
                                               self.csar['source']))
            ziph.close()
        # Update the CSAR definition
        self.csar['local'] = tmp_filename

    def _validate_pre(self):
        '''
            Validates a proposed CSAR package (before ZIP)
        '''
        # Check the provided path
        if not os.path.exists(self.csar['source']):
            raise RuntimeError('CSAR source path does not exist')

    def create_metadata(self):
        '''
            Creates a new TOSCA CSAR metadata file
        '''
        self.log.debug('Opening archive for updating')
        ziph = zipfile.ZipFile(self.csar['local'], 'a', zipfile.ZIP_DEFLATED)
        self.log.debug('Writing new metadata file to %s'
                       % constants.META_FILE)
        ziph.writestr(constants.META_FILE,
                      yaml.dump(self.metadata, default_flow_style=False))
        ziph.close()

    def create_signature(self, keydata, outfile=None):
        '''
            Creates a signature for the CSAR package

        :param str keydata: Key signing data
        :param str outfile: If set, writes the signature to an output file at
            this path.
        :rtype: str
        :returns: Signature string
        '''
        sig_builder = hmac.new(keydata, digestmod=hashlib.sha384)
        # Open the CSAR for reading
        if not self.csar['destination']:
            raise RuntimeError(
                'Cannot calculate signature before CSAR package exists')
        fcsar = open(self.csar['destination'], 'rb')
        # Read in chunks and prepare for signature calculation
        self.log.debug('Using CSAR package at "%s"',self.csar['destination'])
        self.log.debug('Preparing to calculate CSAR signature')
        try:
            while True:
                block = fcsar.read(4096)
                if not block:
                    break
                sig_builder.update(block)
        finally:
            fcsar.close()
        # Get the actual signature
        self.log.debug('Calculating CSAR signature')
        digest = sig_builder.hexdigest()
        self.log.debug('Calculated CSAR signature as "%s"', digest)
        # Write signature to file if needed
        if outfile:
            self.log.debug('Writing signature to file "%s"', outfile)
            with open(outfile, 'w') as fsig:
                fsig.write(digest)
        # Return the signature
        return digest

    def verify_signature(self, keydata, digest=None, sigfile=None):
        '''
            Verifies a signature for the CSAR package

        :note: This method request `digest` OR `sigfile` to be specified.
            If both are specified, `digest` takes precedence.

        :param str keydata: Key signing data
        :param str digest: Signature string
        :param str sigfile: Path to a signature file
        :rtype: boolean
        :returns: True if signature is verified, False if not
        '''
        # Sanity checks
        if not digest and not sigfile:
            raise RuntimeError('"digest" or "sigfile" must be set')
        # Get signature from file if not from string
        if digest:
            self.log.debug('Using signature from string')
        elif sigfile:
            self.log.debug('Using signature from file "%s"', sigfile)
            with open(sigfile, 'r') as sfile:
                digest = sfile.read()
        # Signature normalization
        if not isinstance(digest, basestring):
            raise RuntimeError('Existing signature must be a string type')
        digest = digest.strip()
        # Calculate fresh signature
        real_digest = self.create_signature(keydata)
        # Verify signatures
        return hmac.compare_digest(digest, real_digest)


