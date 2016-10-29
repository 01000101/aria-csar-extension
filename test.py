#!/usr/bin/python
'''Test application'''

import os
from aria import install_aria_extensions
from aria.consumption import (
    ConsumptionContext,
    ConsumerChain,
    Read, Validate, Model, Instance)
from aria.loading import LiteralLocation

from nfvo_packager.writer import CSARReader, CSARWriter

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
    context.loading.prefixes += search_paths
    ConsumerChain(context, (Read, Validate, Model, Instance)).consume()
    if not context.validation.dump_issues():
        return context.modeling.instance
    return None


def dump_info(csar):
    '''Dumps information from a CSAR reader'''
    print 'Path: %s' % csar.path
    print 'Author: %s' % csar.author
    print 'Version: %s' % csar.version
    print 'Metadata file version: %s' % csar.metadata_file_version
    print 'Entry definitions: %s' % csar.entry_definitions

    # Send the package to ARIA for parsing
    # Including the /definitions directory for searching
    aria_res = parse_text(
        csar.entry_definitions_yaml,
        [os.path.join(csar.path, 'definitions')])
    # Dump information about the final blueprint
    for _, node in aria_res.nodes.items():
        print '\nNode: %s:' % node.id
        print '| type: %s' % node.type_name
        print '| template: %s' % node.template_name
        print '| properties:'
        for pname, prop in node.properties.items():
            print '  | %s: %s' % (pname, prop.value)
        print '| capabilities:'
        for _, capability in node.capabilities.items():
            print '  | %s:' % capability.name
            for pname, prop in capability.properties.items():
                print '    | %s: %s' % (pname, prop.value)


def main():
    '''Entry point'''
    print '\n\n======================='
    print '== VNF CHAINING CSAR =='
    print '======================='
    build = CSARWriter('examples/csar_vnf_chaining',
                       entry='service.yaml',
                       author='Gigaspaces',
                       output='examples/csar_vnf_chaining.zip')
    dump_info(build.reader)
    
    print '\n\n==================================='
    print '== HELLO WORLD CSAR W/ ARTIFACTS =='
    print '==================================='
    dump_info(CSARReader('examples/csar_hello_world.zip'))


main()
