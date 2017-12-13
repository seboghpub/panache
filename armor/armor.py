#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" armor: pandoc wrapped in styles
for more info: <https://github.com/sebogh/armor>
Author    : Sebastian Bogan <sebogh@qibli.net>
Copyright : Copyright 2017, Sebastian Bogan
License   : BSD3
"""

import os
import errno
import sys
import tempfile
import re
import yaml
import logging
from datetime import datetime
from subprocess import Popen
from typing import List

from armor.armorstyle import ArmorStyle
from armor.armorstyles import ArmorStyles
from armor.passthroughoptionparser import PassThroughOptionParser
from armor.armorexception import ArmorException
from armor.armoryaml import STYLEDEF_, STYLES_, STYLE_, PARENT_, COMMANDLINE_, METADATA_, FILTER_, RUN_, KILL_


# check script environment
script = os.path.realpath(sys.argv[0])
script_dir = os.path.dirname(script)
base_dir = os.path.realpath(os.path.join(script_dir, ".."))
script_base = os.path.basename(script)


def parse_cmdline(cl: List[str]):
    """Parse and validate the command line.
    """

    default_style_dir = os.path.join(base_dir, "styles")
    if not os.path.isdir(default_style_dir):
        default_style_dir = None

    usage = "%s [<OPTIONS>] [<PANDOC-OPTIONS>]" % script_base
    parser = PassThroughOptionParser(usage, add_help_option=False)
    parser.add_option("--input", dest="input", default="")
    parser.add_option("--output", dest="output", default="")
    parser.add_option("-h", "--help", dest="help", action="store_true", default=False)
    parser.add_option("--style", dest="style", default="")
    parser.add_option("--medium", dest="medium", default="")
    parser.add_option("--debug", dest="debug", action="store_true", default=False)
    parser.add_option("--style-dir", dest="style_dir", default=default_style_dir)

    (options, args) = parser.parse_args(cl)

    if options.help:
        os.sys.stderr.write("""
NAME

    {name}

SYNOPSIS

    {usage}

DESCRIPTION

    Pandoc wrapper implementing styles.

