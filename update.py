#!/usr/bin/env python

import os
import sys
import datetime
import ast
import collections

# we do not use the nicer sys.version_info.major
# for compatibility with Python < 2.7
if sys.version_info[0] > 2:
    from io import StringIO
    import urllib.request

    class URLopener(urllib.request.FancyURLopener):
        def http_error_default(self, url, fp, errcode, errmsg, headers):
            sys.stderr.write("ERROR: could not fetch {}\n".format(url))
            sys.exit(-1)
else:
    from StringIO import StringIO
    import urllib

    class URLopener(urllib.FancyURLopener):
        def http_error_default(self, url, fp, errcode, errmsg, headers):
            sys.stderr.write("ERROR: could not fetch {}\n".format(url))
            sys.exit(-1)


AUTOCMAKE_GITHUB_URL = 'https://github.com/scisoft/autocmake'

# ------------------------------------------------------------------------------


def replace(s, d):
    from re import findall
    if isinstance(s, str):
        for var in findall(r"%\(([A-Za-z0-9_]*)\)", s):
            s = s.replace("%({})".format(var), d[var])
    return s


def test_replace():
    assert replace('hey %(foo) ho %(bar)',
                   {'foo': 'hey', 'bar': 'ho'}) == 'hey hey ho ho'

# ------------------------------------------------------------------------------


def interpolate(d, d_map):
    from collections import Mapping
    for k, v in d.items():
        if isinstance(v, Mapping):
            d[k] = interpolate(d[k], d_map)
        else:
            d[k] = replace(d[k], d_map)
    return d


def test_interpolate():
    d = {'foo': 'hey',
         'bar': 'ho',
         'one': 'hey %(foo) ho %(bar)',
         'two': {'one': 'hey %(foo) ho %(bar)',
                 'two': 'raboof'}}
    d_interpolated = {'foo': 'hey',
                      'bar': 'ho',
                      'one': 'hey hey ho ho',
                      'two': {'one': 'hey hey ho ho',
                              'two': 'raboof'}}
    assert interpolate(d, d) == d_interpolated

# ------------------------------------------------------------------------------


def fetch_url(src, dst):
    """
    Fetch file from URL src and save it to dst.
    """
    dirname = os.path.dirname(dst)
    if dirname != '':
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

    opener = URLopener()
    opener.retrieve(src, dst)

# ------------------------------------------------------------------------------


def parse_yaml(file_name):
    import yaml

    def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
        class OrderedLoader(Loader):
            pass
        def construct_mapping(loader, node):
            loader.flatten_mapping(node)
            return object_pairs_hook(loader.construct_pairs(node))
        OrderedLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping)
        return yaml.load(stream, OrderedLoader)

    with open(file_name, 'r') as stream:
        try:
            config = ordered_load(stream, yaml.SafeLoader)
        except yaml.YAMLError as exc:
            print(exc)
            sys.exit(-1)

    config = interpolate(config, config)
    return config

# ------------------------------------------------------------------------------


def print_progress_bar(text, done, total, width):
    """
    Print progress bar.
    """
    n = int(float(width) * float(done) / float(total))
    sys.stdout.write("\r{0} [{1}{2}] ({3}/{4})".format(text, '#' * n,
                                              ' ' * (width - n), done, total))
    sys.stdout.flush()

# ------------------------------------------------------------------------------


def align_options(options):
    """
    Indents flags and aligns help texts.
    """
    l = 0
    for opt in options:
        if len(opt[0]) > l:
            l = len(opt[0])
    s = []
    for opt in options:
        s.append('  {0}{1}  {2}'.format(opt[0], ' ' * (l - len(opt[0])), opt[1]))
    return '\n'.join(s)

# ------------------------------------------------------------------------------


