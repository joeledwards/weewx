#!/usr/bin/env python
#
#    weewx --- A simple, high-performance weather station server
#
#    Copyright (c) 2009-2020 Tom Keffer <tkeffer@gmail.com>
#
#    See the file LICENSE.txt for your full rights.
#
"""Customized setup file for weewx."""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import with_statement

import distutils.dir_util
import distutils.file_util
import fnmatch
import os.path
import shutil
import sys
import tempfile
from distutils.command.install_data import install_data
from distutils.command.install_lib import install_lib
# Useful for debugging setup.py. Set the environment variable
# DISTUTILS_DEBUG to get more debug info.
from distutils.debug import DEBUG
from setuptools import setup, find_packages
from setuptools.command.install import install

if sys.version_info < (2, 7):
    print('WeeWX requires Python V2.7 or greater.')
    print('For earlier versions of Python, use WeeWX V3.9.')
    sys.exit("Python version unsupported.")

# Find the install bin subdirectory:
this_file = os.path.join(os.getcwd(), __file__)
this_dir = os.path.abspath(os.path.dirname(this_file))
bin_dir = os.path.abspath(os.path.join(this_dir, 'bin'))

# Now that we've found the bin subdirectory, inject it into the path:
sys.path.insert(0, bin_dir)

# Now we can import some weewx modules
import weewx
import weeutil.weeutil

VERSION = weewx.__version__


# ==============================================================================
# install
# ==============================================================================

class weewx_install(install):
    """Specialized version of install, which adds a --no-prompt option to
    the 'install' command."""

    # Add an option for --no-prompt:
    user_options = install.user_options + [('no-prompt', None, 'Do not prompt for station info')]

    def initialize_options(self, *args, **kwargs):
        install.initialize_options(self, *args, **kwargs)
        self.no_prompt = None

    def finalize_options(self):
        install.finalize_options(self)
        if self.no_prompt is None:
            self.no_prompt = False

    def run(self):
        """Specialized version of run, which runs post-install commmands"""
        # First run the install.
        install.run(self)

        # Now the post-install
        update_and_install_config(self.install_data, no_prompt=self.no_prompt)


# ==============================================================================
# install_lib
# ==============================================================================

class weewx_install_lib(install_lib):
    """Specialized version of install_lib, which backs up old bin subdirectories."""

    def run(self):
        # Save any existing 'bin' subdirectory:
        if os.path.exists(self.install_dir):
            bin_savedir = weeutil.weeutil.move_with_timestamp(self.install_dir)
            print("Saved bin subdirectory as %s" % bin_savedir)
        else:
            bin_savedir = None

        # Run the superclass's version. This will install all incoming files.
        install_lib.run(self)

        # If the bin subdirectory previously existed, and if it included
        # a 'user' subsubdirectory, then restore it
        if bin_savedir:
            user_backupdir = os.path.join(bin_savedir, 'user')
            if os.path.exists(user_backupdir):
                user_dir = os.path.join(self.install_dir, 'user')
                distutils.dir_util.copy_tree(user_backupdir, user_dir)
                try:
                    # The file schemas.py is no longer used, and can interfere with schema
                    # imports. See issue #54.
                    os.rename(os.path.join(user_dir, 'schemas.py'),
                              os.path.join(user_dir, 'schemas.py.old'))
                except OSError:
                    pass
                try:
                    os.remove(os.path.join(user_dir, 'schemas.pyc'))
                except OSError:
                    pass


# ==============================================================================
# install_data
# ==============================================================================