OPTIONS

    --input=<PATH>
        The input path. Default STDIN.
    --output=<PATH>
        The output path. Default STDOUT.
    --style=<STYLE>
        The style to use.
    --medium=<MEDIUM>
        The target medium.
    --style-dir=<PATH>
        Where to find style definitions. 
        (Default: '{default_style_dir}'.  
    --debug
        Print the Pandoc command line to STDERR.
    -h, --help
        Print this help message.

PANDOC-OPTIONS

    Any argument not being one of the above options is passed down to Pandoc. 

AUTHOR

    Sebastian Bogan sebastian.bogan@t-systems.com

""".format({'name': script_base, 'usage': usage, 'default_style_dir': default_style_dir}))
        sys.exit(0)

    # path to the input- and output-file
    if options.input:
        options.input = os.path.abspath(options.input)
        if not os.path.isfile(options.input):
            raise ArmorException("No such file '%s'." % options.input, 102)

    if options.output:
        options.output = os.path.abspath(options.output)

    # check style-dir
    if options.style_dir:
        options.style_dir = os.path.abspath(options.style_dir)
        if not os.path.isdir(options.style_dir):
            raise ArmorException("No such directory '%s'." % options.style_dir, 103)

    if options.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    return options, args


# see: https://stackoverflow.com/a/10840586
def silent_remove(filename):
    """" Remove a file if it exists.
    """
    try:
        os.remove(filename)
    except OSError as e:

        # filter out errno.ENOENT (no such file or directory)
        if e.errno != errno.ENOENT:

            # but re-raise any other
            raise


def get_yaml_lines(lines: list):
    """" Strip `lines' to those lines that are YAML.
    """
    start = re.compile('^[-]{3}\s*$', flags=0)
    stop = re.compile('^[-\.]{3}\s*$', flags=0)
    in_yaml = False
    yaml_lines = list()
    for line in lines:
        if not in_yaml:
            if start.match(line):
                in_yaml = True
        else:
            if stop.match(line):
                in_yaml = False
            else:
                yaml_lines.append(line)
    return yaml_lines


def get_input_yaml(file):
    """" Get YAML from a Pandoc-flavored Markdown file.
    """

    # read lines from file
    with open(file, "r", encoding='utf-8') as f:
        lines = f.readlines()

    # strip lines to those that are YAML
    yaml_lines = get_yaml_lines(lines)
    if not yaml_lines:
        return None

    # load and return YAML data
    return yaml.load(''.join(yaml_lines))


def determine_style(options, input_yaml):
    """ Determine the style to use.
    """

    # a style named on the command line has highest priority
    if options.style:
        return options.style
    # if there is no style named on the command line a style named in the input would be used
    if STYLE_ in input_yaml:
        return input_yaml[STYLE_]
    # if there is no style named on the command line nor in the input a "medium" -> "style" match would be used
    if options.medium and STYLES_ in input_yaml and options.medium in input_yaml[STYLES_]:
        return input_yaml[STYLES_][options.medium]
    return None


def compile_command_line(input_file, metadata_file, parameters, options, args):

    # compile command line
    command = ["pandoc"]

    if metadata_file:
        command.append(metadata_file)
    command.append(input_file)
    if options.output:
        command.append('--output=%s' % options.output)
    for key, value in parameters[COMMANDLINE_].items():
        if isinstance(parameters[COMMANDLINE_][key], bool):
            if parameters[COMMANDLINE_][key]:
                command.append('--%s' % key)
        else:
            command.append('--%s=%s' % (key, value))
    #command.append('--style-dir=%s' % options.style_dir)
    #command.append('--resource-path=%s' % options.style_dir)
    for run_filter in parameters[FILTER_]:
        command.append('--filter=%s' % run_filter)

    command.extend(list(args))

    # possibly print the command line
    if options.debug:
        sys.stderr.write("Running:\n  %s\n" % " ".join(command))
        sys.stderr.flush()

    return command

def add_special_meta(input_file, options, metadata):
    input_file_dir = os.path.dirname(input_file)
    input_file_basename = os.path.basename(input_file)
    input_file_rootname, _ = os.path.splitext(input_file_basename)
    metadata['date'] = "'%s'" % datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    if options.style_dir:
        metadata['staticDir'] = "'%s'" % options.style_dir.replace('\\', '/')
    if options.input:
        metadata['source_path'] = "'%s'" % input_file_dir
        metadata['source'] = "'%s'" % input_file_basename
        metadata['rootname'] = "'%s'" % input_file_rootname

    return metadata


def main():

    try:

        # parse and validate command line
        options, args = parse_cmdline(sys.argv[1:])

        # initialize styles from the data directory
        armor_styles = ArmorStyles()
        if options.style_dir:
            armor_styles.load(options.style_dir)

        # copy STDIN to a temporary file, iff needed
        input_file = options.input
        if not options.input:
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write(sys.stdin.buffer.read())
                input_file = f.name

        # load YAML from input (either the temporary file or the one name on the command line)
        input_yaml = get_input_yaml(input_file)

        # update (or add) style definitions based on definitions in the input file
        if input_yaml and STYLEDEF_ in input_yaml:
            for style_name in input_yaml[STYLEDEF_]:
                armor_styles.update(ArmorStyle(style_name, input_yaml[STYLEDEF_][style_name], input_file))

        # determine desired style
        style = determine_style(options, input_yaml)

        # resolve style to Pandoc compile parameters (and metadata)
        parameters = armor_styles.resolve(style)

        # add special metadata
        parameters[METADATA_] = add_special_meta(input_file, options, parameters[METADATA_])

        # write the computed metadata to a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write("---\n".encode())
            f.write(yaml.dump(parameters[METADATA_], encoding='utf-8'))
            f.write("---\n".encode())
            metadata_file = f.name

        # change to the directory containing the input, if not STDIN
        if options.input:
            os.chdir(os.path.dirname(options.input))

        # compile the command
        command = compile_command_line(input_file, metadata_file, parameters, options, args)

        # run the command
        process = Popen(command, stdout=sys.stdout, stderr=sys.stderr)
        process.wait()

        # delete the temporary files
        #silent_remove(metadata_file)
        if not options.input:
            silent_remove(input_file)

    except ArmorException as e:
        sys.stderr.write(e.message)
        sys.exit(e.code)




if __name__ == "__main__":
    main()