def gen_cmake_command(config):
    """
    Generate CMake command.
    """
    s = []

    s.append("\n\ndef gen_cmake_command(options, arguments):")
    s.append('    """')
    s.append("    Generate CMake command based on options and arguments.")
    s.append('    """')
    s.append("    command = []")

    # take care of environment variables
    for section in config.sections():
        if config.has_option(section, 'export'):
            for env in config.get(section, 'export').split('\n'):
                s.append('    command.append({})'.format(env))

    s.append("    command.append(arguments['--cmake-executable'])")

    # take care of cmake definitions
    for section in config.sections():
        if config.has_option(section, 'define'):
            for definition in config.get(section, 'define').split('\n'):
                s.append('    command.append({})'.format(definition))

    s.append("    command.append('-DCMAKE_BUILD_TYPE={}'.format(arguments['--type']))")
    s.append("    command.append('-G \"{}\"'.format(arguments['--generator']))")
    s.append("    if arguments['--cmake-options'] != \"''\":")
    s.append("        command.append(arguments['--cmake-options'])")
    s.append("    if arguments['--prefix']:")
    s.append("        command.append('-DCMAKE_INSTALL_PREFIX=\"{0}\"'.format(arguments['--prefix']))")

    s.append("\n    return ' '.join(command)")

    return '\n'.join(s)

# ------------------------------------------------------------------------------


def autogenerated_notice():
    current_year = datetime.date.today().year
    year_range = '2015-{}'.format(current_year)
    s = []
    s.append('# This file is autogenerated by Autocmake http://autocmake.org')
    s.append('# Copyright (c) {} by Radovan Bast and Jonas Juselius'.format(year_range))
    return '\n'.join(s)

# ------------------------------------------------------------------------------


def gen_setup(config, relative_path, setup_script_name):
    """
    Generate setup script.
    """
    s = []
    s.append('#!/usr/bin/env python')
    s.append('\n{}'.format(autogenerated_notice()))
    s.append('\nimport os')
    s.append('import sys')

    s.append("\nsys.path.insert(0, '{0}')".format(relative_path))
    s.append("sys.path.insert(0, '{0}')".format(os.path.join(relative_path, 'lib')))
    s.append("sys.path.insert(0, '{0}')".format(os.path.join(relative_path, 'lib', 'docopt')))

    s.append('import config')
    s.append('import docopt')

    s.append('\n\noptions = """')
    s.append('Usage:')
    s.append('  ./{0} [options] [<builddir>]'.format(setup_script_name))
    s.append('  ./{0} (-h | --help)'.format(setup_script_name))
    s.append('\nOptions:')

    options = []
    for section in config.sections():
        if config.has_option(section, 'docopt'):
            for opt in config.get(section, 'docopt').split('\n'):
                first = opt.split()[0].strip()
                rest = ' '.join(opt.split()[1:]).strip()
                options.append([first, rest])

    options.append(['--type=<TYPE>', 'Set the CMake build type (debug, release, or relwithdeb) [default: release].'])
    options.append(['--generator=<STRING>', 'Set the CMake build system generator [default: Unix Makefiles].'])
    options.append(['--show', 'Show CMake command and exit.'])
    options.append(['--cmake-executable=<CMAKE_EXECUTABLE>', 'Set the CMake executable [default: cmake].'])
    options.append(['--cmake-options=<STRING>', "Define options to CMake [default: '']."])
    options.append(['--prefix=<PATH>', 'Set the install path for make install.'])
    options.append(['<builddir>', 'Build directory.'])
    options.append(['-h --help', 'Show this screen.'])

    s.append(align_options(options))

    s.append('"""')

    s.append(gen_cmake_command(config))

    s.append("\n")
    s.append("# parse command line args")
    s.append("try:")
    s.append("    arguments = docopt.docopt(options, argv=None)")
    s.append("except docopt.DocoptExit:")
    s.append(r"    sys.stderr.write('ERROR: bad input to {}\n'.format(sys.argv[0]))")
    s.append("    sys.stderr.write(options)")
    s.append("    sys.exit(-1)")
    s.append("\n")
    s.append("# use extensions to validate/post-process args")
    s.append("if config.module_exists('extensions'):")
    s.append("    import extensions")
    s.append("    arguments = extensions.postprocess_args(sys.argv, arguments)")
    s.append("\n")
    s.append("root_directory = os.path.dirname(os.path.realpath(__file__))")
    s.append("\n")
    s.append("build_path = arguments['<builddir>']")
    s.append("\n")
    s.append("# create cmake command")
    s.append("cmake_command = '{0} {1}'.format(gen_cmake_command(options, arguments), root_directory)")
    s.append("\n")
    s.append("# run cmake")
    s.append("config.configure(root_directory, build_path, cmake_command, arguments['--show'])")

    return s

