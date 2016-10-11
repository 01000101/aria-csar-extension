#!/usr/bin/python
'''Test application'''

import os
from aria import install_aria_extensions
from aria.consumption import (
    ConsumptionContext,
    ConsumerChain,
    Read, Validate, Model, Instance)
from aria.loading import LiteralLocation

from nfvo_packager.csar import CSAR

install_aria_extensions()


def parse_text(payload, search_paths=None):
    '''
        Parses a TOSCA blueprint set
    :returns: ARIA model or None
    :rtype: `aria.modeling.instance_elements.ServiceInstance`
    '''
    search_paths = search_paths or list()
    context = ConsumptionContext()
    context.presentation.location = LiteralLocation(payload)
    context.loading.file_search_paths += search_paths
    ConsumerChain(context, (Read, Validate, Model, Instance)).consume()
    if not context.validation.dump_issues():
        return context.modeling.instance
    return None


def main():
    '''Entry point'''
    csar = CSAR('examples/csar_hello_world.zip')
    # Validate the package format
    csar.validate()
    # Extract the package locally for debugging
    csar.decompress()
    # Dump information about the package
    print 'Vars: %s' % vars(csar)
    print 'Metadata: %s' % csar.get_metadata()
    print 'Version: %s' % csar.get_version()
    print 'Author: %s' % csar.get_author()
    print 'Description: %s' % csar.get_description()
    print 'Main template: %s' % csar.get_main_template()
    print 'Main template YAML: %s' % csar.get_main_template_yaml()
    print 'Temp dir: %s' % os.listdir(csar.temp_dir)
    # Send the package to ARIA for parsing
    # Including the /Definitions directory for searching
    aria_res = parse_text(
        csar.get_main_template_yaml(),
        [os.path.join(csar.temp_dir, 'Definitions')])
    # Dump information about the final blueprint
    for _, node in aria_res.nodes.items():
        print 'Node: %s:' % node.id
        print '| type: %s' % node.type_name
        print '| template: %s' % node.template_name
        print '| properties: %s' % node.properties
        print '| capabilities:'
        for _, capability in node.capabilities.items():
            print '  | %s:' % capability.name
            for pname, prop in capability.properties.items():
                print '    | %s: %s' % (pname, prop.value)


main()
