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
    nfvo_packager.write
    ~~~~~~~~~~~~~~~~~~~
    CSAR writer interface for building CSAR packages
'''

import os.path
from aria import install_aria_extensions
from aria.tools.utils import create_context
from aria.consumption import Read, Validate, Template, Inputs, Plan
from aria.consumption.consumer import ConsumerChain
from aria.loading import DefaultLoaderSource
from aria.reading import DefaultReaderSource
from aria.presentation import DefaultPresenterSource
from aria.presentation.presenter import Presenter
import ruamel.yaml as yaml


META_INF_DIR = 'Meta-Inf'
MANIFEST_FILE = os.path.join(META_INF_DIR, 'MANIFEST.MF')


class CSARWriter(object):
    '''CSAR writer interface'''
    def __init__(self, path):
        if not path or not isinstance(path, basestring):
            raise RuntimeError('Missing or invalid folder path')
        # Ensure the path is absolute
        path = os.path.abspath(path)
        # Test that the path exists
        if not os.path.isdir(path):
            raise RuntimeError(
                'Path "%s" either does not exist or is not a folder' % path)
        # Save the path for later use
        self.path = path
        # Validate the manifest file
        # self.validate_manifest()
        install_aria_extensions()
        context = create_context(
            os.path.join(self.path, MANIFEST_FILE),
            'aria.loading.DefaultLoaderSource',
            'aria.reading.YamlReader',
            'aria.presentation.DefaultPresenterSource',
            'aria.presentation.Presenter',
            True
        )
        consumer = ConsumerChain(
            context,
            (Read, Validate))
        consumer.append(Template, Plan)
        consumer.consume()
        print vars(consumer.context)
        # print consumer.consumers[-1].dump()
        print context.validation.issues
        for issue in context.validation.issues:
            print vars(issue)

    def validate_meta_inf(self):
        '''Validates the existence of the Meta-Inf folder'''
        # Test that the Meta-Inf folder exists
        if not os.path.isdir(os.path.join(self.path, META_INF_DIR)):
            raise RuntimeError(
                'Path "%s" either does not exist or is not a folder' %
                os.path.join(self.path, META_INF_DIR))

    def validate_manifest(self):
        '''Validates the existence and format of the manifest file'''
        self.validate_meta_inf()
        # Check for a MANIFEST.MF file
        if not os.path.isfile(os.path.join(self.path, MANIFEST_FILE)):
            raise RuntimeError(
                'Could not find a "%s" file' % MANIFEST_FILE)
        # Read in YAML contents
        manifest = None
        with open(os.path.join(self.path, MANIFEST_FILE), 'r') as f_manifest:
            manifest = yaml.load(f_manifest)
        if manifest is None:
            raise RuntimeError(
                'Empty "%s" file format' % MANIFEST_FILE)
        print 'manifest: %s' % manifest