# ------------------------------------------------------------------------------


def gen_cmakelists(project_name, min_cmake_version, relative_path, modules):
    """
    Generate CMakeLists.txt.
    """
    s = []

    s.append(autogenerated_notice())

    s.append('\n# set minimum cmake version')
    s.append('cmake_minimum_required(VERSION {} FATAL_ERROR)'.format(min_cmake_version))

    s.append('\n# project name')
    s.append('project({})'.format(project_name))

    s.append('\n# do not rebuild if rules (compiler flags) change')
    s.append('set(CMAKE_SKIP_RULE_DEPENDENCY TRUE)')

    s.append('\n# if CMAKE_BUILD_TYPE undefined, we set it to Debug')
    s.append('if(NOT CMAKE_BUILD_TYPE)')
    s.append('    set(CMAKE_BUILD_TYPE "Debug")')
    s.append('endif()')

    if len(modules) > 0:
        s.append('\n# directories which hold included cmake modules')

    module_paths = [module.path for module in modules]
    module_paths.append('downloaded')  # this is done to be able to find fetched modules when testing
    module_paths = list(set(module_paths))
    module_paths.sort()  # we do this to always get the same order and to minimize diffs
    for directory in module_paths:
        rel_cmake_module_path = os.path.join(relative_path, directory)
        # on windows cmake corrects this so we have to make it wrong again
        rel_cmake_module_path = rel_cmake_module_path.replace('\\', '/')
        s.append('set(CMAKE_MODULE_PATH ${{CMAKE_MODULE_PATH}} ${{PROJECT_SOURCE_DIR}}/{})'.format(rel_cmake_module_path))

    if len(modules) > 0:
        s.append('\n# included cmake modules')
    for module in modules:
        s.append('include({})'.format(os.path.splitext(module.name)[0]))

    return s

# ------------------------------------------------------------------------------


def prepend_or_set(config, section, option, value, defaults):
    """
    If option is already set, then value is prepended.
    If option is not set, then it is created and set to value.
    This is used to prepend options with values which come from the module documentation.
    """
    if value:
        if config.has_option(section, option):
            value += '\n{}'.format(config.get(section, option, 0, defaults))
        config.set(section, option, value)
    return config

# ------------------------------------------------------------------------------


def fetch_modules(config, relative_path):
    """
    Assemble modules which will
    be included in CMakeLists.txt.
    """

    download_directory = 'downloaded'
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    l = list(filter(lambda x: config.has_option(x, 'source'),
                    config.sections()))
    n = len(l)

    modules = []
    Module = collections.namedtuple('Module', 'path name')

    warnings = []

    if n > 0:  # otherwise division by zero in print_progress_bar
        i = 0
        print_progress_bar(text='- assembling modules:', done=0, total=n, width=30)
        for section in config.sections():
            if config.has_option(section, 'source'):
                for src in config.get(section, 'source').split('\n'):
                    module_name = os.path.basename(src)
                    if 'http' in src:
                        path = download_directory
                        name = 'autocmake_{}'.format(module_name)
                        dst = os.path.join(download_directory, 'autocmake_{}'.format(module_name))
                        fetch_url(src, dst)
                        file_name = dst
                        fetch_dst_directory = download_directory
                    else:
                        if os.path.exists(src):
                            path = os.path.dirname(src)
                            name = module_name
                            file_name = src
                            fetch_dst_directory = path
                        else:
                            sys.stderr.write("ERROR: {} does not exist\n".format(src))
                            sys.exit(-1)

                    if config.has_option(section, 'override'):
                        defaults = ast.literal_eval(config.get(section, 'override'))
                    else:
                        defaults = {}

                    # we infer config from the module documentation
                    with open(file_name, 'r') as f:
                        parsed_config = parse_cmake_module(f.read(), defaults)
                        if parsed_config['warning']:
                            warnings.append('WARNING from {0}: {1}'.format(module_name, parsed_config['warning']))
                        config = prepend_or_set(config, section, 'docopt', parsed_config['docopt'], defaults)
                        config = prepend_or_set(config, section, 'define', parsed_config['define'], defaults)
                        config = prepend_or_set(config, section, 'export', parsed_config['export'], defaults)
                        if parsed_config['fetch']:
                            for src in parsed_config['fetch'].split('\n'):
                                dst = os.path.join(fetch_dst_directory, os.path.basename(src))
                                fetch_url(src, dst)

                    modules.append(Module(path=path, name=name))
                i += 1
                print_progress_bar(
                    text='- assembling modules:',
                    done=i,
                    total=n,
                    width=30
                )
            if config.has_option(section, 'fetch'):
                # when we fetch directly from autocmake.yml
                # we download into downloaded/
                for src in config.get(section, 'fetch').split('\n'):
                    dst = os.path.join(download_directory, os.path.basename(src))
                    fetch_url(src, dst)
        print('')

    if warnings != []:
        print('- {}'.format('\n- '.join(warnings)))

    return modules