class weewx_install_data(install_data):
    """Specialized version of install_data."""

    def initialize_options(self):
        # Initialize my superclass's options:
        install_data.initialize_options(self)
        # Set to None so we inherit whatever setting comes from weewx_install:
        self.no_prompt = None

    def finalize_options(self):
        # Finalize my superclass's options:
        install_data.finalize_options(self)
        # This will set no_prompt to whatever is in weewx_install:
        self.set_undefined_options('install', ('no_prompt', 'no_prompt'))

    def copy_file(self, f, install_dir, **kwargs):
        # If this is the configuration file, then process it separately
        if f == 'weewx.conf':
            rv = self.process_config_file(f, install_dir, **kwargs)
        else:
            rv = install_data.copy_file(self, f, install_dir, **kwargs)
        return rv

    def run(self):
        # If there is a skins directory already, just install what the user doesn't already have.
        if os.path.exists(os.path.join(self.install_dir, 'skins')):
            # A skins directory already exists. Build a list of skins that are missing and should
            # be added to it.
            install_files = []
            for skin_name in ['Ftp', 'Mobile', 'Rsync', 'Seasons', 'Smartphone', 'Standard']:
                rel_name = 'skins/' + skin_name
                if not os.path.exists(os.path.join(self.install_dir, rel_name)):
                    # The skin has not already been installed. Include it.
                    install_files += [dat for dat in self.data_files if
                                      dat[0].startswith(rel_name)]
            # Exclude all the skins files...
            other_files = [dat for dat in self.data_files if not dat[0].startswith('skins')]
            # ... then add the needed skins back in
            self.data_files = other_files + install_files

        # Run the superclass's run():
        install_data.run(self)

    def process_config_file(self, f, install_dir, **kwargs):

        install_path = os.path.join(install_dir, os.path.basename(f))

        if self.dry_run:
            rv = None
        else:
            # Install the config file using the template name. Later, we will merge
            # it with any old config file.
            template_name = install_path + ".template"
            rv = install_data.copy_file(self, f, template_name, **kwargs)
            shutil.copymode(f, template_name)

        return rv


# ==============================================================================
# utilities
# ==============================================================================
def find_files(directory, file_excludes=['*.pyc'], dir_excludes=['*/__pycache__']):
    """Find all files under a directory."""
    # First recursively create a list of all the directories
    dir_list = []
    for dirpath, _, _ in os.walk(directory):
        # Make sure the directory name doesn't match the excluded pattern
        if not any(fnmatch.fnmatch(dirpath, d) for d in dir_excludes):
            dir_list.append(dirpath)

    data_files = []
    # Now search each directory for all files
    for d_path in dir_list:
        file_list = []
        # Find all the files in this directory
        for fn in os.listdir(d_path):
            filepath = os.path.join(d_path, fn)
            # Make sure it's a file, and that it's name doesn't match the excluded pattern
            if os.path.isfile(filepath) and not any(
                    fnmatch.fnmatch(filepath, f) for f in file_excludes):
                file_list.append(filepath)
        # Add this to the list of data files.
        data_files.append((d_path, file_list))
    return data_files


