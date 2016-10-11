#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os.path
import shutil
import tempfile
import zipfile
import requests
import six
import yaml

from nfvo_packager.utils import UrlUtils
from nfvo_packager.imports import ImportsLoader

try:  # Python 2.x
    from BytesIO import BytesIO
except ImportError:  # Python 3.x
    from io import BytesIO


class CSAR(object):

    def __init__(self, csar_file, a_file=True):
        self.path = csar_file
        self.a_file = a_file
        self.is_validated = False
        self.error_caught = False
        self.csar = None
        self.temp_dir = None
        self.zfile = None
        self.metadata = None

    def validate(self):
        """Validate the provided CSAR file."""

        self.is_validated = True

        # validate that the file or URL exists
        missing_err_msg = '"%s" does not exist' % self.path
        if self.a_file:
            if not os.path.isfile(self.path):
                raise RuntimeError(missing_err_msg)
            self.csar = self.path
        else:  # a URL
            if not UrlUtils.validate_url(self.path):
                raise RuntimeError(missing_err_msg)
            response = requests.get(self.path)
            self.csar = BytesIO(response.content)

        # validate that it is a valid zip file
        if not zipfile.is_zipfile(self.csar):
            raise RuntimeError('"%s" is not a valid zip file' % self.path)

        # validate that it contains the metadata file in the correct location
        self.zfile = zipfile.ZipFile(self.csar, 'r')
        filelist = self.zfile.namelist()
        if 'TOSCA-Metadata/TOSCA.meta' not in filelist:
            raise RuntimeError(
                '"%s" is not a valid CSAR as it does not contain the '
                'required file "TOSCA.meta" in the folder '
                '"TOSCA-Metadata"' % self.path)

        # validate that 'Entry-Definitions' property exists in TOSCA.meta
        data = self.zfile.read('TOSCA-Metadata/TOSCA.meta')
        invalid_yaml_err_msg = 'The file "TOSCA-Metadata/TOSCA.meta" in ' \
                               'the CSAR "%s" does not contain valid YAML ' \
                               'content' % self.path
        try:
            meta = yaml.load(data)
            if not isinstance(meta, dict):
                raise RuntimeError(invalid_yaml_err_msg)
            self.metadata = meta
        except yaml.YAMLError:
            raise RuntimeError(invalid_yaml_err_msg)

        if 'Entry-Definitions' not in self.metadata:
            raise RuntimeError(
                'The CSAR "%s" is missing the required metadata '
                '"Entry-Definitions" in '
                '"TOSCA-Metadata/TOSCA.meta"' % self.path)

        # validate that 'Entry-Definitions' metadata value points to an
        # existing file in the CSAR
        entry = self.metadata.get('Entry-Definitions')
        if entry and entry not in filelist:
            raise RuntimeError(
                'The "Entry-Definitions" file defined in the '
                'CSAR "%s" does not exist' % self.path)

        # validate that external references in the main template actually
        # exist and are accessible
        self._validate_external_references()
        return not self.error_caught

    def get_metadata(self):
        """Return the metadata dictionary."""

        # validate the csar if not already validated
        if not self.is_validated:
            self.validate()

        # return a copy to avoid changes overwrite the original
        return dict(self.metadata) if self.metadata else None

    def _get_metadata(self, key):
        if not self.is_validated:
            self.validate()
        return self.metadata.get(key)

    def get_author(self):
        return self._get_metadata('Created-By')

    def get_version(self):
        return self._get_metadata('CSAR-Version')

    def get_main_template(self):
        entry_def = self._get_metadata('Entry-Definitions')
        if entry_def in self.zfile.namelist():
            return entry_def

    def get_main_template_yaml(self):
        main_template = self.get_main_template()
        if main_template:
            data = self.zfile.read(main_template)
            invalid_tosca_yaml_err_msg = \
                'The file "%(template)s" in the CSAR "%(csar)s" does not ' \
                'contain valid TOSCA YAML content' % {
                    'template': main_template,
                    'csar': self.path
                }
            try:
                tosca_yaml = yaml.load(data)
                if not isinstance(tosca_yaml, dict):
                    raise RuntimeError(invalid_tosca_yaml_err_msg)
                return tosca_yaml
            except Exception as ex:
                raise RuntimeError(ex)

    def get_description(self):
        desc = self._get_metadata('Description')
        if desc is not None:
            return desc

        self.metadata['Description'] = \
            self.get_main_template_yaml().get('description')
        return self.metadata['Description']

    def decompress(self):
        if not self.is_validated:
            self.validate()
        self.temp_dir = tempfile.NamedTemporaryFile().name
        with zipfile.ZipFile(self.csar, "r") as zf:
            zf.extractall(self.temp_dir)

    def _validate_external_references(self):
        """Extracts files referenced in the main template

        These references are currently supported:
        * imports
        * interface implementations
        * artifacts
        """
        try:
            self.decompress()
            main_tpl_file = self.get_main_template()
            if not main_tpl_file:
                return
            main_tpl = self.get_main_template_yaml()

            if 'imports' in main_tpl:
                imports = main_tpl['imports']
                imports.remove(
                    'tosca-simple-profile-1.0/tosca-simple-profile-1.0.yaml')
                if imports:
                    ImportsLoader(
                        imports,
                        os.path.join(self.temp_dir, main_tpl_file))

            if 'topology_template' in main_tpl:
                topology_template = main_tpl['topology_template']

                if 'node_templates' in topology_template:
                    node_templates = topology_template['node_templates']

                    for node_template_key in node_templates:
                        node_template = node_templates[node_template_key]
                        if 'artifacts' in node_template:
                            artifacts = node_template['artifacts']
                            for artifact_key in artifacts:
                                artifact = artifacts[artifact_key]
                                if isinstance(artifact, six.string_types):
                                    self._validate_external_reference(
                                        main_tpl_file,
                                        artifact)
                                elif isinstance(artifact, dict):
                                    if 'file' in artifact:
                                        self._validate_external_reference(
                                            main_tpl_file,
                                            artifact['file'])
                                else:
                                    raise RuntimeError(
                                        'Unexpected artifact definition for %s'
                                        % artifact_key)
                        if 'interfaces' in node_template:
                            interfaces = node_template['interfaces']
                            for interface_key in interfaces:
                                interface = interfaces[interface_key]
                                for opertation_key in interface:
                                    operation = interface[opertation_key]
                                    if isinstance(operation, six.string_types):
                                        self._validate_external_reference(
                                            main_tpl_file,
                                            operation,
                                            False)
                                    elif isinstance(operation, dict):
                                        if 'implementation' in operation:
                                            self._validate_external_reference(
                                                main_tpl_file,
                                                operation['implementation'])
        finally:
            if self.temp_dir:
                shutil.rmtree(self.temp_dir)

    def _validate_external_reference(self, tpl_file, resource_file,
                                     raise_exc=True):
        """Verify that the external resource exists

        If resource_file is a URL verify that the URL is valid.
        If resource_file is a relative path verify that the path is valid
        considering base folder (self.temp_dir) and tpl_file.
        Note that in a CSAR resource_file cannot be an absolute path.
        """
        if UrlUtils.validate_url(resource_file):
            msg = (_('The resource at "%s" cannot be accessed') %
                   resource_file)
            try:
                if UrlUtils.url_accessible(resource_file):
                    return
                else:
                    raise RuntimeError(
                        'The resource at "%s" cannot be accessed'
                        % resource_file)
            except Exception as ex:
                raise RuntimeError(ex)

        if os.path.isfile(os.path.join(self.temp_dir,
                                       os.path.dirname(tpl_file),
                                       resource_file)):
            return

        if raise_exc:
            raise RuntimeError(
                'The resource "%s" does not exist'
                % resource_file)