# ------------------------------------------------------------------------------


def main(argv):
    """
    Main function.
    """
    if len(argv) != 2:
        sys.stderr.write("\nYou can update a project in two steps.\n\n")
        sys.stderr.write("Step 1: Update or create infrastructure files\n")
        sys.stderr.write("        which will be needed to configure and build the project:\n")
        sys.stderr.write("        $ {} --self\n\n".format(argv[0]))
        sys.stderr.write("Step 2: Create CMakeLists.txt and setup script in PROJECT_ROOT:\n")
        sys.stderr.write("        $ {} <PROJECT_ROOT>\n".format(argv[0]))
        sys.stderr.write("        example:\n")
        sys.stderr.write("        $ {} ..\n".format(argv[0]))
        sys.exit(-1)

    if argv[1] in ['-h', '--help']:
        print('Usage:')
        print('  python update.py --self         Update this script and fetch or update infrastructure files under lib/.')
        print('  python update.py <builddir>     (Re)generate CMakeLists.txt and setup script and fetch or update CMake modules.')
        print('  python update.py (-h | --help)  Show this help text.')
        sys.exit(0)

    if argv[1] == '--self':
        # update self
        if not os.path.isfile('autocmake.yml'):
            print('- fetching example autocmake.yml')  # FIXME
            fetch_url(
                src='{}/raw/master/example/autocmake.yml'.format(AUTOCMAKE_GITHUB_URL),
                dst='autocmake.yml'
            )
        if not os.path.isfile('.gitignore'):
            print('- creating .gitignore')
            with open('.gitignore', 'w') as f:
                f.write('*.pyc\n')
        print('- fetching lib/config.py')
        fetch_url(
            src='{}/raw/master/lib/config.py'.format(AUTOCMAKE_GITHUB_URL),
            dst='lib/config.py'
        )
        print('- fetching lib/docopt/docopt.py')
        fetch_url(
            src='{}/raw/master/lib/docopt/docopt.py'.format(AUTOCMAKE_GITHUB_URL),
            dst='lib/docopt/docopt.py'
        )
        print('- fetching update.py')
        fetch_url(
            src='{}/raw/master/update.py'.format(AUTOCMAKE_GITHUB_URL),
            dst='update.py'
        )
        sys.exit(0)

    project_root = argv[1]
    if not os.path.isdir(project_root):
        sys.stderr.write("ERROR: {} is not a directory\n".format(project_root))
        sys.exit(-1)

    # read config file
    print('- parsing autocmake.yml')
    config = parse_yaml('autocmake.yml')

    if 'name' in config:
        project_name = config['name']
    else:
        sys.stderr.write("ERROR: you have to specify the project name in autocmake.yml\n")
        sys.exit(-1)
    if ' ' in project_name.rstrip():
        sys.stderr.write("ERROR: project name contains a space\n")
        sys.exit(-1)

    if 'min_cmake_version' in config:
        min_cmake_version = config['min_cmake_version']
    else:
        sys.stderr.write("ERROR: you have to specify min_cmake_version in autocmake.yml\n")
        sys.exit(-1)

    if 'setup_script' in config:
        setup_script_name = config['setup_script']
    else:
        setup_script_name = 'setup'

    # get relative path from setup script to this directory
    relative_path = os.path.relpath(os.path.abspath('.'), project_root)

    # fetch modules from the web or from relative paths
    modules = fetch_modules(config, relative_path)

    # create CMakeLists.txt
    print('- generating CMakeLists.txt')
    s = gen_cmakelists(project_name, min_cmake_version, relative_path, modules)
    with open(os.path.join(project_root, 'CMakeLists.txt'), 'w') as f:
        f.write('{}\n'.format('\n'.join(s)))

    # create setup script
    print('- generating setup script')
    s = gen_setup(config, relative_path, setup_script_name)
    file_path = os.path.join(project_root, setup_script_name)
    with open(file_path, 'w') as f:
        f.write('{}\n'.format('\n'.join(s)))
    if sys.platform != 'win32':
        make_executable(file_path)