def update_and_install_config(install_dir, config_name='weewx.conf',
                              no_prompt=False, dry_run=False):
    import configobj
    import weecfg

    # Open up and parse the config file that came with the distribution
    template_path = os.path.join(install_dir, config_name + ".template")
    try:
        dist_config_dict = configobj.ConfigObj(template_path,
                                               interpolation=False,
                                               file_error=True,
                                               encoding='utf-8')
    except IOError as e:
        sys.exit(e)
    except SyntaxError as e:
        sys.exit("Syntax error in distribution configuration file '%s': %s"
                 % (template_path, e))

    # The path where the weewx.conf configuration file will be installed
    install_path = os.path.join(install_dir, config_name)

    # Do we have an old config file?
    if os.path.isfile(install_path):
        # Yes. Read it
        config_path, config_dict = weecfg.read_config(install_path, None, interpolation=False)
        if DEBUG:
            print("Old configuration file found at", config_path)

        # Update the old configuration file to the current version,
        # then merge it into the distribution file
        weecfg.update_and_merge(config_dict, dist_config_dict)
    else:
        # No old config file. Use the distribution file, then, if we can,
        # prompt the user for station specific info
        config_dict = dist_config_dict
        if no_prompt:
            # The default station information:
            stn_info = {
                'station_type': 'Simulator',
                'driver': 'weewx.drivers.simulator'
            }
        else:
            # Prompt the user for the station information:
            stn_info = weecfg.prompt_for_info()
            driver = weecfg.prompt_for_driver(stn_info.get('driver'))
            stn_info['driver'] = driver
            stn_info.update(weecfg.prompt_for_driver_settings(driver, config_dict))
            if DEBUG:
                print("Station info =", stn_info)
        weecfg.modify_config(config_dict, stn_info, DEBUG)

    # Set the WEEWX_ROOT
    config_dict['WEEWX_ROOT'] = os.path.normpath(install_dir)

    # NB: use mkstemp instead of NamedTemporaryFile because we need to
    # do the delete (windows gets mad otherwise) and there is no delete
    # parameter in NamedTemporaryFile in python 2.5.

    # Time to write it out. Get a temporary file:
    tmpfd, tmpfn = tempfile.mkstemp()
    try:
        # We don't need the file descriptor
        os.close(tmpfd)
        # Set the filename we will write to
        config_dict.filename = tmpfn
        # Write the config file
        config_dict.write()

        # Save the old config file if it exists:
        if not dry_run and os.path.exists(install_path):
            backup_path = weeutil.weeutil.move_with_timestamp(install_path)
            print("Saved old configuration file as %s" % backup_path)
        if not dry_run:
            # Now install the temporary file (holding the merged config data)
            # into the proper place:
            distutils.file_util.copy_file(tmpfn, install_path)
            try:
                # Remove the template
                os.unlink(template_path)
            except OSError:
                pass
    finally:
        # Get rid of the temporary file
        os.unlink(tmpfn)


# ==============================================================================
# main entry point
# ==============================================================================

if __name__ == "__main__":
    # Use the README.md for the long description:
    with open(os.path.join(this_dir, "README.md"), "r") as fd:
        long_description = fd.read()

    setup(name='weewx',
          version=VERSION,
          description='The WeeWX weather software system',
          long_description=long_description,
          author='Tom Keffer',
          author_email='tkeffer@gmail.com',
          url='http://www.weewx.com',
          license='GPLv3',
          classifiers=[
              'Development Status :: 5 - Production/Stable',
              'Intended Audience :: End Users/Desktop',
              'Intended Audience :: Science/Research',
              'License :: GPLv3',
              'Operating System :: POSIX :: LINUX',
              'Operating System :: Unix',
              'Operating System :: MacOS',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2.7',
              'Programming Language :: Python :: 3.5',
              'Programming Language :: Python :: 3.6',
              'Programming Language :: Python :: 3.7',
              'Programming Language :: Python :: 3.8',
              'Topic:: Scientific / Engineering:: Physics'
          ],
          python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, <4',
          requires=[
              'cheetah3(>=3.0)',
              'configobj(>=4.7)',  # Python 3 requires >5.0
              'pillow(>=5.4)',
              'pyephem(>=3.7)',
              'pyserial(>=2.3)',
              'pyusb(>=1.0)',
              'six(>=1.12)'
          ],
          packages=find_packages('bin'),
          cmdclass={
              "install": weewx_install,
              "install_data": weewx_install_data,
              "install_lib": weewx_install_lib,
          },
          platforms=['any'],
          package_dir={'': 'bin'},
          py_modules=['daemon'],
          scripts=[
              'bin/wee_config',
              'bin/wee_database',
              'bin/wee_debug',
              'bin/wee_device',
              'bin/wee_extension',
              'bin/wee_import',
              'bin/wee_reports',
              'bin/weewxd',
              'bin/wunderfixer'
          ],
          data_files=[('', ['LICENSE.txt', 'README.md', 'weewx.conf']), ]
                     + find_files('docs')
                     + find_files('examples')
                     + find_files('skins')
                     + find_files('util')
          )