# ------------------------------------------------------------------------------


# http://stackoverflow.com/a/30463972
def make_executable(path):
    mode = os.stat(path).st_mode
    mode |= (mode & 0o444) >> 2    # copy R bits to X
    os.chmod(path, mode)

# ------------------------------------------------------------------------------


def parse_cmake_module(s_in, defaults={}):

    parsed_config = collections.defaultdict(lambda: None)

    if 'autocmake.yml configuration::' not in s_in:
        return parsed_config

    s_out = []
    is_rst_line = False
    for line in s_in.split('\n'):
        if is_rst_line:
            if len(line) > 0:
                if line[0] != '#':
                    is_rst_line = False
            else:
                is_rst_line = False
        if is_rst_line:
            s_out.append(line[2:])
        if '#.rst:' in line:
            is_rst_line = True

    autocmake_entry = '\n'.join(s_out).split('autocmake.yml configuration::')[1]
    autocmake_entry = autocmake_entry.replace('\n  ', '\n')

    # FIXME
    # we prepend a fake section heading so that we can parse it with configparser
    autocmake_entry = '[foo]\n' + autocmake_entry

    buf = StringIO(autocmake_entry)
    config = ConfigParser(dict_type=collections.OrderedDict)
    config.readfp(buf)

    for section in config.sections():
        for s in ['docopt', 'define', 'export', 'fetch', 'warning']:
            if config.has_option(section, s):
                parsed_config[s] = config.get(section, s, 0, defaults)

    return parsed_config

# ------------------------------------------------------------------------------


def test_parse_cmake_module():

    s = '''#.rst:
#
# Foo ...
#
# autocmake.yml configuration::
#
#   docopt: --cxx=<CXX> C++ compiler [default: g++].
#           --extra-cxx-flags=<EXTRA_CXXFLAGS> Extra C++ compiler flags [default: ''].
#   export: 'CXX={}'.format(arguments['--cxx'])
#   define: '-DEXTRA_CXXFLAGS="{}"'.format(arguments['--extra-cxx-flags'])

enable_language(CXX)

if(NOT DEFINED CMAKE_C_COMPILER_ID)
    message(FATAL_ERROR "CMAKE_C_COMPILER_ID variable is not defined!")
endif()'''

    parsed_config = parse_cmake_module(s)
    assert parsed_config['docopt'] == "--cxx=<CXX> C++ compiler [default: g++].\n--extra-cxx-flags=<EXTRA_CXXFLAGS> Extra C++ compiler flags [default: '']."

    s = '''#.rst:
#
# Foo ...
#
# Bar ...

enable_language(CXX)

if(NOT DEFINED CMAKE_C_COMPILER_ID)
    message(FATAL_ERROR "CMAKE_C_COMPILER_ID variable is not defined!")
endif()'''

    parsed_config = parse_cmake_module(s)
    assert parsed_config['docopt'] is None

# ------------------------------------------------------------------------------


if __name__ == '__main__':
    main(sys.argv)
